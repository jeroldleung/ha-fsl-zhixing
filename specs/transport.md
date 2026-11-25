# UDP Transport & Session Lifecycle

## Connection Mode (Gateway Server Mode)

- Home Assistant acts as an async UDP client (`asyncio.DatagramProtocol`) communicating with the FSL gateway's IP and UDP port (default `51000`).
- Bind an **unconnected** UDP socket (`local_addr=("0.0.0.0", 0)`) rather than a `connect()`ed (`remote_addr`) socket so asynchronous **Type 15** telemetry arriving from any gateway source port is never dropped by the OS kernel; send **Type 16** ACKs back to the incoming packet's sender `addr`.
- **LAN Discovery:** Broadcast **Type 1 (Probe Request)** to `255.255.255.255` and parse **Type 2 (Probe Response)** to auto-populate the gateway IP and MAC.
- **Session Handshake:** On startup, send a unicast **Type 1 (Probe Request)** (best-effort) followed by **Type 3 (Heartbeat Request)** on the **same persistent UDP socket** before issuing Type 5 or Type 17 commands.

## Packet Framing & Deduplication

- **Header:** Encode `type` (`uint16_t`) and `seq` (`uint16_t`) in **Little-Endian**.
- **Initial Sequence Number:** Initialize outbound `seq` randomly in `1..0xFFF0` per UDP client session so reconnects and integration reloads do not collide with gateway duplicate-`seq` filters.
- **Payload:** Encode multi-byte payload fields in **Big-Endian**, unless specified otherwise by a device profile or command type.
- **Deduplication:** Maintain a rolling ring-buffer cache of the last **128** received `seq` numbers and drop retransmitted duplicate packets.

## Keep-Alive Watchdog

- Send **Type 3 (Heartbeat Request)** every **15 seconds** containing Home Assistant's 6-byte client MAC identifier.
- Monitor **Type 4 (Heartbeat Response)**.
- After **5 consecutive missed responses (~75 s)**:
  1. Mark all FSL entities as `unavailable`.
  2. Trigger an automatic discovery / re-registration cycle.
- **Recovery target:** `100%` automatic recovery within `90 s` after a Wi-Fi or router reboot, without user intervention.

## Extended Short Addressing (`> 255` Devices)

Large deployments can exceed 255 sub-devices (`500+` per gateway). To prevent address collisions, handle short addresses consistently across message types:

| Message Type | Direction | Short Address Encoding |
| :--- | :--- | :--- |
| **Type 9** (Control) | HA -> Gateway | 2-byte **Little-Endian** |
| **Type 17** (Status Query) | HA -> Gateway | 2-byte **Big-Endian** (`MSB`, `LSB`) |
| **Type 15** (Telemetry Report) | Gateway -> HA | `0xC0` prefix for `<= 255`; `0xC1+` prefix for `> 255`: `Addr = ((Byte0 & 0x0F) << 8) | Byte4` (non-`0xC*` prefixes default high bits to `0`: `Addr = Byte4`) |
