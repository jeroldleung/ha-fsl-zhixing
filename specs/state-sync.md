# Device State Synchronization

Capability: keep Home Assistant entity states synchronized with physical BLE lights via real-time push telemetry and staggered status polling.

## Asynchronous Push Telemetry (Type 15 / Type 16)

- Continuously listen for **Type 15 (`0x000F`)** telemetry reports from the gateway on an unconnected UDP socket.
- Immediately reply with **Type 16 (`0x0010`)** mirroring the exact `seq` to the packet's sender `addr` to prevent gateway retransmission storms.
- Parse standard (`0xC0`, `<= 255`), extended (`0xC1+`, `> 255`), and non-`0xC*` (`msb = 0`) short addresses (see [transport.md](./transport.md)).

## Active Status Polling (Type 17 / Type 18)

- Execute a staggered **Type 17** status poll on startup, post-recovery, `fsl.reload_devices`, and configured polling intervals (see [config-flow.md](./config-flow.md)).
- Chunk target short addresses into blocks of up to **104 devices** per **13-byte bitmask**.
- Ensure `delay_max + 1` is strictly a **power of 2**:
  - Single-device queries: `delay_max = 0`
  - Small sweeps (`2–16` devices, round 1): `delay_max = 7` (`7 x 15 ms = 105 ms` max backoff)
  - Larger sweeps (`> 16` devices) and retry rounds: `delay_max = 31` (`31 x 15 ms = 465 ms` max backoff)
- **Two-round retry for missing devices:**
  1. Send Round 1 Type 17 chunks and wait up to **3.5 s** for Type 15 responses (exiting early once all queried short addresses report in).
  2. If any queried short addresses remain missing, send Round 2 Type 17 targeting **only the missing addresses** with `delay_max = 31` and wait up to **2.0 s**.

## Edge Case: BLE Mesh Radio Congestion

- **Risk:** Querying 200+ lights simultaneously via Type 17 can saturate the 2.4 GHz BLE mesh and cause dropped Type 15 responses.
- **Mitigation:**
  - Set `delay_max = 31` (`31 x 15 ms = 465 ms` random backoff window) on multi-device sweeps.
  - Enforce a minimum **1.5-second cooldown** between consecutive 104-device chunks.
  - Keep broadcast rate at or below **1 Type 17 broadcast every 2 seconds**.
