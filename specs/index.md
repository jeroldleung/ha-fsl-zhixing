# FSL Integration Specifications

Modular specifications derived from [`dev_docs/prd-integrate.md`](../dev_docs/prd-integrate.md) (v1.3), separated by domain and capability.

## System & Identity

| Spec | Domain / Capability |
| :--- | :--- |
| [architecture.md](./architecture.md) | Vision, core objectives, high-level architecture, and non-functional requirements |
| [brand.md](./brand.md) | Integration identity (`FSL` / `fsl`), Device Registry attribution, and HA brand assets |
| [config-flow.md](./config-flow.md) | Setup flow, LAN gateway auto-discovery, manual configuration, and options flow |

## Protocol & Sync Capabilities

| Spec | Domain / Capability |
| :--- | :--- |
| [transport.md](./transport.md) | Local UDP transport, binary framing, 15s keep-alive watchdog, `seq` deduplication, and extended addressing |
| [manifest-sync.md](./manifest-sync.md) | Gateway manifest download (Type 5/6), Base64 decoding, room-to-Area sync, and `fsl.reload_devices` |
| [state-sync.md](./state-sync.md) | Async telemetry push (Type 15/16), staggered status polling (Type 17/18), and mesh congestion control |

## Devices & Entity Domains

| Spec | Domain / Capability |
| :--- | :--- |
| [device-catalog.md](./device-catalog.md) | 10 supported lighting types, 3 parent gateway models, shared `dev_t` handling, and out-of-scope boundaries |
| [light.md](./light.md) | `light` domain: color modes, 6-byte payload encoding, brightness/Kelvin conversions, and fade transitions |

## Reference Documents

- Original PRD: [`dev_docs/prd-integrate.md`](../dev_docs/prd-integrate.md)
- FASTCON BLE Gateway UDP Interface (v0.8): [`dev_docs/fastcon_ble_gateway_udp_open_interface.md`](../dev_docs/fastcon_ble_gateway_udp_open_interface.md)
- BroadLink Whole-House Device Profile Spec: [`dev_docs/broadlink_whole_house_device_functions_and_profile_specification.md`](../dev_docs/broadlink_whole_house_device_functions_and_profile_specification.md)
- FSL Device Type Catalog: [`dev_docs/default_dev_type.csv`](../dev_docs/default_dev_type.csv)
