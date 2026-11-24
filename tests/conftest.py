"""Shared fixtures and mock UDP gateway simulator for FSL tests."""

import asyncio
import base64
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable
import json
import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from custom_components import ha_fsl_zhixing
from custom_components.ha_fsl_zhixing import config_flow, light
from custom_components.ha_fsl_zhixing.const import (
    CONF_CLIENT_MAC,
    CONF_GATEWAY_MAC,
    DEFAULT_CLIENT_MAC,
    DEFAULT_UDP_PORT,
    DOMAIN,
    MSG_DATA_REPORT_REQ,
    MSG_DATA_REPORT_RESP,
    MSG_DEV_URL_REQ,
    MSG_DEV_URL_RESP,
    MSG_HEARTBEAT_REQ,
    MSG_HEARTBEAT_RESP,
    MSG_PROBE_REQ,
    MSG_PROBE_RESP,
    MSG_SHORT_CTRL_REQ,
    MSG_SHORT_CTRL_RESP,
    MSG_STATUS_TRIGGER_REQ,
    MSG_STATUS_TRIGGER_RESP,
)
from custom_components.ha_fsl_zhixing.transport import pack_frame, parse_mac_bytes, unpack_frame
import pytest

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from tests.common import (  # noqa: TID251
    MockConfigEntry,
    MockModule,
    mock_integration,
    mock_platform,
)

GATEWAY_IP = "192.168.1.50"
GATEWAY_MAC = "ec:0b:ae:a3:ea:15"
GATEWAY_DID = "00000000000000000000ec0baea3ea15"
MANIFEST_URL = "192.168.1.50:50397/family.dat"


def make_spid(dev_t: int) -> str:
    """Build a 16-byte BroadLink SPID hex string encoding dev_t in LE bytes 12-13."""
    return "00" * 12 + dev_t.to_bytes(2, "little").hex() + "0000"


def make_telemetry_chunk(short_addr: int, dev_payload: bytes) -> bytes:
    """Build a single Type 15 length-prefixed telemetry chunk (standard or > 255)."""
    padded = (dev_payload + b"\x00" * 15)[:15]
    addr_mode = 0xC0 | ((short_addr >> 8) & 0x0F)
    addr_lsb = short_addr & 0xFF
    chunk = bytes([addr_mode, 0xF1, 0x5E, 0xF5, addr_lsb, 0x00, 0x60]) + padded
    return bytes([len(chunk)]) + chunk


