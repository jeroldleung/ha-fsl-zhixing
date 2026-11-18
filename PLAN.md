# Implementation Plan: FSL Smart Lighting Integration (`custom_components/fsl`)

**Target Version:** `1.0.0` (Local-First `local_push` refactor from `0.1.0` cloud-polling prototype)  
**Domain:** `fsl` | **Display Name:** `FSL` | **Integration Type:** `hub`  
**Reference Specs:**
- [`PRD.md`](PRD.md) (v1.3)
- [`fastcon_ble_gateway_udp_open_interface.md`](docs/fastcon_ble_gateway_udp_open_interface.md) (v0.8)
- [`broadlink_whole_house_device_functions_and_profile_specification.md`](docs/broadlink_whole_house_device_functions_and_profile_specification.md)
- [`default_dev_type.csv`](docs/default_dev_type.csv)

---

## 1. Overview & Migration Goals

### 1.1 Current Baseline (`v0.1.0`)
The existing prototype in `custom_components/fsl` is a cloud-polling integration targeting `smart-api.chinafsl.com` (`iot_class: "cloud_polling"`, hardcoded `HOME_ID = 728`, 5-minute polling) with:
- Token-based cloud authentication (`auth.py`, `config_flow.py`).
- Limited device coverage: spotlight (`304`), gateway sensor (`325`), and a stubbed infrared controller (`353` in `infrared.py`).
- No local LAN discovery, no asynchronous telemetry push, and no support for tunable color/radar lighting types.

### 1.2 Target Architecture (`v1.0.0`)
Refactor `custom_components/fsl` into a **zero-cloud, local-first (`"iot_class": "local_push"`)** Home Assistant custom integration communicating over the local LAN via **UDP** (`asyncio.DatagramProtocol`) with the **FSL Smart Gateway (BroadLink FASTCON BLE Gateway)** in **Gateway Server Mode**, supplemented by immediate single-use HTTP manifest retrieval from the gateway itself.

### 1.3 Scope & Boundaries
- **In Scope:**
  - **Parent Gateways** (UDP transport bridge and `via_device` parent in HA Device Registry):
    - `325` (`GATEWAY`, `dev_t = 43500` / `ec a9`)
    - `333` (`WIRE_GATEWAY`, `dev_t = 44602` / `3a ae`)
    - `345` (`4G_WIFI_ROUTER`, `dev_t = 44862` / `3e af`)
  - **12 FSL Lighting Device Types across 7 BroadLink `dev_t` PIDs** (`default_dev_type.csv` $\cap$ BroadLink Profile Spec): `W` (`332`), `CW` (`301`–`306`, `315`), `RGB` (`352`), `RGBCW` (`331`), and Radar/Induction Lights (`338`, `347`).
  - **Radar / Induction Light Extensions** (`switch`, `number`, `sensor` platforms for `338` and `347`).
  - **Automatic Room/Area Synchronization** mapping `familyInfo.roomlist` to Home Assistant Areas.
  - **Legacy Prototype Removal:** Remove `auth.py`, cloud URLs/token renewal, and `infrared.py` (`353` is out of scope for this release).
- **Out of Scope (Deferred):**
  - Group and scene mapping/control (`grouplist` / Type 13, `scenelist` / Type 11, and temporary group Type 19); lighting groups and scenes are handled natively in Home Assistant.
  - Non-lighting categories (relay switches, composite/scene panels, curtains, thermostats/HVAC, standalone sensors, IR/virtual remotes).
  - Unmatched BroadLink light PIDs not in `default_dev_type.csv` (`43169`, `45559`, `45408`, `45161`) and CSV lighting rows without a documented BroadLink `dev_t` profile (`335`, `348`, `349`, `350`, `351`, `356`, `357`, `361`–`364`).

---

## 2. Target File & Module Architecture

