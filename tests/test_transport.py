"""Unit tests for the FSL UDP transport and protocol framing."""

import struct
from unittest.mock import patch

from custom_components.ha_fsl_zhixing.const import (
    DEFAULT_CLIENT_MAC,
    DEFAULT_UDP_PORT,
    DISCOVERY_BROADCAST_ADDR,
    HEARTBEAT_MAX_MISSED,
    MSG_PROBE_REQ,
    MSG_SHORT_CTRL_REQ,
    SEQ_DEDUP_CACHE_SIZE,
)
from custom_components.ha_fsl_zhixing.transport import (
    FSLTimeoutError,
    FSLTransportError,
    FSLUdpClient,
    async_discover_gateways,
    build_status_trigger_payloads,
    format_mac_bytes,
    pack_frame,
    parse_mac_bytes,
    parse_telemetry_chunks,
    unpack_frame,
)
import pytest

from homeassistant.core import HomeAssistant

from .conftest import GATEWAY_IP, GATEWAY_MAC, MockUdpGateway, make_telemetry_chunk


def test_frame_pack_and_unpack() -> None:
    """Verify Little-Endian header encoding and payload slicing."""
    frame = pack_frame(MSG_SHORT_CTRL_REQ, 0x2330, b"\x05\x00\x80")
    assert frame == bytes.fromhex("09 00 30 23 05 00 80")
    msg_type, seq, payload = unpack_frame(frame)
    assert msg_type == MSG_SHORT_CTRL_REQ
    assert seq == 0x2330
    assert payload == b"\x05\x00\x80"

    with pytest.raises(ValueError, match="4-byte header"):
        unpack_frame(b"\x01\x00\x02")


@pytest.mark.parametrize(
    ("mac_input", "expected"),
    [
        pytest.param("02:00:00:00:00:54", "02:00:00:00:00:54", id="colon"),
        pytest.param("EC-0B-AE-A3-EA-15", "ec:0b:ae:a3:ea:15", id="dash-upper"),
        pytest.param("ec0baea3ea15", "ec:0b:ae:a3:ea:15", id="compact"),
    ],
)
def test_mac_roundtrip(mac_input: str, expected: str) -> None:
    """Parse and format 6-byte MAC strings consistently."""
    raw = parse_mac_bytes(mac_input)
    assert len(raw) == 6
    assert format_mac_bytes(raw) == expected


@pytest.mark.parametrize(
    "bad_mac",
    [
        pytest.param("02:00:00", id="too-short"),
        pytest.param("zz:00:00:00:00:54", id="non-hex"),
    ],
)
def test_invalid_mac_raises(bad_mac: str) -> None:
    """Reject malformed MAC address strings."""
    with pytest.raises(ValueError):
        parse_mac_bytes(bad_mac)


def test_parse_telemetry_chunks_standard_and_extended() -> None:
    """Decode both <=255 (0xC0) and >255 (0xC1+) Type 15 telemetry chunks."""
    payload = make_telemetry_chunk(8, b"\x7f\x00\x00\xff\x00\x00") + make_telemetry_chunk(
        257, b"\xc0\x00\x00\x00\x80\x7f"
    )
    chunks = parse_telemetry_chunks(payload)
    assert len(chunks) == 2
    assert chunks[0][0] == 8
    assert chunks[0][1][:6] == b"\x7f\x00\x00\xff\x00\x00"
    assert chunks[1][0] == 257
    assert chunks[1][1][:6] == b"\xc0\x00\x00\x00\x80\x7f"


def test_build_status_trigger_payloads() -> None:
    """Chunk Type 17 queries into 104-device Big-Endian masks."""
    assert build_status_trigger_payloads([]) == []

    single = build_status_trigger_payloads([8])
    assert len(single) == 1
    delay, start_addr = struct.unpack_from(">BH", single[0], 0)
    assert delay == 0
    assert start_addr == 8
    assert single[0][3] == 0x01
    assert single[0][4:] == b"\x00" * 12

    multi = build_status_trigger_payloads([1, 104, 105, 264])
    assert len(multi) == 3
    delay1, start1 = struct.unpack_from(">BH", multi[0], 0)
    assert delay1 == 31
    assert start1 == 1
    assert multi[0][3] == 0x01
    assert multi[0][3 + 12] == 0x80

    delay2, start2 = struct.unpack_from(">BH", multi[1], 0)
    assert delay2 == 31
    assert start2 == 105

    delay3, start3 = struct.unpack_from(">BH", multi[2], 0)
    assert delay3 == 31
    assert start3 == 264

    with pytest.raises(ValueError, match="power of 2"):
        build_status_trigger_payloads([1, 2], delay_max=10)


async def test_sequence_wraparound(hass: HomeAssistant) -> None:
    """Wrap 16-bit sequence numbers from 65535 back to 1."""
    client = FSLUdpClient(hass.loop, GATEWAY_IP, DEFAULT_UDP_PORT, DEFAULT_CLIENT_MAC)
    client._seq = 0xFFFE  # noqa: SLF001
    assert client._next_seq() == 0xFFFF  # noqa: SLF001
    assert client._next_seq() == 1  # noqa: SLF001