def encode_manifest(
    devlist: list[dict[str, Any]],
    roomlist: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Encode devlist and familyInfo into the Type 6 gateway JSON manifest format."""
    rooms = roomlist if roomlist is not None else [
        {"roomId": 0, "roomName": "Whole House"},
        {"roomId": 1, "roomName": "Living Room"},
        {"roomId": 2, "roomName": "Bedroom"},
    ]
    dev_b64 = base64.b64encode(json.dumps(devlist).encode("utf-8")).decode("ascii")
    family_b64 = base64.b64encode(
        json.dumps({"name": "Test Home", "roomlist": rooms, "updateTime": 1}).encode(
            "utf-8"
        )
    ).decode("ascii")
    return {
        "status": 0,
        "data": [
            {
                "did": "family_1",
                "dataList": [
                    {"mtag": "devlist", "data": dev_b64},
                    {"mtag": "familyInfo", "data": family_b64},
                ],
            }
        ],
    }


def make_sample_devlist() -> list[dict[str, Any]]:
    """Build a mixed device list covering all 10 lighting types, gateways, and ignored."""
    return [
        {
            "did": GATEWAY_DID,
            "pid": make_spid(43500),
            "devname": "FSL Main Gateway",
            "room": "Whole House",
            "roomId": 0,
            "version": "1.0.0",
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_332",
            "shortaddr": "1",
            "spid": make_spid(43049),
            "type_no": 332,
            "blecatetory": "LIGHT",
            "devname": "White Bulb",
            "room": "Living Room",
            "roomId": 1,
            "version": "4.1.0.2056.15",
            "ignoreflag": False,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_301",
            "shortaddr": "2",
            "spid": make_spid(43051),
            "type_no": 301,
            "dev_version": "1",
            "blecatetory": "CWLIGHT",
            "devname": "Main Ceiling",
            "room": "Living Room",
            "roomId": 1,
            "version": "4.1.0.2056.58",
            "ignoreflag": False,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_352",
            "shortaddr": "3",
            "spid": make_spid(43168),
            "type_no": 352,
            "blecatetory": "RGBLIGHT",
            "devname": "RGB Strip",
            "room": "Bedroom",
            "roomId": 2,
            "version": "4.1.0.2056.58",
            "ignoreflag": False,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_331",
            "shortaddr": "264",
            "spid": make_spid(43050),
            "type_no": 331,
            "blecatetory": "RGBCWLIGHT",
            "devname": "Extended RGBCW Lamp",
            "room": "Bedroom",
            "roomId": 2,
            "version": "4.1.0.2056.60",
            "ignoreflag": False,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_ignored",
            "shortaddr": "10",
            "spid": make_spid(43051),
            "type_no": 304,
            "blecatetory": "CWLIGHT",
            "devname": "Ignored Spotlight",
            "room": "Living Room",
            "roomId": 1,
            "version": "4.1.0.2056.15",
            "ignoreflag": True,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_radar_338",
            "shortaddr": "11",
            "spid": make_spid(44876),
            "type_no": 338,
            "blecatetory": "LIGHT",
            "devname": "Out of Scope Radar",
            "room": "Living Room",
            "roomId": 1,
            "version": "4.1.0.2056.80",
            "ignoreflag": False,
        },
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_sensor",
            "shortaddr": "12",
            "spid": make_spid(43505),
            "blecatetory": "DOOR_SENSOR",
            "devname": "Door Sensor",
            "room": "Living Room",
            "roomId": 1,
            "version": "4.1.0.2056.15",
            "ignoreflag": False,
        },
    ]


class MockDatagramTransport(asyncio.DatagramTransport):
    """In-memory datagram transport forwarding frames to MockUdpGateway."""

    def __init__(
        self,
        gateway: MockUdpGateway,
        protocol: asyncio.DatagramProtocol,
        remote_addr: tuple[str, int] | None,
    ) -> None:
        """Initialize mock datagram transport."""
        super().__init__()
        self._gateway = gateway
        self._protocol = protocol
        self._remote_addr = remote_addr
        self._closing = False

    def is_closing(self) -> bool:
        """Return whether the mock transport is closing."""
        return self._closing

    def close(self) -> None:
        """Close the mock transport and notify protocol."""
        if not self._closing:
            self._closing = True
            self._gateway.unregister_protocol(self._protocol)
            self._protocol.connection_lost(None)

    def abort(self) -> None:
        """Abort the mock transport."""
        self.close()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        """Return extra transport metadata."""
        return default

    def sendto(
        self, data: bytes | bytearray | memoryview, addr: tuple[str, int] | None = None
    ) -> None:
        """Forward outgoing datagram bytes to the mock gateway."""
        target = addr or self._remote_addr or (self._gateway.ip, self._gateway.port)
        self._gateway.handle_outgoing(bytes(data), target, self._protocol)


class MockUdpGateway:
    """In-memory FASTCON BLE Gateway simulator operating without real OS sockets."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        ip: str = GATEWAY_IP,
        port: int = DEFAULT_UDP_PORT,
        mac: str = GATEWAY_MAC,
    ) -> None:
        """Initialize the simulated gateway."""
        self.loop = loop
        self.ip = ip
        self.port = port
        self.mac = mac
        self.mac_bytes = parse_mac_bytes(mac)

        self.protocols: list[asyncio.DatagramProtocol] = []
        self.sent_frames: list[tuple[bytes, tuple[str, int]]] = []
        self.received_by_type: dict[int, list[tuple[int, bytes]]] = defaultdict(list)
        self.control_commands: list[tuple[int, bytes]] = []
        self.status_triggers: list[tuple[int, int, bytes]] = []
        self.telemetry_acks: list[int] = []

        self.respond_probe = True
        self.drop_heartbeats = 0
        self.drop_all_heartbeats = False
        self.drop_url_requests = False
        self.drop_control = False
        self.drop_status_trigger = False
        self.url_factory: Callable[[int], str] = lambda seq: f"{MANIFEST_URL}?seq={seq}"

    def unregister_protocol(self, protocol: asyncio.DatagramProtocol) -> None:
        """Remove a closed protocol instance."""
        if protocol in self.protocols:
            self.protocols.remove(protocol)

    async def create_datagram_endpoint(
        self,
        protocol_factory: Callable[[], asyncio.DatagramProtocol],
        local_addr: tuple[str, int] | None = None,
        remote_addr: tuple[str, int] | None = None,
        allow_broadcast: bool = False,
        **kwargs: Any,
    ) -> tuple[asyncio.DatagramTransport, asyncio.DatagramProtocol]:
        """Bind a protocol to an in-memory MockDatagramTransport."""
        protocol = protocol_factory()
        transport = MockDatagramTransport(self, protocol, remote_addr)
        self.protocols.append(protocol)
        protocol.connection_made(transport)
        return transport, protocol

    def handle_outgoing(
        self, data: bytes, addr: tuple[str, int], protocol: asyncio.DatagramProtocol
    ) -> None:
        """Record outgoing client packet and schedule simulated gateway reply."""
        self.sent_frames.append((data, addr))
        msg_type, seq, payload = unpack_frame(data)
        self.received_by_type[msg_type].append((seq, payload))

        if msg_type == MSG_PROBE_REQ and self.respond_probe:
            self._reply(protocol, pack_frame(MSG_PROBE_RESP, seq, self.mac_bytes))
        elif msg_type == MSG_HEARTBEAT_REQ:
            if self.drop_all_heartbeats:
                return
            if self.drop_heartbeats > 0:
                self.drop_heartbeats -= 1
                return
            self._reply(protocol, pack_frame(MSG_HEARTBEAT_RESP, seq, self.mac_bytes))
        elif msg_type == MSG_DEV_URL_REQ and not self.drop_url_requests:
            url_bytes = self.url_factory(seq).encode("utf-8")
            self._reply(protocol, pack_frame(MSG_DEV_URL_RESP, seq, url_bytes))
        elif msg_type == MSG_SHORT_CTRL_REQ:
            short_addr = struct.unpack_from("<H", payload, 0)[0]
            self.control_commands.append((short_addr, payload[2:]))
            if not self.drop_control:
                self._reply(protocol, pack_frame(MSG_SHORT_CTRL_RESP, seq))
        elif msg_type == MSG_STATUS_TRIGGER_REQ:
            delay_max, start_addr = struct.unpack_from(">BH", payload, 0)
            self.status_triggers.append((delay_max, start_addr, payload[3:]))
            if not self.drop_status_trigger:
                self._reply(protocol, pack_frame(MSG_STATUS_TRIGGER_RESP, seq))
        elif msg_type == MSG_DATA_REPORT_RESP:
            self.telemetry_acks.append(seq)

    def _reply(self, protocol: asyncio.DatagramProtocol, frame: bytes) -> None:
        self.loop.call_soon(protocol.datagram_received, frame, (self.ip, self.port))

    def push_telemetry(self, seq: int, chunks: list[tuple[int, bytes]]) -> None:
        """Push a Type 15 telemetry frame to active client protocols."""
        payload = b"".join(
            make_telemetry_chunk(short_addr, dev_payload)
            for short_addr, dev_payload in chunks
        )
        frame = pack_frame(MSG_DATA_REPORT_REQ, seq, payload)
        for protocol in list(self.protocols):
            protocol.datagram_received(frame, (self.ip, self.port))