```text
custom_components/fsl/
├── __init__.py          # Entry setup/unload, platform forwarding, fsl.reload_devices service
├── catalog.py           # 12 lighting & 3 gateway PID/type_no catalog, spid parser, dataclasses
├── config_flow.py       # UDP Type 1 LAN discovery, manual setup, unique_id MAC, OptionsFlow
├── const.py             # Domain, UDP ports/timers, msg types, color temp bounds
├── coordinator.py       # Session lifecycle, Type 5/6 HTTP manifest sync, Area sync, Type 15/17 routing
├── light.py             # FSLLightEntity (12 lighting types)
├── manifest.json        # domain="fsl", name="FSL", iot_class="local_push", integration_type="hub"
├── number.py            # Radar light three-stage brightness & hold-time configuration (338, 347)
├── sensor.py            # Radar light runtime (h) & energy consumption (kWh) sensors (338, 347)
├── services.yaml        # Schema definition for fsl.reload_devices
├── strings.json         # UI strings for config flow, options flow, and entity translations
├── switch.py            # Radar enable/disable switch for induction lights (338, 347)
├── transport.py         # asyncio.DatagramProtocol UDP client, codec, heartbeat, seq deduplication
├── PRD.md               # Product Requirements Document
├── PLAN.md              # Implementation plan
├── brand/               # Existing icon.png & logo.png for home-assistant/brands
├── docs/                # CSV and BroadLink protocol specs
└── translations/
    └── en.json          # Generated via python3 -m script.translations develop --integration fsl
```

