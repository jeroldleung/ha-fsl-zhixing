# Architecture & Non-Functional Requirements

## Vision

`custom_components/ha_fsl_zhixing` is a local-first Home Assistant custom integration for **FSL** smart lighting (`domain: fsl`). It bridges FSL lighting fixtures through a BroadLink **FASTCON BLE Gateway** directly into Home Assistant over LAN UDP for low-latency control, real-time state updates, and automatic room-to-area sync without cloud dependency.

## Core Objectives

1. **Zero-Cloud Control:** Execute all single-light control commands locally over UDP.
2. **Automatic Topology & Area Discovery:** Fetch the gateway manifest (`devlist` and `familyInfo`) over temporary HTTP (Type 5/6) and map FSL rooms and lights to Home Assistant Areas and Devices automatically.
3. **Focused Lighting Coverage:** Support the 10 matched FSL lighting device types across 4 BroadLink `dev_t` PIDs (`W`, `CW`, `RGB`, `RGBCW`).
4. **Resilient Sessions:** Maintain reliable local UDP sessions via 15s heartbeats, sequence deduplication, and self-healing reconnection.

## High-Level Architecture

```text
+-------------------------------------------------------------------+
|                        Home Assistant Core                        |
|  +-------------+  +---------------+  +-------------------------+  |
|  | Config Flow |  | Area & Device |  |    Entity Platforms     |  |
|  |   ("FSL")   |  |   Registry    |  | - light (Primary)       |  |
|  +------+------+  +-------+-------+  +------------+------------+  |
|         |                 |                       |               |
|         v                 v                       v               |
|  +-------------------------------------------------------------+  |
|  |                 FSL DataUpdateCoordinator                   |  |
|  |  - Lighting PID / type_no / dev_version Resolver            |  |
|  |  - State Cache & Optimistic Updates                         |  |
|  |  - Rate-Limited Polling Scheduler (Type 17)                 |  |
|  |  - Async Telemetry Dispatcher (Type 15 -> Type 16 ACK)      |  |
|  +------------------------------+------------------------------+  |
|                                 |                                 |
|  +------------------------------v------------------------------+  |
|  |                UDP Transport & Session Manager              |  |
|  |  - Little-Endian Header Codec (type, seq)                   |  |
|  |  - 15s Heartbeat Loop (Type 3/4) & 5-Miss Timeout Watchdog  |  |
|  |  - Sequence Ring-Buffer Deduplicator                        |  |
|  +------------------------------+------------------------------+  |
+---------------------------------|---------------------------------+
                                  | Local LAN (UDP / HTTP GET)
                                  v
+-------------------------------------------------------------------+
|            FSL Smart Gateway (BroadLink FASTCON BLE)              |
|  - Listens on Configured UDP Port (e.g., 51000)                   |
|  - Serves Single-Use Config JSON via Ephemeral HTTP Port          |
|  - Translates UDP Frames <-> BLE Mesh Radio Broadcasts            |
+-------------------------------------------------------------------+
```

## Non-Functional Requirements

| Category | Requirement | Target |
| :--- | :--- | :--- |
| **Latency** | End-to-end local command execution (UI click -> BLE light actuation) | `< 150 ms` |
| **Reliability** | Automated heartbeat recovery without user intervention after Wi-Fi/router reboot | `100%` recovery within `90 s` |
| **Scalability** | Large lighting deployments with extended short addresses (`> 255`) | `500+` sub-devices per gateway |
| **Network Traffic** | Avoid BLE mesh radio congestion during status polling | Max `1` Type 17 broadcast every `2 s` |
| **Code Quality** | Home Assistant Integration Quality Scale compliance | Async-only I/O (`asyncio.DatagramProtocol`), full type annotations, `> 90%` test coverage |
