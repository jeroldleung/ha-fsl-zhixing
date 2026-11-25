"""Async UDP transport and FASTCON BLE Gateway protocol codec."""

import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
import logging
import random
import socket
import struct

from .const import (
    DEFAULT_CLIENT_MAC,
    DEFAULT_UDP_PORT,
    DISCOVERY_BROADCAST_ADDR,
    DISCOVERY_TIMEOUT,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_MAX_MISSED,
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
    POLL_CHUNK_SIZE,
    POLL_MASK_BYTES,
    POLL_SINGLE_DELAY_MAX,
    POLL_SWEEP_DELAY_MAX,
    REQUEST_TIMEOUT,
    SEQ_DEDUP_CACHE_SIZE,
)

_LOGGER = logging.getLogger(__name__)
_HEADER_STRUCT = struct.Struct("<HH")


class FSLTransportError(Exception):
    """Base error raised for FSL UDP transport failures."""


class FSLTimeoutError(FSLTransportError):
    """Raised when the gateway does not acknowledge a request in time."""


@dataclass(frozen=True, slots=True)
class FSLDiscoveredGateway:
    """Gateway discovered via LAN UDP Type 1/Type 2 broadcast probe."""

    ip: str
    port: int
    mac: str


def parse_mac_bytes(mac: str) -> bytes:
    """Parse a 6-byte MAC address string into raw bytes."""
    cleaned = mac.replace(":", "").replace("-", "").replace(" ", "").strip()
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    raw = bytes.fromhex(cleaned)
    if len(raw) != 6:
        raise ValueError(f"Invalid MAC address: {mac}")
    return raw


def format_mac_bytes(raw: bytes) -> str:
    """Format a 6-byte MAC address as lowercase colon-separated hex."""
    if len(raw) != 6:
        raise ValueError(f"Expected 6 MAC bytes, got {len(raw)}")
    return ":".join(f"{byte:02x}" for byte in raw)


def pack_frame(msg_type: int, seq: int, payload: bytes = b"") -> bytes:
    """Encode a FASTCON UDP frame with Little-Endian header."""
    return _HEADER_STRUCT.pack(msg_type, seq) + payload


def unpack_frame(data: bytes) -> tuple[int, int, bytes]:
    """Decode a FASTCON UDP frame into (msg_type, seq, payload)."""
    if len(data) < _HEADER_STRUCT.size:
        raise ValueError(f"UDP frame shorter than 4-byte header: {len(data)} bytes")
    msg_type, seq = _HEADER_STRUCT.unpack_from(data, 0)
    return msg_type, seq, data[_HEADER_STRUCT.size :]


def parse_telemetry_chunks(payload: bytes) -> list[tuple[int, bytes]]:
    """Parse concatenated Type 15 chunks into (short_addr, device_payload) pairs."""
    chunks: list[tuple[int, bytes]] = []
    idx = 0
    while idx < len(payload):
        chunk_len = payload[idx]
        idx += 1
        if chunk_len <= 0 or idx + chunk_len > len(payload):
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Stopping Type 15 parse at offset %d: chunk_len=%d, payload=%s",
                    idx - 1,
                    chunk_len,
                    payload.hex(" "),
                )
            break
        chunk = payload[idx : idx + chunk_len]
        idx += chunk_len
        if len(chunk) >= 8:
            # 0xC0 handles <= 255; 0xC1+ stores bits 8..11 in the low nibble of Byte 0.
            short_addr_msb = (chunk[0] & 0x0F) if (chunk[0] & 0xF0) == 0xC0 else 0
            short_addr = (short_addr_msb << 8) | chunk[4]
            chunks.append((short_addr, chunk[7:]))
        elif _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Skipping short Type 15 chunk (len=%d): %s",
                len(chunk),
                chunk.hex(" "),
            )
    return chunks