def build_http_response(
    result: object, *, status: int = 200, error: Exception | None = None
) -> MagicMock:
    """Create a mock aiohttp ClientResponse for Type 6 manifest downloads."""
    mocked_response = MagicMock(spec=aiohttp.ClientResponse)
    mocked_response.status = status
    mocked_response.json = AsyncMock(return_value=result)
    mocked_response.raise_for_status.side_effect = error
    return mocked_response


def wrap_http_request(mocked_response: MagicMock) -> MagicMock:
    """Wrap a mock ClientResponse in an async context manager."""
    mocked_request = MagicMock()
    mocked_request.__aenter__.return_value = mocked_response
    return mocked_request


@pytest.fixture
def mock_gateway(hass: HomeAssistant) -> AsyncGenerator[MockUdpGateway]:
    """Patch loop.create_datagram_endpoint with an in-memory MockUdpGateway."""
    gateway = MockUdpGateway(hass.loop)
    with patch.object(
        hass.loop,
        "create_datagram_endpoint",
        side_effect=gateway.create_datagram_endpoint,
    ):
        yield gateway


@pytest.fixture
def mock_session() -> MagicMock:
    """Provide an isolated aiohttp ClientSession serving a sample manifest."""
    session = MagicMock(spec=aiohttp.ClientSession)
    manifest = encode_manifest(make_sample_devlist())
    session.get.return_value = wrap_http_request(build_http_response(manifest))
    return session


@pytest.fixture
def register_fsl(hass: HomeAssistant) -> None:
    """Register the FSL custom component and platforms with Home Assistant."""
    mock_integration(
        hass,
        MockModule(
            DOMAIN,
            async_setup=ha_fsl_zhixing.async_setup,
            async_setup_entry=ha_fsl_zhixing.async_setup_entry,
            async_unload_entry=ha_fsl_zhixing.async_unload_entry,
            async_migrate_entry=ha_fsl_zhixing.async_migrate_entry,
        ),
        built_in=False,
    )
    mock_platform(hass, "ha_fsl_zhixing.config_flow", config_flow, built_in=False)
    mock_platform(hass, "ha_fsl_zhixing.light", light, built_in=False)


@pytest.fixture
def fsl_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a v2 FSL config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=GATEWAY_MAC,
        title="FSL",
        data={
            CONF_HOST: GATEWAY_IP,
            CONF_PORT: DEFAULT_UDP_PORT,
            CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
            CONF_GATEWAY_MAC: GATEWAY_MAC,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_fsl(
    hass: HomeAssistant,
    register_fsl: None,
    mock_gateway: MockUdpGateway,
    mock_session: MagicMock,
    fsl_entry: MockConfigEntry,
) -> AsyncGenerator[MockConfigEntry]:
    """Set up the full FSL integration with mocked UDP and HTTP layers."""
    with patch("custom_components.ha_fsl_zhixing.async_get_clientsession", return_value=mock_session):
        assert await hass.config_entries.async_setup(fsl_entry.entry_id)
        await hass.async_block_till_done()
        yield fsl_entry
        await hass.config_entries.async_unload(fsl_entry.entry_id)
        await hass.async_block_till_done()
