# Product Requirements Document (PRD): FSL Smart Lighting Integration for Home Assistant

**Document Version:** 1.3  
**Brand / Integration Name:** FSL (`custom_components/fsl`)  
**Target Platform:** Home Assistant (Core / HACS Custom Integration)  
**Underlying Hardware & Protocols:** BroadLink Hardware Architecture, FASTCON BLE Gateway UDP Open Interface (v0.8) & Whole-House Device Profile Specification  
**Current Version Scope:** Standard lighting subset of `docs/default_dev_type.csv` $\cap$ `docs/broadlink_whole_house_device_functions_and_profile_specification.md` (**10 FSL lighting device types** across **4 BroadLink `dev_t` PIDs**)

---

## 1. Executive Summary

### 1.1 Product Vision
Refactor `custom_components/fsl` from its legacy cloud-polling prototype (`smart-api.chinafsl.com`) into a local-first Home Assistant custom integration branded under **FSL** (domain: `fsl`, display name: **FSL**). The current version focuses strictly on **FSL smart lighting**—bridging FSL lighting fixtures through the FASTCON BLE Gateway directly into Home Assistant over the local area network (LAN) via UDP for low-latency control, real-time asynchronous state updates, and automatic room/area synchronization without cloud dependency.

### 1.2 Brand & Component Identity
* **Integration Display Name:** `FSL`
* **Component Domain (`manifest.json`):** `fsl` (`custom_components/fsl`, `"iot_class": "local_push"`)
* **Device Registry Attribution:** Register the parent FSL Gateway and each lighting sub-device in the Home Assistant Device Registry with `manufacturer="FSL"`, preserving `type_no`, `dev_t`, and `dev_version` metadata and linking lights via `via_device` to the parent FSL Gateway.
* **HA Brands Repository:** Include brand assets (`icon.png`, `logo.png`) structured for `home-assistant/brands` under `custom_integrations/fsl`.

### 1.3 Core Objectives
1. **Zero-Cloud Lighting Control:** Execute all single-light control commands locally over UDP.
2. **Automatic Topology & Area Discovery:** Retrieve the home manifest (`devlist` and `familyInfo`) via the gateway's temporary HTTP URL (Type 5/6) and map FSL rooms and lights to Home Assistant Areas and Devices automatically.
3. **Focused Lighting Coverage:** Strictly support the **10 FSL lighting device types** from `docs/default_dev_type.csv` whose `dev_t` exists in `docs/broadlink_whole_house_device_functions_and_profile_specification.md` (`W`, `CW`, `RGB`, and `RGBCW` lights).
4. **Resilient Session Management:** Maintain reliable local UDP communication through 15-second heartbeat keep-alives, sequence deduplication, and self-healing reconnection logic.

---

## 2. System Architecture & Communication Engine

### 2.1 High-Level Architecture