def build_status_trigger_payloads(
    short_addrs: Iterable[int], *, delay_max: int | None = None
) -> list[bytes]:
    """Build Type 17 payloads chunked to at most 104 devices per 13-byte mask."""
    sorted_addrs = sorted({addr for addr in short_addrs if addr >= 0})
    if not sorted_addrs:
        return []

    effective_delay = (
        delay_max
        if delay_max is not None
        else (POLL_SINGLE_DELAY_MAX if len(sorted_addrs) == 1 else POLL_SWEEP_DELAY_MAX)
    )
    if (effective_delay + 1) & effective_delay != 0:
        raise ValueError(
            f"delay_max + 1 must be a power of 2, got delay_max={effective_delay}"
        )

    payloads: list[bytes] = []
    idx = 0
    total = len(sorted_addrs)
    while idx < total:
        start_addr = sorted_addrs[idx]
        mask = bytearray(POLL_MASK_BYTES)
        while idx < total and sorted_addrs[idx] < start_addr + POLL_CHUNK_SIZE:
            offset = sorted_addrs[idx] - start_addr
            mask[offset // 8] |= 1 << (offset % 8)
            idx += 1
        payloads.append(
            struct.pack(">BH", effective_delay, start_addr) + bytes(mask)
        )
    return payloads


class FSLUdpClient(asyncio.DatagramProtocol):
    """UDP client managing session keep-alives, requests, and telemetry ACKs."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        host: str,
        port: int,
        client_mac: str = DEFAULT_CLIENT_MAC,
        *,
        on_telemetry: Callable[[list[tuple[int, bytes]]], None] | None = None,
        on_availability_changed: Callable[[bool], None] | None = None,
    ) -> None:
        """Initialize the UDP session client."""
        self._loop = loop
        self._host = host
        self._port = port
        self._client_mac_bytes = parse_mac_bytes(client_mac)
        self._client_mac = format_mac_bytes(self._client_mac_bytes)
        self._on_telemetry = on_telemetry
        self._on_availability_changed = on_availability_changed

        self._transport: asyncio.DatagramTransport | None = None
        self._seq = random.randint(1, 0xFFF0)
        self._pending: dict[tuple[int, int], asyncio.Future[bytes]] = {}
        self._recent_telemetry_seqs: deque[int] = deque(maxlen=SEQ_DEDUP_CACHE_SIZE)
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._missed_heartbeats = 0
        self._available = True
        self._gateway_mac: str | None = None
        self._closed = False

    @property
    def available(self) -> bool:
        """Return whether the gateway heartbeat session is healthy."""
        return self._available

    @property
    def gateway_mac(self) -> str | None:
        """Return the gateway MAC discovered during handshake or heartbeat."""
        return self._gateway_mac

    @property
    def missed_heartbeats(self) -> int:
        """Return the current consecutive missed heartbeat count."""
        return self._missed_heartbeats

    def _next_seq(self) -> int:
        """Return the next non-zero 16-bit sequence number."""
        self._seq = (self._seq % 0xFFFF) + 1
        return self._seq

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the bound datagram transport."""
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming gateway frames, ACK telemetry, and resolve futures."""
        try:
            msg_type, seq, payload = unpack_frame(data)
        except ValueError as err:
            _LOGGER.debug("Ignoring malformed UDP packet from %s: %s", addr, err)
            return

        if msg_type == MSG_DATA_REPORT_REQ:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Received Type 15 telemetry from %s (seq=%d, len=%d): %s",
                    addr,
                    seq,
                    len(payload),
                    payload.hex(" "),
                )
            # Always ACK with exact seq so gateway stops retransmitting duplicates.
            self._send_raw(pack_frame(MSG_DATA_REPORT_RESP, seq), addr)
            if seq in self._recent_telemetry_seqs:
                _LOGGER.debug(
                    "Ignoring duplicate Type 15 telemetry seq=%d from %s", seq, addr
                )
                return
            self._recent_telemetry_seqs.append(seq)
            if self._on_telemetry is not None:
                chunks = parse_telemetry_chunks(payload)
                if chunks:
                    self._on_telemetry(chunks)
                elif _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "No parseable device chunks in Type 15 seq=%d payload=%s",
                        seq,
                        payload.hex(" "),
                    )
            return

        future = self._pending.pop((msg_type, seq), None)
        if future is not None and not future.done():
            future.set_result(payload)
        elif _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Received unmatched UDP frame from %s: type=0x%04x seq=%d payload=%s",
                addr,
                msg_type,
                seq,
                payload.hex(" "),
            )

    def error_received(self, exc: Exception) -> None:
        """Log socket-level datagram errors."""
        _LOGGER.debug("UDP socket error for %s:%s: %s", self._host, self._port, exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Fail any in-flight requests if the transport closes."""
        self._transport = None
        if exc is not None:
            for key, future in list(self._pending.items()):
                self._pending.pop(key, None)
                if not future.done():
                    future.set_exception(FSLTransportError(str(exc)))

    def _send_raw(
        self, frame: bytes, addr: tuple[str, int] | None = None
    ) -> None:
        """Transmit a pre-encoded UDP frame if the transport is open."""
        if self._transport is None or self._transport.is_closing():
            raise FSLTransportError("UDP transport is not connected")
        self._transport.sendto(frame, addr or (self._host, self._port))

    async def async_connect(self) -> None:
        """Open an unconnected UDP datagram socket for communicating with the gateway."""
        if self._transport is not None and not self._transport.is_closing():
            return
        self._closed = False
        try:
            await self._loop.create_datagram_endpoint(
                lambda: self,
                local_addr=("0.0.0.0", 0),
            )
        except OSError as err:
            raise FSLTransportError(
                f"Failed to open UDP endpoint to {self._host}:{self._port}: {err}"
            ) from err
        _LOGGER.debug(
            "Opened UDP socket on %s for FSL gateway %s:%s",
            self._transport.get_extra_info("sockname") if self._transport else None,
            self._host,
            self._port,
        )

    async def async_close(self) -> None:
        """Stop heartbeats, cancel pending requests, and close the transport."""
        self._closed = True
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        for key, future in list(self._pending.items()):
            self._pending.pop(key, None)
            if not future.done():
                future.cancel()

        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def start_heartbeat(self) -> None:
        """Start the 15-second keep-alive watchdog task if not already running."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = self._loop.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Send Type 3 every 15s and recover after 5 consecutive missed responses."""
        while not self._closed:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._closed:
                break
            await self.async_heartbeat_tick()

    async def async_heartbeat_tick(self) -> bool:
        """Run one keep-alive exchange and update availability watchdog state."""
        try:
            if not self._available:
                await self._async_re_register()
            await self.async_heartbeat()
        except (FSLTransportError, ValueError, OSError):
            self._missed_heartbeats += 1
            if self._available and self._missed_heartbeats >= HEARTBEAT_MAX_MISSED:
                self._available = False
                if self._on_availability_changed is not None:
                    self._on_availability_changed(False)
            return False

        was_unavailable = not self._available
        self._missed_heartbeats = 0
        self._available = True
        if was_unavailable and self._on_availability_changed is not None:
            self._on_availability_changed(True)
        return True

    async def _async_re_register(self) -> None:
        """Attempt a Type 1 probe re-registration toward the configured gateway."""
        try:
            await self.async_probe()
        except FSLTransportError:
            pass

    async def async_request(
        self,
        msg_type: int,
        expected_resp_type: int,
        payload: bytes = b"",
        *,
        timeout: float | None = None,
    ) -> bytes:
        """Send a framed request and wait for its sequence-matched response."""
        if self._transport is None or self._transport.is_closing():
            await self.async_connect()

        effective_timeout = timeout if timeout is not None else REQUEST_TIMEOUT
        seq = self._next_seq()
        key = (expected_resp_type, seq)
        future: asyncio.Future[bytes] = self._loop.create_future()
        self._pending[key] = future

        try:
            self._send_raw(pack_frame(msg_type, seq, payload))
            async with asyncio.timeout(effective_timeout):
                return await future
        except TimeoutError as err:
            raise FSLTimeoutError(
                f"Timed out waiting for response type {expected_resp_type} (seq={seq})"
            ) from err
        finally:
            self._pending.pop(key, None)

    async def async_probe(self, *, timeout: float | None = None) -> str:
        """Send a unicast Type 1 Probe Request and return the gateway MAC."""
        effective_timeout = timeout if timeout is not None else DISCOVERY_TIMEOUT
        _LOGGER.debug(
            "Sending Type 1 probe to %s:%s (client_mac=%s)",
            self._host,
            self._port,
            self._client_mac,
        )
        payload = await self.async_request(
            MSG_PROBE_REQ,
            MSG_PROBE_RESP,
            self._client_mac_bytes,
            timeout=effective_timeout,
        )
        if len(payload) != 6:
            raise FSLTransportError(
                f"Expected 6-byte gateway MAC in Type 2 response, got {len(payload)}"
            )
        mac = format_mac_bytes(payload)
        self._gateway_mac = mac
        _LOGGER.debug(
            "Received Type 2 probe response from %s:%s (gateway_mac=%s)",
            self._host,
            self._port,
            mac,
        )
        return mac

    async def async_heartbeat(self, *, timeout: float | None = None) -> str:
        """Send a Type 3 Heartbeat Request and return the gateway MAC."""
        _LOGGER.debug(
            "Sending Type 3 heartbeat to %s:%s (client_mac=%s)",
            self._host,
            self._port,
            self._client_mac,
        )
        payload = await self.async_request(
            MSG_HEARTBEAT_REQ,
            MSG_HEARTBEAT_RESP,
            self._client_mac_bytes,
            timeout=timeout,
        )
        if len(payload) != 6:
            raise FSLTransportError(
                f"Expected 6-byte gateway MAC in Type 4 response, got {len(payload)}"
            )
        mac = format_mac_bytes(payload)
        self._gateway_mac = mac
        return mac

    async def async_get_device_url(self, *, timeout: float | None = None) -> str:
        """Send Type 5 and return the single-use config JSON URL from Type 6."""
        payload = await self.async_request(
            MSG_DEV_URL_REQ, MSG_DEV_URL_RESP, timeout=timeout
        )
        url = payload.rstrip(b"\x00").decode("utf-8", errors="replace").strip()
        if not url:
            raise FSLTransportError("Gateway returned an empty Type 6 config URL")
        if not url.lower().startswith(("http://", "https://")):
            url = f"http://{url}"
        return url

    async def async_send_short_control(
        self,
        short_addr: int,
        control_payload: bytes,
        *,
        timeout: float | None = None,
    ) -> None:
        """Send a Type 9 Short Address Control Request and await Type 10 ACK."""
        payload = struct.pack("<H", short_addr) + control_payload
        await self.async_request(
            MSG_SHORT_CTRL_REQ, MSG_SHORT_CTRL_RESP, payload, timeout=timeout
        )

    async def async_trigger_status_report(
        self,
        trigger_payload: bytes,
        *,
        timeout: float | None = None,
    ) -> None:
        """Send a Type 17 Trigger Device Status Report and await Type 18 ACK."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Sending Type 17 status trigger to %s:%s: %s",
                self._host,
                self._port,
                trigger_payload.hex(" "),
            )
        resp = await self.async_request(
            MSG_STATUS_TRIGGER_REQ,
            MSG_STATUS_TRIGGER_RESP,
            trigger_payload,
            timeout=timeout,
        )
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Received Type 18 status trigger ACK from %s:%s (payload=%s)",
                self._host,
                self._port,
                resp.hex(" "),
            )


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Temporary UDP protocol for collecting Type 2 probe responses."""

    def __init__(self, target_seq: int, port: int) -> None:
        self._target_seq = target_seq
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self.gateways: dict[str, FSLDiscoveredGateway] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport
        sock = transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg_type, seq, payload = unpack_frame(data)
        except ValueError:
            return
        if msg_type != MSG_PROBE_RESP or seq != self._target_seq or len(payload) != 6:
            return
        mac = format_mac_bytes(payload)
        self.gateways[mac] = FSLDiscoveredGateway(
            ip=addr[0],
            port=addr[1] or self._port,
            mac=mac,
        )


async def async_discover_gateways(
    loop: asyncio.AbstractEventLoop,
    *,
    port: int = DEFAULT_UDP_PORT,
    client_mac: str = DEFAULT_CLIENT_MAC,
    timeout: float | None = None,
) -> list[FSLDiscoveredGateway]:
    """Broadcast a Type 1 Probe Request on the LAN and return discovered gateways."""
    effective_timeout = timeout if timeout is not None else DISCOVERY_TIMEOUT
    seq = 1
    protocol = _DiscoveryProtocol(seq, port)
    client_mac_bytes = parse_mac_bytes(client_mac)
    transport: asyncio.BaseTransport | None = None

    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )
        assert isinstance(transport, asyncio.DatagramTransport)
        transport.sendto(
            pack_frame(MSG_PROBE_REQ, seq, client_mac_bytes),
            (DISCOVERY_BROADCAST_ADDR, port),
        )
        await asyncio.sleep(effective_timeout)
    except OSError as err:
        _LOGGER.debug("LAN broadcast discovery failed: %s", err)
    finally:
        if transport is not None:
            transport.close()

    return list(protocol.gateways.values())
