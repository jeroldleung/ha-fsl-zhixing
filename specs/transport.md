# UDP Transport & Session Lifecycle

## Connection Mode (Gateway Server Mode)

- Home Assistant acts as an async UDP client (`asyncio.DatagramProtocol`) connecting to the FSL gateway's IP and UDP port (default `51000`).
- **LAN Discovery:** Broadcast **Type 1 (Probe Request)** to `255.255.255.255` and parse **Type 2 (Probe Response)** to auto-populate the gateway IP and MAC.

## Packet Framing & Deduplication

- **Header:** Encode `type` (`uint16_t`) and `seq` (`uint16_t`) in **Little-Endian**.
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
| **Type 15** (Telemetry Report) | Gateway -> HA | `0xC0` prefix for `<= 255`; `0xC1+` prefix for `> 255`: `Addr = ((Byte1 & 0x0F) << 8) + Byte5` |