### 2.1 `manifest.json`
- `"domain": "fsl"`
- `"name": "FSL"`
- `"config_flow": true`
- `"integration_type": "hub"`
- `"iot_class": "local_push"`
- `"version": "1.0.0"`
- `"requirements": []` (pure standard library `asyncio`, `struct`, `base64`, `json` + Home Assistant's `aiohttp_client`).

### 2.2 `const.py`
Define protocol, transport, and lighting constants:
- `DOMAIN = "fsl"`
- `DEFAULT_UDP_PORT = 51000`
- `DISCOVERY_BROADCAST_ADDR = "255.255.255.255"`
- `HEARTBEAT_INTERVAL = 15` (seconds)
- `HEARTBEAT_MAX_MISSED = 5` (~75s watchdog before marking entities unavailable and reconnecting)
- `SEQ_DEDUP_CACHE_SIZE = 128`
- `POLL_CHUNK_SIZE = 104` (13-byte bitmask $\times$ 8 bits)
- `POLL_SWEEP_DELAY_MAX = 31` (`delay_max + 1 = 32` is a power of 2; max backoff $31 \times 15\text{ ms} = 465\text{ ms}$)
- `POLL_SINGLE_DELAY_MAX = 0`
- `POLL_CHUNK_COOLDOWN = 1.5` (minimum seconds between consecutive 104-device `Type 17` chunks)
- `MANIFEST_FETCH_MAX_RETRIES = 3`
- Message Type IDs (`uint16` Little-Endian):
  - `MSG_PROBE_REQ = 1`, `MSG_PROBE_RESP = 2`
  - `MSG_HEARTBEAT_REQ = 3`, `MSG_HEARTBEAT_RESP = 4`
  - `MSG_DEV_URL_REQ = 5`, `MSG_DEV_URL_RESP = 6`
  - `MSG_SHORT_CTRL_REQ = 9`, `MSG_SHORT_CTRL_RESP = 10`
  - `MSG_DATA_REPORT_REQ = 15`, `MSG_DATA_REPORT_RESP = 16`
  - `MSG_STATUS_TRIGGER_REQ = 17`, `MSG_STATUS_TRIGGER_RESP = 18`
- Lighting constants:
  - `MIN_KELVIN = 2700`, `MAX_KELVIN = 6500`
  - `CONF_CLIENT_MAC = "client_mac"`, `CONF_FADE_TRANSITION = "fade_transition"`, `CONF_FILTER_IGNORED = "filter_ignored"`, `CONF_POLL_INTERVAL = "poll_interval"`

### 2.3 `catalog.py`
- **Supported Gateway & Lighting Maps:**
  - `GATEWAY_TYPE_NOS = {325: "GATEWAY", 333: "WIRE_GATEWAY", 345: "4G_WIFI_ROUTER"}` and `GATEWAY_DEV_TS = {43500, 44602, 44862}`.
  - `LIGHTING_CATALOG`: Lookup keyed by `dev_t` and/or `(type_no, dev_version)` defining `category`, `model_name`, `lighting_class` (`W`, `CW`, `RGB`, `RGBCW`, `RADAR`), `supported_color_modes`, and `is_radar_light: bool`.
- **`spid` Parser:**
  - BroadLink 16-byte `spid` hex strings (e.g., `0000000000000000000000002ba80000`) encode `dev_t` at byte indices 12–13 (`spid[24:28]`), parsed as Little-Endian `uint16` (`int.from_bytes(bytes.fromhex(spid[24:28]), "little")`).
  - Fallback resolution: if `type_no`/`dev_version` metadata is present in `devlist` (or `extendInfo`), preserve exact FSL `type_no` / `dev_version` as `DeviceInfo.model`; otherwise default cleanly from `spid` $\to$ `dev_t`.
- **Typed Dataclasses:**
  - `FSLGatewayInfo`: `mac`, `ip`, `port`, `did`, `name`, `pid`, `dev_t`, `version`.
  - `FSLLightDevice`: `did`, `sdid`, `short_addr: int`, `spid`, `dev_t: int`, `type_no: int | None`, `dev_version: str | None`, `ble_category: str`, `name: str`, `room_id: int`, `room_name: str`, `version: str`, `fw_version: int | None`, `ignore_flag: bool`, `rated_wattage: float | None`.
  - `FSLLightState`: `is_on: bool`, `brightness_ha: int | None`, `color_temp_kelvin: int | None`, `rgb_color: tuple[int, int, int] | None`.
  - `FSLRadarParams`: `radar_enabled: bool`, `high_brightness: int`, `low_brightness: int`, `nobody_keep_time: int`, `mid_brightness: int`, `mid_keep_time: int`, `runtime_seconds: int | None`, `energy_integral: int | None`, `energy_kwh: float | None`.

### 2.4 `transport.py` (UDP Transport & Session Manager)
Implements `FSLUdpClient` backed by `asyncio.DatagramProtocol`:
- **Framing Codec:**
  - Header: `struct.pack("<HH", msg_type, seq)` (`type` and `seq` in Little-Endian `uint16`).
  - `seq` counter wraps cleanly over `1..65535`.
  - Multi-byte payload fields follow Big-Endian unless explicitly Little-Endian in the device profile (e.g., `short_addr` in Type 9 is `<H`, `start_addr` in Type 17 is `>H`).
- **Deduplication:**
  - `collections.deque(maxlen=128)` paired with a membership check tracks the last 128 incoming `seq` numbers for unsolicited/telemetry packets (`Type 15`) so gateway retransmissions do not re-trigger state updates, while still answering with `Type 16` ACK mirroring the exact `seq`.
- **LAN Broadcast Discovery (`async_discover_gateways`):**
  - Opens a UDP socket with `SO_BROADCAST` enabled, sends `Type 1` (`0x0001` + `seq` + 6-byte client MAC) to `255.255.255.255:<port>`, and collects `Type 2` (`0x0002` + `seq` + 6-byte gateway MAC) unicast responses with source IP and MAC.
- **Keep-Alive Watchdog:**
  - Sends `Type 3` (`0x0003` + `seq` + 6-byte client MAC) every **15 seconds**.
  - Resets missed-heartbeat counter on every `Type 4` response.
  - If **5 consecutive heartbeats (~75s)** time out, notifies the coordinator to mark entities `unavailable` and initiates an automatic reconnect / re-registration loop.
- **Request/Response Correlation & Telemetry Callback:**
  - Pending `Future` table keyed by `(expected_resp_type, seq)` for `Type 5/6`, `Type 9/10`, `Type 17/18`.
  - Incoming `Type 15` (`0x000F`) packets immediately transmit `Type 16` (`0x0010` + mirrored `seq` LE) before dispatching the telemetry payload to the coordinator.

### 2.5 `coordinator.py` (`FSLDataUpdateCoordinator`)
- **Session & Manifest Synchronization (`Type 5` $\to$ `Type 6`):**
  - Sends `Type 5` (`0x0005` + `seq`), awaits `Type 6` ASCII/UTF-8 URL.
  - Immediately executes an HTTP `GET` via `async_get_clientsession(hass)` (single-use URL).
  - On HTTP failure (timeout, `403`, `404`, or invalid JSON), automatically re-requests a fresh `Type 5` with an incremented `seq` up to **3 retries**.
  - Parses `data[0].dataList` and Base64-decodes `devlist` and `familyInfo`.
- **Topology & Home Assistant Area Sync:**
  - Iterates `familyInfo["roomlist"]` and ensures each room (excluding or handling `roomId = 0` `"Whole House"` cleanly) exists via `area_registry.async_get_or_create(room_name)`.
  - Registers the parent Gateway device (`manufacturer="FSL"`, `identifiers={(DOMAIN, gateway_mac)}`, `connections={(dr.CONNECTION_NETWORK_MAC, gateway_mac)}`) and links all lighting devices via `via_device=(DOMAIN, gateway_mac)` with `suggested_area` set to the device's `roomName`.
- **Telemetry Parsing (`Type 15`):**
  - Splits concatenated 22-byte (`0x16`) report chunks inside a `Type 15` frame.
  - Parses short addresses:
    - Byte 0 == `0xC0`: $\text{short\_addr} = \text{Byte}_4$ ($\le 255$).
    - Byte 0 > `0xC0` (e.g., `0xC1+`): $\text{short\_addr} = ((\text{Byte}_0 \ \& \ 0\text{x0F}) \ll 8) + \text{Byte}_4$ ($> 255$).
  - Dispatches standard 15-byte lighting state payloads (`Bytes 7..21` of the 22-byte chunk) vs. three-stage radar reports (`00 E0` descriptor + `91 00 00 00 00 00` header) vs. radar runtime/energy telemetry (`FW <= 78` and `FW >= 79`) to entity state caches and notifies listeners.
- **Rate-Limited Status Polling (`Type 17` / `Type 18`):**
  - Collects active lighting `short_addr` values, sorts them, and builds 13-byte (104-bit) bitmask chunks starting from each chunk's base `start_addr` (`>H`).
  - Transmits `Type 17` with `delay_max = 31` for sweeps (`0` for single-device queries) and enforces a minimum `1.5s` cooldown (`max` 1 broadcast per `2s` target window) between consecutive chunks to prevent BLE mesh congestion.
  - Schedules initial startup sweep and configurable periodic sweeps (from Options Flow; default disabled or conservative interval to rely on `local_push` without flooding BLE).
- **Optimistic State & Command Dispatch:**
  - `async_control_short_addr(short_addr, payload)` (`Type 9`, `<H` short address + payload).
  - `async_query_radar_params(short_addr)` (`Type 9` with `91 00 00 00 00 00`).

### 2.6 `config_flow.py` & `strings.json`
- **Discovery & User Flow (`VERSION = 2`, migration from `VERSION = 1`):**
  - `async_step_user`: Runs a short LAN `Type 1` broadcast discovery (e.g., 2–3s timeout). If gateways are found, presents a selector (`<IP> (<MAC>)` plus `"Enter manually"`); if none are found, goes directly to `async_step_manual`.
  - `async_step_manual`: Prompts for `host` (Gateway IP), `port` (default `51000`), and optional `client_mac` (6-byte hex string, auto-generated locally if omitted, e.g., deterministic/random LAA MAC).
  - Validates connectivity by sending `Type 3` heartbeat + `Type 5`/`Type 6` manifest fetch, extracts Gateway MAC, sets `unique_id = dr.format_mac(gateway_mac)`, calls `_abort_if_unique_id_configured(updates=...)`, and creates entry titled `"FSL"` (or `"FSL (<IP>)"` / `"FSL"` per HA guidelines — avoid custom user-typed entry name prompts).
  - **Config Entry Migration (`async_migrate_entry`):** Cleanly handles v1 cloud entries by prompting/marking for reconfiguration or migrating schema cleanly without crashing HA startup.
- **Options Flow (`FSLOptionsFlow`):**
  - `fade_transition` (bool, default `True` for FW $\ge 58$ lights).
  - `filter_ignored` (bool, default `True` to skip entries with `ignoreflag: true`).
  - `poll_interval` (int seconds, e.g., `0` to disable periodic sweep or `>= 30` seconds; used strictly for optional `Type 17` BLE state resync in Options Flow per PRD §4.1).

---

## 3. Device Catalog & Protocol Mapping Specification

### 3.1 Supported Gateway Types (Transport & `via_device` Parent)

| `type_no` | CSV Category | English Name | `dev_t` | PID (Hex, LE) | HA Role |
| :---: | :--- | :--- | :---: | :---: | :--- |
| `325` | `GATEWAY` | gateway | `43500` | `ec a9` | Hub Device (`via_device` parent) |
| `333` | `WIRE_GATEWAY` | wire_gateway | `44602` | `3a ae` | Hub Device (`via_device` parent) |
| `345` | `4G_WIFI_ROUTER` | 4gWifiRouter | `44862` | `3e af` | Hub Device (`via_device` parent) |

### 3.2 Supported Lighting Device Catalog (12 Types Across 7 PIDs)

| `type_no` | CSV Category | Chinese Name | English Name | `dev_t` | PID (Hex, LE) | `dev_version` | Lighting Class | HA `ColorMode` |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| `332` | `KW_WHITE_LIGHT` | 白灯 | kw_white_light | `43049` | `29 a8` | — | White (`W`) | `ColorMode.BRIGHTNESS` |
| `301` | `MAIN_LIGHT` | 主灯 | main light | `43051` | `2b a8` | `1` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `302` | `CEILING_LIGHT` | 吸顶灯 | ceiling light | `43051` | `2b a8` | `2` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `303` | `LIGHT_BELT` | 灯带 | light belt | `43051` | `2b a8` | `3` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `304` | `DOWN_LIGHT` | 筒射灯 | down light | `43051` | `2b a8` | `4` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `305` | `MAGNET_DOWN_LIGHT` | 磁吸泛光灯 | magnet down light | `43051` | `2b a8` | `5` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `306` | `MAGNET_DOWN_LIGHT_NO_FLOODLIGHT` | 磁吸灯（除泛光） | magnet down light no floodlight | `43051` | `2b a8` | `6` | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `315` | `FAN_LIGHT` | 风扇灯 | fanLight | `43051` | `2b a8` | — | Tunable White (`CW`) | `ColorMode.COLOR_TEMP` |
| `352` | `UNIVERSAL_COLOR_LIGHT` | 通用彩灯 | UniversalColorLight | `43168` | `a0 a8` | — | Color (`RGB`) | `ColorMode.RGB` |
| `331` | `KRGBCW_LIGHT` | 可调亮度和色温的彩灯 | krgbcw light | `43050` | `2a a8` | — | Color + CCT (`RGBCW`) | `ColorMode.RGB` + `ColorMode.COLOR_TEMP` (or `ColorMode.RGBWW`) |
| `338` | `LIGHT_INDUCTION` | 微波灯管 | lightInduction | `44876`, `44956` | `4c af`, `9c af` | — | Radar / Induction | `ColorMode.BRIGHTNESS` (or `COLOR_TEMP` if CW channels reported) |
| `347` | `HANGING_WIRE_LAMP_PANEL` | 吊线灯盘 | HangingWireLampPanel | `45160` | `68 b0` | — | Radar / Induction | `ColorMode.BRIGHTNESS` (or `COLOR_TEMP` if CW channels reported) |

> **Note on `331` (`KRGBCW_LIGHT`):** Home Assistant separates mutually exclusive color modes (`ColorMode.RGB` and `ColorMode.COLOR_TEMP`) or combines them in `ColorMode.RGBWW`. Using `{ColorMode.RGB, ColorMode.COLOR_TEMP}` aligns cleanly with BroadLink's 6-byte `[Bri/Power, B, R, G, W, C]` payload (zeroing `W, C` when in RGB mode, and zeroing `B, R, G` when in CCT mode) and provides native HA UI color/temperature tabs; `RGBWW` can also be supported if 5-channel simultaneous control is desired, with clear decoding from telemetry.

### 3.3 Lighting Control & Telemetry Codec Rules
1. **Standard 6-Byte Control Payload (`[Byte 0..5]`):**
   - `Byte 0`: Bit 7 = Power (`1` = On, `0` = Off), Bits 0–6 = Brightness ($0 - 127$).
   - `Byte 1`: Blue (`0 - 255`), `Byte 2`: Red (`0 - 255`), `Byte 3`: Green (`0 - 255`), `Byte 4`: Warm White `W` (`0 - 255`), `Byte 5`: Cool White `C` (`0 - 255`).
2. **Power Off Quirk:**
   - When turning off **without** transition prefix, transmit **single byte `b"\x00"`** (never `00 00 00 00 00 00`).
3. **Power On (Restore):**
   - When turning on with no brightness/color/temp arguments, transmit **single byte `b"\x80"`**.
4. **Brightness Conversion ($0 - 255 \leftrightarrow 0 - 127$):**
   - Encode: `bri_bl = max(1, (bri_ha * 127) // 255)` $\to$ `Byte 0 = 0x80 | bri_bl`.
   - Decode: `bri_ha = min(255, round((byte0 & 0x7F) * 255 / 127))`.
5. **Color Temperature Conversion ($2700\text{ K} - 6500\text{ K}$):**
   - Encode: clamp `kelvin` to `[2700, 6500]`; `C = ((kelvin - 2700) * 255) // (6500 - 2700)`, `W = 255 - C`.
   - Decode: when `W + C > 0`, `kelvin = 2700 + round((C / (W + C)) * (6500 - 2700))`.
6. **Fade Transitions (Firmware $\ge 58$):**
   - When `ATTR_TRANSITION` is provided (or Options Flow fade preference is enabled) on FW $\ge 58$ lights, prepend `b"\x80"` (fade enabled) or `b"\x00"` (instant) before the lighting payload (`[prefix, Bri/Power, B, R, G, W, C]`).
7. **Extended Short Addressing ($> 255$):**
   - **Type 9 (Control):** 2-byte Little-Endian (`struct.pack("<H", short_addr)`).
   - **Type 17 (Status Poll):** 2-byte Big-Endian start address (`struct.pack(">H", start_addr)`).
   - **Type 15 (Telemetry Report):** Parse `addr_mode = chunk[0]`:
     - `0xC0`: `short_addr = chunk[4]`.
     - `> 0xC0` (e.g., `0xC1+`): `short_addr = ((chunk[0] & 0x0F) << 8) + chunk[4]`.

### 3.4 Radar / Induction Light Extensions (`338`, `347`)
Attached to the same HA Device (`identifiers={(DOMAIN, sdid)}`) as the primary `light` entity:
- **Three-Stage Query & Report:**
  - Query payload via `Type 9`: `b"\x91\x00\x00\x00\x00\x00"`.
  - Detect report in `Type 15` chunk when bytes `[5:7] == b"\x00\xe0"` and `[7:13] == b"\x91\x00\x00\x00\x00\x00"`:
    - `Byte 0`: `radar_enable` (`0` / `1`) $\to$ `switch` entity.
    - `Byte 1`: `high_brightness` ($0 - 100\%$) $\to$ `number` entity.
    - `Byte 2`: `low_brightness` ($0 - 100\%$) $\to$ `number` entity.
    - `Bytes 3–4` (LE `uint16`): `nobody_keep_time` ($\text{s}$) $\to$ `number` entity.
    - `Byte 5`: `mid_brightness` ($0 - 100\%$, `0` = disabled) $\to$ `number` entity.
    - `Bytes 6–7` (LE `uint16`): `mid_keep_time` ($\text{s}$) $\to$ `number` entity.
- **Telemetry & Energy Reporting (`sensor` platform):**
  - `FW <= 78` (15-byte payload): `Byte 0` Bri/Power, `Bytes 1–3` + `Byte 14` Trigger Count, `Bytes 4–5` W/C, `Bytes 6–9` LE Energy Integral, `Bytes 10–13` LE Operating Runtime ($\text{s}$).
  - `FW >= 79` (15-byte payload): `Byte 0` Bri/Power, `Byte 1` + `Bytes 10–14` MAC, `Bytes 2–5` LE Operating Runtime ($\text{s}$), `Bytes 6–9` LE Energy Integral.
  - Sensors exposed:
    - Operating Runtime (`SensorDeviceClass.DURATION`, unit `h`, `state_class=TOTAL_INCREASING`).
    - Energy Consumption (`SensorDeviceClass.ENERGY`, unit `kWh`, `state_class=TOTAL_INCREASING`, derived from $\frac{\text{Integral} \times 8}{\text{Runtime} \times 127} \times \text{RatedWattage} \times \frac{\text{Runtime}}{3600}$ when rated wattage is known/configured, plus diagnostic/power attributes as applicable).

---

## 4. Phased Implementation Roadmap

### Phase 1: Core UDP Transport, Framing & Discovery Engine
- **Deliverables:** `const.py`, `transport.py`.
- **Key Tasks:**
  1. Implement Little-Endian packet header packing/unpacking (`<HH`) and `uint16` `seq` sequence tracker.
  2. Implement `FSLUdpClient(asyncio.DatagramProtocol)` with pending-future correlation and automatic `Type 16` ACK mirroring `seq` on every `Type 15` packet.
  3. Implement 128-entry `seq` ring-buffer deduplication for incoming packets.
  4. Implement `Type 1` LAN broadcast probe and `Type 2` response collector.
  5. Implement 15-second `Type 3`/`Type 4` heartbeat loop and 5-miss (~75s) watchdog callback.
- **Exit Criteria:** Unit tests validate packet framing, seq wrap-around, deduplication of 128+ packets, Type 1/2 discovery, Type 3/4 timeout watchdog, and Type 15 $\to$ Type 16 instant ACK.

### Phase 2: Manifest Parser, Device Catalog, Coordinator & Onboarding
- **Deliverables:** `catalog.py`, `coordinator.py`, `config_flow.py`, `manifest.json`, `strings.json`, `translations/en.json`.
- **Key Tasks:**
  1. Build the 12-light / 3-gateway catalog and `spid[24:28]` LE `dev_t` extractor.
  2. Implement `Type 5` $\to$ `Type 6` single-use HTTP GET manifest fetcher with up to 3 automatic retries on HTTP expiration/failure.
  3. Decode Base64 `devlist` and `familyInfo`; filter non-lighting devices and optionally `ignoreflag: true` devices.
  4. Map `familyInfo.roomlist` to HA Areas and wire `DeviceInfo` with `manufacturer="FSL"`, `via_device` to the parent gateway, `model` preserving `type_no`/`dev_version`, and `suggested_area`.
  5. Implement rate-limited `Type 17` 104-device bitmask chunking (`delay_max = 31`, `1.5s` cooldown) and `Type 15` multi-chunk (`0x16`) + extended address (`0xC1+`) parser.
  6. Replace cloud `config_flow.py` with UDP discovery + manual IP/port/MAC entry, Gateway MAC `unique_id`, v1 $\to$ v2 entry migration, and Options Flow.
- **Exit Criteria:** Config flow discovers simulated gateways, persists MAC `unique_id`, downloads and parses Base64 manifests, creates HA Areas, and updates coordinator state on `Type 15` push and `Type 17` sweep.

### Phase 3: Primary Lighting Platform (`light.py`)
- **Deliverables:** `light.py`.
- **Key Tasks:**
  1. Implement `FSLLightEntity` supporting all 12 FSL lighting `type_no` values and their exact `ColorMode` (`BRIGHTNESS`, `COLOR_TEMP`, `RGB`, `{RGB, COLOR_TEMP}`).
  2. Implement exact brightness (`1..127`), CCT (`2700K..6500K`, `C + W = 255`), RGB, single-byte `0x00` turn-off, `0x80` restore turn-on, and FW $\ge 58$ fade transition (`0x80`/`0x00` prefix) codecs.
  3. Support extended short addresses ($> 255$) in both control (`Type 9` LE) and telemetry (`Type 15` `0xC1+`).
- **Exit Criteria:** All 12 lighting classes pass command encoding, state decoding, optimistic update, availability watchdog, and extended address tests.

### Phase 4: Radar Light Extensions & Services
- **Deliverables:** `switch.py`, `number.py`, `sensor.py`, `services.yaml`, `__init__.py`.
- **Key Tasks:**
  1. Implement Radar Light (`338`, `347`) three-stage parameter query (`91 00 00 00 00 00`), `switch` (radar enable), `number` (high/mid/low brightness `%`, unoccupied hold time `s`, mid hold time `s`), and `sensor` (operating runtime `h` and energy consumption `kWh` for FW $\le 78$ and $\ge 79$).
  2. Implement `fsl.reload_devices` service in `__init__.py` & `services.yaml` to trigger an on-demand `Type 5`/`Type 6` manifest refresh and entity/area reconciliation.
- **Exit Criteria:** Radar entities parse `00 E0` and telemetry frames and write back updated 8-byte parameter frames; reload service refreshes devices cleanly.

### Phase 5: Legacy Cleanup, Test Suite Overhaul & Quality Verification
- **Deliverables:** Updated `config/tests/fsl/*`, cleaned component files, generated `translations/en.json`.
- **Key Tasks:**
  1. Remove legacy `auth.py` and `infrared.py` and their stale cloud tests (`test_auth.py`, `test_infrared.py`), plus clean up obsolete entity registry migration code in `__init__.py` (or handle legacy entity cleanup gracefully).
  2. Build comprehensive local mock UDP gateway test suite in `config/tests/fsl/` targeting $> 90\%$ coverage.
  3. Regenerate `translations/en.json` via `python3 -m script.translations develop --integration fsl`.
  4. Run full `pytest` and `uv run prek run --all-files` to verify typing, linting, formatting, and HA Quality Scale compliance.

---

## 5. Testing & Verification Strategy

### 5.1 Planned Test Suite (`config/tests/fsl/`)
All tests will use an in-memory/loopback **Mock UDP Gateway** simulating `Type 1`–`Type 18` frames and an isolated `aiohttp` response for `Type 6` HTTP manifest fetches—zero network/cloud access:
- `conftest.py`: Mock UDP gateway simulator fixture, sample Base64-encoded family manifests (`devlist` covering all 12 lighting types + 3 gateway types + ignored/out-of-scope devices + short addresses `<= 255` and `> 255`, and `familyInfo`).
- `test_transport.py`: Framing byte order, `seq` rollover, 128-entry deduplication ring buffer, `Type 15` $\to$ `Type 16` ACK mirroring, 15s heartbeat loop, and 5-miss watchdog reconnect.
- `test_config_flow.py`: Auto-discovery via `Type 1`/`Type 2`, manual entry fallback, MAC `unique_id` deduplication, IP update on rediscovery, error handling (`cannot_connect`, invalid response), and Options Flow.
- `test_coordinator.py`: `Type 5`/`Type 6` single-use URL retry (up to 3x), Base64 decoding, `spid` $\to$ `dev_t` lookup, HA Area creation, `Type 17` 104-device mask chunking + `1.5s` cooldown + `delay_max = 31`, `fsl.reload_devices` service, and availability transitions.
- `test_light.py`: All 12 lighting device types, brightness `1..127` scaling, CCT `2700K..6500K` (`C + W = 255`), RGB color encoding, single-byte `0x00` off rule, `0x80` restore on, FW $\ge 58$ fade transitions, and extended short addresses (`0xC1+`).
- `test_radar_light.py`: `338`/`347` `91 00 00 00 00 00` parameter query, `00 E0` parsing, `switch` & `number` writes, and `FW <= 78` / `FW >= 79` runtime & energy `sensor` calculations.

### 5.2 Verification Commands
- **Run FSL tests:**
  ```bash
  PYTHONPATH=config:. uv run --no-sync pytest -p tests.conftest config/tests/fsl --cov=custom_components.fsl --cov-report=term-missing
  ```
- **Regenerate translations (after any `strings.json` edit):**
  ```bash
  python3 -m script.translations develop --integration fsl
  ```
- **Lint & format check:**
  ```bash
  uv run prek run --all-files
  ```

---

## 6. Key Edge Cases & Mitigations Checklist

| Edge Case | Mitigation |
| :--- | :--- |
| **Single-use `Type 6` URL expiration** | Trigger HTTP `GET` immediately upon `Type 6`; retry `Type 5` with incremented `seq` (max 3 retries) on timeout/4xx/5xx. |
| **BLE mesh congestion during startup poll** | Chunk `Type 17` into max 104-device masks, set `delay_max = 31` ($465\text{ ms}$ backoff), and enforce $\ge 1.5\text{ s}$ cooldown between chunks. |
| **Extended short addresses ($> 255$)** | Parse `0xC1+` prefix upper 4 bits in `Type 15`; send `<H` in `Type 9` and `>H` in `Type 17`. |
| **Light Off single-byte quirk** | Always send `b"\x00"` (1 byte) when turning off without transition prefix, never 6 zero bytes. |
| **Shared `dev_t = 43051` across 7 light types** | Map all 7 (`301`–`306`, `315`) to `ColorMode.COLOR_TEMP` while preserving `type_no`/`dev_version` in `DeviceInfo.model`, falling back to `spid` when absent. |
| **Gateway session timeout (~75s)** | Send `Type 3` every 15s; on 5 missed `Type 4` responses, mark entities `unavailable` and restart discovery/re-registration. |