```
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

### 2.2 Transport & Session Lifecycle Requirements
* **Connection Mode (Gateway Server Mode):** Home Assistant acts as a UDP client connecting to the FSL gateway's IP and UDP port (default `51000`). Supports LAN broadcast discovery via **Type 1 (Probe Request)** to `255.255.255.255` and parsing **Type 2 (Probe Response)** to auto-populate IP and Gateway MAC.
* **Keep-Alive Watchdog:**
  * Transmit **Type 3 (Heartbeat Request)** every **15 seconds** containing HA's 6-byte client MAC identifier.
  * Monitor **Type 4 (Heartbeat Response)**. If **5 consecutive responses (~75s)** are missed, mark FSL entities as `unavailable` and trigger an automatic discovery/re-registration cycle.
* **Packet Framing & Deduplication:**
  * Encode `type` (`uint16_t`) and `seq` (`uint16_t`) in **Little-Endian**; encode multi-byte payload fields in **Big-Endian** unless specified otherwise by device profiles.
  * Maintain a rolling cache of the last 128 received `seq` numbers to drop retransmitted duplicate packets.
* **Metadata Synchronization (Type 5 $\to$ Type 6):**
  * Upon connection establishment (and via `fsl.reload_devices`), send **Type 5** to obtain the single-use HTTP URL from **Type 6**.
  * Immediately download the JSON manifest, Base64-decode `devlist` and `familyInfo`, and map `roomlist` entries to Home Assistant Areas.

### 2.3 State Synchronization Strategy
* **Asynchronous Push (Type 15 / Type 16):**
  * Continuously listen for **Type 15 (`0x000F`)** telemetry reports.
  * Immediately reply with **Type 16 (`0x0010`)** mirroring the exact `seq` to prevent gateway retransmission storms.
  * Parse both standard short addresses $\le 255$ (`0xC0` prefix) and extended short addresses $> 255$ (`0xC1+` prefix, where $\text{Addr} = ((\text{Byte}_1 \ \& \ 0\text{x0F}) \ll 8) + \text{Byte}_5$).
* **Active Status Polling (Type 17 / Type 18):**
  * Execute a staggered **Type 17** poll on HA startup and configurable intervals so lights synchronize their initial state.
  * Chunk queries into blocks of up to 104 devices per 13-byte bitmask, ensuring $(\text{delay\_max} + 1)$ is strictly a power of 2 (e.g., `delay_max = 15` or `31` for sweeps, `0` for single-device queries).

---

## 3. Target Lighting Device Catalog & Scope Boundaries

### 3.1 Filtered FSL Lighting Catalog (`default_dev_type.csv` $\cap$ BroadLink Profile Specification)
The current version integrates **10 FSL lighting device types** spanning **4 BroadLink `dev_t` PIDs**:

| `type_no` | Category (`CSV`) | Chinese Name | English Name | Matched `dev_t` | PID (Hex, LE) | `dev_version` | Lighting Class |
| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| `332` | `KW_WHITE_LIGHT` | 白灯 | kw_white_light | `43049` | `29 a8` | — | White (`W`) |
| `301` | `MAIN_LIGHT` | 主灯 | main light | `43051` | `2b a8` | `1` | Tunable White (`CW`) |
| `302` | `CEILING_LIGHT` | 吸顶灯 | ceiling light | `43051` | `2b a8` | `2` | Tunable White (`CW`) |
| `303` | `LIGHT_BELT` | 灯带 | light belt | `43051` | `2b a8` | `3` | Tunable White (`CW`) |
| `304` | `DOWN_LIGHT` | 筒射灯 | down light | `43051` | `2b a8` | `4` | Tunable White (`CW`) |
| `305` | `MAGNET_DOWN_LIGHT` | 磁吸泛光灯 | magnet down light | `43051` | `2b a8` | `5` | Tunable White (`CW`) |
| `306` | `MAGNET_DOWN_LIGHT_NO_FLOODLIGHT` | 磁吸灯（除泛光） | magnet down light no floodlight | `43051` | `2b a8` | `6` | Tunable White (`CW`) |
| `315` | `FAN_LIGHT` | 风扇灯 | fanLight | `43051` | `2b a8` | — | Tunable White (`CW`) |
| `352` | `UNIVERSAL_COLOR_LIGHT` | 通用彩灯 | UniversalColorLight | `43168` | `a0 a8` | — | Color (`RGB`) |
| `331` | `KRGBCW_LIGHT` | 可调亮度和色温的彩灯 | krgbcw light | `43050` | `2a a8` | — | Color + CCT (`RGBCW`) |

> **Gateway Transport Role:** The FASTCON BLE Gateway (`325` `GATEWAY` / `43500`, `333` `WIRE_GATEWAY` / `44602`, `345` `4G_WIFI_ROUTER` / `44862`) acts solely as the local UDP bridge and parent device (`via_device`) in the Device Registry.

### 3.2 Out of Scope for the Current Version
* **Radar / Induction Lights:** Microwave induction lights (`338` `LIGHT_INDUCTION` / `44876`, `44956`) and hanging wire lamp panels (`347` `HANGING_WIRE_LAMP_PANEL` / `45160`) are deferred from this release.
* **Group & Scene Mapping / Control:** Lighting group mapping and control (`grouplist` / Type 13) and scene mapping and control (`scenelist` / Type 11) are excluded; grouping and scenes are managed natively within Home Assistant.
* **Non-Lighting Device Categories:** Relay switches, composite panels, scene panels, curtains, thermostats/HVAC, standalone sensors, and virtual remotes are deferred from this release.
* **Unmatched / Unverified Lights:**
  * BroadLink spec light PIDs without a matching `dev_t` in `default_dev_type.csv`: `43169` (`a1 a8` RGBW), `45559` (`f7 b1`), `45408` (`60 b1`), `45161` (`69 b0`).
  * `default_dev_type.csv` lighting rows without a documented BroadLink `dev_t` profile: `335` (`44841`), `348` (`44838`), `349` (`45509`), `350` (`45510`), `351` (`45648`), `356` (`45712`), `357` (`45789`), `361` (`46017`), `362` (`99997`), `363` (`400`), `364` (`46133`).

---

## 4. Feature Specifications & Entity Mappings

### 4.1 User Onboarding & Configuration Flow (`custom_components/fsl/config_flow.py`)
* **Integration Branding:** Appears in Home Assistant's *Add Integration* menu as **FSL** (`domain: "fsl"`).
* **Auto-Discovery:** Broadcast Type 1 probe packets during setup to list discovered FSL gateways on the subnet by MAC and IP.
* **Manual Entry:** Allow manual input of Gateway IP, UDP Port (default `51000`), and a custom 6-byte Client MAC identifier (auto-generated if omitted).
* **Options Flow:** Allow users to configure polling intervals, enable/disable transition fading (for FW $\ge 58$ lights), and filter ignored devices (`ignoreflag: true`).

### 4.2 Lighting Platform Specification (`light` platform)
Supports all **10 matched lighting device types** via the standard 6-byte lighting payload (`[Bri/Power, B, R, G, W, C]`):
* **Color Mode Assignment (via `dev_t` / `spid` and `blecatetory`):**
  * `43049` (`29 a8`, `332` `KW_WHITE_LIGHT`) $\to$ `ColorMode.BRIGHTNESS`
  * `43051` (`2b a8`, `301`–`306`, `315` `FAN_LIGHT`) $\to$ `ColorMode.COLOR_TEMP`
  * `43168` (`a0 a8`, `352` `UNIVERSAL_COLOR_LIGHT`) $\to$ `ColorMode.RGB`
  * `43050` (`2a a8`, `331` `KRGBCW_LIGHT`) $\to$ `ColorMode.RGBWW` (or `ColorMode.HS` + `ColorMode.COLOR_TEMP` mapped onto the 6-byte `Bri/B/R/G/W/C` frame)
* **Value Conversions:**
  * **Off Command:** Transmit single byte `0x00` (never 6 zero bytes).
  * **On (Restore):** Transmit `0x80`.
  * **Brightness:** Convert HA brightness ($0 - 255$) to protocol brightness ($0 - 127$):
    $$\text{Bri}_{\text{BL}} = \max\left(1, \left\lfloor \frac{\text{Bri}_{\text{HA}}}{255} \times 127 \right\rfloor\right)$$
  * **Color Temperature:** Map HA Kelvin ($2700\text{ K} - 6500\text{ K}$) to Warm ($W$) and Cool ($C$) channels where $C + W = 255$:
    $$C = \left\lfloor \frac{T_{\text{Kelvin}} - 2700}{6500 - 2700} \times 255 \right\rfloor, \quad W = 255 - C$$
* **Fade Transitions (Firmware $\ge 58$):** Prepend `0x80` (fade enabled) or `0x00` (instant) when `transition` is supplied on `light.turn_on` / `light.turn_off`.

---

## 5. Non-Functional Requirements

| Category | Requirement | Target Metric |
| :--- | :--- | :--- |
| **Latency** | End-to-end local command execution (HA UI click $\to$ BLE light actuation) | $< 150\text{ ms}$ |
| **Reliability** | Automated heartbeat recovery without user intervention after Wi-Fi/Router reboot | $100\%$ recovery within $90\text{ s}$ |
| **Scalability** | Support large lighting deployments with extended short addresses ($> 255$) | Up to $500+$ sub-devices per gateway |
| **Network Traffic** | Avoid BLE mesh radio congestion during status polling | Max 1 Type 17 broadcast every $2\text{ s}$ |
| **Code Quality** | Compliance with Home Assistant Integration Quality Scale | Async-only I/O (`asyncio.DatagramProtocol`), full type annotations, $> 90\%$ test coverage |

---

## 6. Edge Cases & Risk Mitigation

1. **Single-Use Config URL Expiration (Type 6):**
   * *Risk:* The HTTP URL returned by Type 6 becomes invalid immediately after one HTTP GET request or after a short timeout.
   * *Mitigation:* Execute the HTTP GET immediately upon receiving Type 6; if the HTTP fetch fails (e.g., timeout or HTTP 404/403), automatically re-issue a fresh Type 5 request with an incremented `seq` (up to 3 retries).
2. **BLE Mesh Radio Congestion During Startup Polling:**
   * *Risk:* Querying 200+ lights simultaneously via Type 17 can flood the 2.4GHz BLE mesh and drop Type 15 responses.
   * *Mitigation:* Set `delay_max = 31` ($31 \times 15\text{ ms} = 465\text{ ms}$ random backoff window) on multi-device Type 17 sweeps and enforce a minimum 1.5-second cooldown between consecutive 104-device mask chunks.
3. **Extended Short Addresses ($> 255$):**
   * *Risk:* Large installations exceed 255 sub-devices, causing address collisions if only 1 byte is parsed.
   * *Mitigation:* Strictly parse the upper 4 bits of the Type 15 `0xC1+` report prefix byte alongside the LSB address byte, and use 2-byte Little-Endian addressing for Type 9 control commands and 2-byte Big-Endian (`MSB`, `LSB`) for Type 17 status queries.
4. **Light Off Command Quirk:**
   * *Risk:* Sending `00 00 00 00 00 00` fails to turn off lights per protocol rules.
   * *Mitigation:* Enforce single-byte `0x00` payload transmission whenever `light.turn_off` is invoked without a transition prefix.
5. **Shared `dev_t` (`43051`) Across Lighting Form Factors:**
   * *Risk:* Seven distinct FSL lighting `type_no` values (`301`–`306`, `315`) share `dev_t = 43051` (`2b a8`).
   * *Mitigation:* All seven share identical `ColorMode.COLOR_TEMP` control semantics; preserve `type_no` / `dev_version` as the device model metadata in the Home Assistant Device Registry while defaulting cleanly via `spid` when absent.