async def test_telemetry_ack_and_deduplication(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Mirror exact seq with Type 16 ACK and deduplicate across 128-seq ring buffer."""
    received: list[list[tuple[int, bytes]]] = []
    client = FSLUdpClient(
        hass.loop,
        GATEWAY_IP,
        DEFAULT_UDP_PORT,
        on_telemetry=received.append,
    )
    await client.async_connect()

    try:
        for seq in range(1, SEQ_DEDUP_CACHE_SIZE + 3):
            mock_gateway.push_telemetry(seq, [(8, b"\x80\x00\x00\x00\xff\x00")])

        assert len(received) == SEQ_DEDUP_CACHE_SIZE + 2
        assert len(mock_gateway.telemetry_acks) == SEQ_DEDUP_CACHE_SIZE + 2

        # seq=130 is still in the 128-entry cache: ACKed, not re-dispatched.
        mock_gateway.push_telemetry(
            SEQ_DEDUP_CACHE_SIZE + 2, [(8, b"\x00\x00\x00\x00\x00\x00")]
        )
        assert len(received) == SEQ_DEDUP_CACHE_SIZE + 2
        assert mock_gateway.telemetry_acks[-1] == SEQ_DEDUP_CACHE_SIZE + 2

        # seq=1 has been evicted from the 128-entry cache: ACKed and dispatched.
        mock_gateway.push_telemetry(1, [(8, b"\x80\x00\x00\x00\x00\xff")])
        assert len(received) == SEQ_DEDUP_CACHE_SIZE + 3
        assert mock_gateway.telemetry_acks[-1] == 1
    finally:
        await client.async_close()


async def test_discover_gateways(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Broadcast Type 1 probe and parse Type 2 unicast gateway responses."""
    gateways = await async_discover_gateways(hass.loop, timeout=0.01)
    assert len(gateways) == 1
    assert gateways[0].ip == GATEWAY_IP
    assert gateways[0].mac == GATEWAY_MAC
    assert any(
        addr == (DISCOVERY_BROADCAST_ADDR, DEFAULT_UDP_PORT)
        and unpack_frame(frame)[0] == MSG_PROBE_REQ
        for frame, addr in mock_gateway.sent_frames
    )

    mock_gateway.respond_probe = False
    assert await async_discover_gateways(hass.loop, timeout=0.01) == []


async def test_heartbeat_watchdog_and_recovery(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Mark unavailable after 5 missed heartbeats and recover when responses resume."""
    availability_events: list[bool] = []
    client = FSLUdpClient(
        hass.loop,
        GATEWAY_IP,
        DEFAULT_UDP_PORT,
        on_availability_changed=availability_events.append,
    )
    await client.async_connect()

    try:
        with (
            patch("custom_components.ha_fsl_zhixing.transport.REQUEST_TIMEOUT", 0.01),
            patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        ):
            assert await client.async_heartbeat() == GATEWAY_MAC
            assert client.available is True

            mock_gateway.drop_all_heartbeats = True
            for expected_misses in range(1, HEARTBEAT_MAX_MISSED):
                assert await client.async_heartbeat_tick() is False
                assert client.missed_heartbeats == expected_misses
                assert client.available is True

            assert await client.async_heartbeat_tick() is False
            assert client.available is False
            assert availability_events == [False]

            mock_gateway.drop_all_heartbeats = False
            assert await client.async_heartbeat_tick() is True
            assert client.available is True
            assert client.missed_heartbeats == 0
            assert availability_events == [False, True]
    finally:
        await client.async_close()


async def test_request_timeout_and_malformed_datagram(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Handle request timeouts and ignore malformed UDP packets gracefully."""
    client = FSLUdpClient(hass.loop, GATEWAY_IP, DEFAULT_UDP_PORT)
    await client.async_connect()
    try:
        client.datagram_received(b"\x01\x00", (GATEWAY_IP, DEFAULT_UDP_PORT))
        mock_gateway.drop_control = True
        with pytest.raises(FSLTimeoutError):
            await client.async_request(MSG_SHORT_CTRL_REQ, 10, b"\x01\x00\x00", timeout=0.01)

        client.error_received(OSError("udp error"))
        client.connection_lost(OSError("socket reset"))
        assert client._transport is None  # noqa: SLF001
    finally:
        await client.async_close()


@pytest.mark.parametrize(
    ("raw_url", "expected_url"),
    [
        pytest.param(
            "192.168.1.50:50397/family.dat",
            "http://192.168.1.50:50397/family.dat",
            id="schemeless",
        ),
        pytest.param(
            "http://192.168.1.50:50397/family.dat",
            "http://192.168.1.50:50397/family.dat",
            id="http-prefix",
        ),
        pytest.param(
            "https://192.168.1.50:50397/family.dat",
            "https://192.168.1.50:50397/family.dat",
            id="https-prefix",
        ),
    ],
)
async def test_get_device_url_normalizes_scheme(
    hass: HomeAssistant,
    mock_gateway: MockUdpGateway,
    raw_url: str,
    expected_url: str,
) -> None:
    """Prepend http:// when Type 6 URL omits a scheme and preserve existing ones."""
    mock_gateway.url_factory = lambda _seq: raw_url
    client = FSLUdpClient(hass.loop, GATEWAY_IP, DEFAULT_UDP_PORT)
    await client.async_connect()
    try:
        assert await client.async_get_device_url(timeout=0.1) == expected_url
    finally:
        await client.async_close()


async def test_get_device_url_empty_raises(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Reject empty Type 6 URL responses."""
    mock_gateway.url_factory = lambda _seq: ""
    client = FSLUdpClient(hass.loop, GATEWAY_IP, DEFAULT_UDP_PORT)
    await client.async_connect()
    try:
        with pytest.raises(FSLTransportError, match="empty Type 6"):
            await client.async_get_device_url(timeout=0.1)
    finally:
        await client.async_close()
