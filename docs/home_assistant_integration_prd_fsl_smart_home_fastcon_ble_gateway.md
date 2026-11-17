# Product Requirements Document (PRD): FSL Smart Home Integration for Home Assistant

**Document Version:** 1.2  
**Brand / Integration Name:** FSL (`custom_components/fsl`)  
**Target Platform:** Home Assistant (Core / HACS Custom Integration)  
**Underlying Hardware & Protocols:** BroadLink Hardware Architecture, FASTCON BLE Gateway UDP Open Interface (v0.8) & Whole-House Device Profile Specification  
**Device Scope Baseline:** Intersection of `docs/default_dev_type.csv` (`dev_t`) and `docs/broadlink_whole_house_device_functions_and_profile_specification.md` (**35 FSL device types** across **24 BroadLink `dev_t` PIDs**)

---

## 1. Executive Summary

### 1.1 Product Vision
Refactor and evolve the `custom_components/fsl` Home Assistant integration from its legacy cloud-polling prototype (`smart-api.chinafsl.com`) into an official-grade, local-first Home Assistant custom integration branded under **FSL** (domain: `fsl`, display name: **FSL**). The integration bridges FSL smart home devices—built on BroadLink hardware and FASTCON BLE Gateways—directly into Home Assistant over the local area network (LAN) via UDP. By leveraging the gateway's open UDP interface, FSL users achieve ultra-low-latency local control, real-time asynchronous state updates, automated room/area synchronization, and native entity exposure without relying on continuous cloud connectivity.

### 1.2 Brand & Component Identity
* **Integration Display Name:** `FSL`
* **Component Domain (`manifest.json`):** `fsl` (`custom_components/fsl`)
* **Device Registry Attribution:** All discovered gateways and sub-devices must register in the Home Assistant Device Registry with `manufacturer="FSL"`, preserving the underlying FSL `type_no`, hardware PID (`dev_t`), and `dev_version` metadata, and linking sub-devices via `via_device` to the parent FSL Gateway.
* **HA Brands Repository:** Include brand icon and logo assets (`icon.png`, `logo.png`) structured for submission to `home-assistant/brands` under `custom_integrations/fsl`.

### 1.3 Core Objectives
1. **Zero-Cloud Runtime Control:** Execute all FSL device commands, group broadcasts, and scene triggers locally over UDP once initial device metadata is fetched.
2. **Automatic Topology & Area Discovery:** Automatically retrieve the home manifest (`devlist`, `familyInfo`, `grouplist`, `scenelist`) via the gateway's temporary HTTP URL mechanism (Type 5/6) and map FSL devices to Home Assistant Areas and Devices automatically.
3. **Targeted FSL Device Coverage:** Strictly support the **35 FSL device types** in `docs/default_dev_type.csv` whose BroadLink `dev_t` exists in `docs/broadlink_whole_house_device_functions_and_profile_specification.md`—spanning Lighting (`W`, `CW`, `RGB`, `RGBCW`, Radar/Induction Lights), 1–4 Gang Relay Switches & Composite Switch/Scene Panels, 4-Key & 6-Key Scene Panels, Motorized Curtains, HVAC & Thermostats (Individual Thermostat, Central AC Gateway, Virtual AC Remote), Sensors (Door/Window Contact, 5.8 GHz Motion, 24 GHz Human Presence Radar, Temp/Humidity), and Virtual TV IR Remote.
4. **Resilient Session Management:** Maintain uninterrupted communication through automated 15-second UDP heartbeat keep-alives, sequence deduplication, and self-healing reconnection logic.

---

## 2. System Architecture & Communication Engine

### 2.1 High-Level Architecture

```
+-------------------------------------------------------------------+
|                        Home Assistant Core                        |
|  +-------------+  +---------------+  +-------------------------+  |
|  | Config Flow |  | Area & Device |  |   Entity Platforms      |  |
|  |   ("FSL")   |  |   Registry    |  | (Light, Switch, Cover,  |  |
|  +------+------+  +-------+-------+  |  Climate, BinarySensor, |  |
|         |                 |          |  Sensor, Number, Event, |  |
|         |                 |          |  Remote, Scene, Button) |  |
|         v                 v          +------------+------------+  |
|  +-------------------------------------------------------------+  |
|  |                 FSL DataUpdateCoordinator                   |  |
|  |  - PID / type_no / dev_version Capability Resolver          |  |
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
|  - Listens on Configured UDP Port (e.g., 54321)                   |
|  - Serves Single-Use Config JSON via Ephemeral HTTP Port          |
|  - Translates UDP Frames <-> BLE Mesh Radio Broadcasts            |
+-------------------------------------------------------------------+
```

### 2.2 Transport & Session Lifecycle Requirements
* **Connection Modes:**
  * **Primary (Gateway Server Mode):** Home Assistant acts as a UDP client connecting to the FSL gateway's static IP and configured UDP port (e.g., `54321`). Supports LAN broadcast discovery via **Type 1 (Probe Request)** to `255.255.255.255` and parsing **Type 2 (Probe Response)** to auto-populate IP and Gateway MAC.
  * **Secondary (Gateway Client Mode):** Optional listener mode where HA binds to a local UDP port to accept inbound registration from gateways configured in Client Mode (`mode: 2`).
* **Keep-Alive Watchdog:**
  * Transmit **Type 3 (Heartbeat Request)** every **15 seconds** containing HA's virtual/host 6-byte MAC identifier.
  * Monitor **Type 4 (Heartbeat Response)**. If **5 consecutive responses (~75s)** are missed, mark FSL entities as `unavailable` and trigger an automatic discovery/re-registration cycle.
* **Packet Framing & Deduplication:**
  * Encode `type` (`uint16_t`) and `seq` (`uint16_t`) in **Little-Endian**; encode multi-byte payload fields in **Big-Endian** unless specified otherwise by device profiles.
  * Maintain a rolling cache of the last 128 received `seq` numbers to drop retransmitted duplicate packets.
* **Metadata Synchronization (Type 5 $\to$ Type 6):**
  * Upon connection establishment (and via a manual `fsl.reload_devices` service), send **Type 5** to obtain the single-use HTTP URL from **Type 6**.
  * Download the JSON manifest immediately, Base64-decode `devlist`, `familyInfo`, `grouplist`, and `scenelist`, and map `roomlist` entries to Home Assistant Areas.

### 2.3 State Synchronization Strategy
* **Asynchronous Push (Type 15 / Type 16):**
  * Continuously listen for **Type 15 (`0x000F`)** telemetry reports.
  * Immediately reply with **Type 16 (`0x0010`)** mirroring the exact `seq` to prevent gateway retransmission storms.
  * Parse both standard short addresses $\le 255$ (`0xC0` prefix) and extended short addresses $> 255$ (`0xC1+` prefix, where $\text{Addr} = ((\text{Byte}_1 \ \& \ 0\text{x0F}) \ll 8) + \text{Byte}_5$).
* **Active Status Polling (Type 17 / Type 18):**
  * Because non-sensor BLE devices do not push state spontaneously on boot, execute a staggered **Type 17** poll on HA startup and configurable intervals.
  * Chunk queries into blocks of up to 104 devices per 13-byte bitmask, ensuring $(\text{delay\_max} + 1)$ is strictly a power of 2 (e.g., `delay_max = 15` or `31` for multi-device sweeps, `0` for single-device queries).

---

## 3. Target FSL Device Catalog & Scope Boundaries

### 3.1 Filtered Device Catalog (`default_dev_type.csv` $\cap$ BroadLink Profile Specification)
Only FSL device types (`type_no`) from `docs/default_dev_type.csv` whose `dev_t` is documented in `docs/broadlink_whole_house_device_functions_and_profile_specification.md` are in scope (**35 device types**, **24 unique `dev_t` PIDs**):

| `type_no` | Category (`CSV`) | Chinese Name | English Name | Matched `dev_t` | PID (Hex, LE) | `dev_version` | HA Platform(s) |
| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| `301` | `MAIN_LIGHT` | 主灯 | main light | `43051` | `2b a8` | `1` | `light` |
| `302` | `CEILING_LIGHT` | 吸顶灯 | ceiling light | `43051` | `2b a8` | `2` | `light` |
| `303` | `LIGHT_BELT` | 灯带 | light belt | `43051` | `2b a8` | `3` | `light` |
| `304` | `DOWN_LIGHT` | 筒射灯 | down light | `43051` | `2b a8` | `4` | `light` |
| `305` | `MAGNET_DOWN_LIGHT` | 磁吸泛光灯 | magnet down light | `43051` | `2b a8` | `5` | `light` |
| `306` | `MAGNET_DOWN_LIGHT_NO_FLOODLIGHT` | 磁吸灯（除泛光） | magnet down light no floodlight | `43051` | `2b a8` | `6` | `light` |
| `315` | `FAN_LIGHT` | 风扇灯 | fanLight | `43051` | `2b a8` | — | `light` |
| `332` | `KW_WHITE_LIGHT` | 白灯 | kw_white_light | `43049` | `29 a8` | — | `light` |
| `331` | `KRGBCW_LIGHT` | 可调亮度和色温的彩灯 | krgbcw light | `43050` | `2a a8` | — | `light` |
| `352` | `UNIVERSAL_COLOR_LIGHT` | 通用彩灯 | UniversalColorLight | `43168` | `a0 a8` | — | `light` |
| `338` | `LIGHT_INDUCTION` | 微波灯管 | lightInduction | `44876`, `44956` | `4c af`, `9c af` | — | `light`, `switch`, `number`, `sensor` |
| `347` | `HANGING_WIRE_LAMP_PANEL` | 吊线灯盘 | HangingWireLampPanel | `45160` | `68 b0` | — | `light`, `switch`, `number`, `sensor` |
| `307` | `EASY_SWITCH` | 百搭开关 | easy switch | `44624` | `50 ae` | — | `switch`, `light` |
| `316` | `PWR_PANEL_ONE` | 一键开关 | pwrPanelOne | `43525` | `05 aa` | — | `switch`, `light` |
| `326` | `PWR_PANEL_TWO` | 二键开关 | pwrPanelTwo | `43474` | `d2 a9` | `0` | `switch`, `light` |
| `366` | `TWO_PANEL_TWO_EIGHT` | 2+2复合面板 | TwoPanelTwoEight | `43474` | `d2 a9` | `2` | `switch`, `event`, `light` |
| `358` | `FOUR_PANEL_TWO_EIGHT` | 2+4复合面板 | FourPanelTwoEight | `43474` | `d2 a9` | `4` | `switch`, `event`, `light` |
| `319` | `COM_PANEL_TWO_EIGHT` | 2+8复合面板 | comPanelTwoEight | `43474` | `d2 a9` | `8` | `switch`, `event`, `light` |
| `327` | `PWR_PANEL_THREE` | 三键开关 | pwrPanelThree | `43463` *(also `43462`)* | `c7 a9` | `0` | `switch`, `light` |
| `367` | `COM_PANEL_THREE_THREE` | 3+3复合面板 | comPanelThreeThree | `43463` | `c7 a9` | `3` | `switch`, `event`, `light` |
| `334` | `COM_PANEL_THREE_SIX` | 3+6复合面板 | comPanelThreeSix | `43463` | `c7 a9` | `6` | `switch`, `event`, `light` |
| `328` | `PWR_PANEL_FOUR` | 四键开关 | pwrPanelFour | `43680` | `a0 aa` | `0` | `switch`, `light` |
| `318` | `COM_PANEL_FOUR_FOUR` | 4+4复合面板 | comPanelFourFour | `43680` | `a0 aa` | `4` | `switch`, `event`, `light` |
| `317` | `COM_PANEL_FOUR_SIX` | 4+6复合面板 | comPanelFourSix | `43680` | `a0 aa` | `6` | `switch`, `event`, `light` |
| `329` | `SCENE_PANEL_FOUR` | 四键场景面板 | scenePanelFour | `43472`, `43473` | `d0 a9`, `d1 a9` | — | `event` |
| `330` | `SCENE_PANEL_SIX` | 六键场景面板 | scenePanelSix | `43459`, `43461` | `c3 a9`, `c5 a9` | — | `event` |
| `309` | `CURTAIN` | 窗帘 | curtain | `43499` *(also `43096`)* | `eb a9` | — | `cover` |
| `324` | `DOOR_SENSOR` | 门磁感应器 | doorsensor | `43505` | `f1 a9` | — | `binary_sensor` |
| `308` | `BODY_SENSOR` | 人体传感器 | body sensor | `43516` | `fc a9` | — | `binary_sensor`, `number` |
| `312` | `RADARSENSOR` | 24G存在感应器 | radarsensor | `44619` | `4b ae` | — | `binary_sensor`, `switch`, `number` |
| `360` | `TEMPHUMIDITY` | 温湿计 | temphumidity | `43951` | — | — | `sensor`, `binary_sensor` |
| `336` | `THERMOSTAT` | 温控器 | thermostat | `43919` | — | — | `climate`, `fan`, `sensor`, `binary_sensor` |
| `359` | `AIR_CONDITION_GATEWAY` | 中央空调网关 | AirConditionGateway | `43756` | — | — | `climate`, `fan`, `sensor`, `binary_sensor` |
| `354` | `VIRTUAL_AC_CONTROL` | 空调遥控 | AC remote control | `43919` | — | — | `climate` |
| `355` | `VIRTUAL_TV_CONTROL` | 电视遥控 | TV remote control | `44843` | `2b af` | — | `remote` |

> **Gateway Transport Role Note:** The FASTCON BLE Gateway itself (e.g., `325` `GATEWAY` / `43500`, `333` `WIRE_GATEWAY` / `44602`, `345` `4G_WIFI_ROUTER` / `44862`) serves as the local UDP bridge/parent hub in Home Assistant's Device Registry (`via_device`), exposing gateway diagnostic entities (`sensor` for Type 48/49 network status, `button` for Type 46/47 reboot) rather than acting as a BLE sub-device profile.

### 3.2 Explicitly Out-of-Scope Devices
To maintain tight focus and avoid unverified protocol code, the following are **excluded** from this PRD:
1. **BroadLink Spec Profiles Without a Matching `dev_t` in `default_dev_type.csv`:**
   * RGBW Light (`43169` / `a1 a8`)
   * Radar Light variants `45559` (`f7 b1`), `45408` (`60 b1`), `45161` (`69 b0`)
   * 1-Gang & 2-Gang Curtain Switch Panels (`44606` / `3e ae`, `44607` / `3f ae`)
   * 1–6 Gang Power Strips & Metering Sockets (`44181` / `95 ac`, `44180` / `94 ac`, `44167` / `87 ac`, `44164` / `84 ac`, `44165` / `85 ac`, `44166` / `86 ac`)
   * Universal In-line Breaker (`45733` / `a5 b2`)
   * Curtain/Blind Motors `44111` (`4f ac`), `44112` (`50 ac`), `44113` (`51 ac`), `44724` (`b4 ae`), `44725` (`b5 ae`), `44726` (`b6 ae`)
   * Always-Powered 5.8 GHz Motion Sensor (`43808` / `20 ab`), Water Leak (`43791` / `0f ab`), Rain Sensor (`45659` / `5b b2`), RTL8720 24 GHz Radar (`45477` / `a5 b1`), 8-in-1 Air Quality Detector (`44603` / `3b ae`), SOS Emergency Button (`44207` / `af ac`)
   * Smart Clothes Drying Rack (`44007`), Electric Fan / Ceiling Fan Controller (`44436` / `ad 94`), USB Music Rhythm Controller (`45739` / `ab b2`), Multi-functional Dry-Contact Input Box
   * Non-TV BroadLink RM IR/RF Sub-Devices (`44844`–`44847`, `44850`, `45153`, `45534`, `45660`–`45663`, `45666`–`45667`, `45669`)
2. **FSL CSV Rows Without a Documented BroadLink `dev_t` Profile:**
   * Touch screen panels (`310`, `311`), Super/Knob/Health Panels (`320`–`323`, `365`), Power Plug (`337`), Meters (`339`, `340`, `342`), Remotes (`341`, `346`, `353`), Self-developed 24G Radar (`344`), 4G Router (`343`), Newer Light Models (`335`, `348`–`351`, `356`, `357`, `361`–`364`).

---

## 4. Feature Specifications & Entity Mappings

### 4.1 User Onboarding & Configuration Flow (`custom_components/fsl/config_flow.py`)
* **Integration Branding:** Appears in Home Assistant's *Add Integration* menu as **FSL** (`domain: "fsl"`).
* **Auto-Discovery:** Broadcast Type 1 probe packets during setup to list discovered FSL gateways on the subnet by MAC and IP.
* **Manual Entry:** Allow users to manually input Gateway IP, UDP Port (default `54321`), and a custom 6-byte Client MAC identifier (auto-generated if omitted).
* **Options Flow:** Allow users to configure polling intervals, enable/disable transition fading (for FW $\ge 58$ lights), and filter ignored devices (`ignoreflag: true`).

### 4.2 Device Category to Home Assistant Platform Mapping

#### A. Lighting (`light` platform)
Supports the **12 matched lighting device types** across `dev_t` PIDs `43049` (`29 a8`), `43051` (`2b a8`), `43168` (`a0 a8`), `43050` (`2a a8`), `44876`/`44956` (`4c af`, `9c af`), and `45160` (`68 b0`).
* **Color Modes:** Dynamically assign Home Assistant `ColorMode` from `dev_t` / `spid` and `blecatetory`:
  * `43049` (`29 a8`, `332` `KW_WHITE_LIGHT`) $\to$ `ColorMode.BRIGHTNESS`
  * `43051` (`2b a8`, `301`–`306`, `315` `FAN_LIGHT`) $\to$ `ColorMode.COLOR_TEMP`
  * `43168` (`a0 a8`, `352` `UNIVERSAL_COLOR_LIGHT`) $\to$ `ColorMode.RGB`
  * `43050` (`2a a8`, `331` `KRGBCW_LIGHT`) $\to$ `ColorMode.RGBWW` (or `ColorMode.COLOR_TEMP` / `ColorMode.HS` + `COLOR_TEMP` mapped onto the 6-byte `Bri/B/R/G/W/C` frame)
  * `44876`/`44956` (`4c af`/`9c af`, `338` `LIGHT_INDUCTION`) & `45160` (`68 b0`, `347` `HANGING_WIRE_LAMP_PANEL`) $\to$ `ColorMode.BRIGHTNESS` (or `ColorMode.COLOR_TEMP` when warm/cool channels are active per telemetry).
* **Value Conversions:**
  * **Off Command:** Transmit single byte `0x00` (never 6 zero bytes).
  * **On (Restore):** Transmit `0x80`.
  * **Brightness:** Convert HA brightness ($0 - 255$) to protocol brightness ($0 - 127$):
    $$\text{Bri}_{\text{BL}} = \max\left(1, \left\lfloor \frac{\text{Bri}_{\text{HA}}}{255} \times 127 \right\rfloor\right)$$
  * **Color Temperature:** Map HA Kelvin ($2700\text{ K} - 6500\text{ K}$) to Warm ($W$) and Cool ($C$) channels where $C + W = 255$:
    $$C = \left\lfloor \frac{T_{\text{Kelvin}} - 2700}{6500 - 2700} \times 255 \right\rfloor, \quad W = 255 - C$$
* **Fade Transitions:** Prepend `0x80` (fade enabled) or `0x00` (instant) when `transition` attribute is passed in `light.turn_on` / `light.turn_off` (for firmware $\ge 58$).
* **Radar / Induction Light Extensions (`338`, `347`):** Expose additional entities on the same FSL HA Device (queried via `91 00 00 00 00 00`, supporting both FW $\le \text{v}78$ and $\ge \text{v}79$ telemetry formats):
  * `switch`: Radar Enable/Disable (`Byte 0`).
  * `number`: High/Occupied Brightness ($\%$, `Byte 1`), Mid Brightness ($\%$, `Byte 5`), Standby/Low Brightness ($\%$, `Byte 2`), Unoccupied Hold Time (`nobody_keep_time` in $\text{s}$, `Bytes 3–4` LE), and Mid Brightness Hold Time ($\text{s}$, `Bytes 6–7` LE).
  * `sensor`: Operating Runtime ($\text{h}$, from cumulative seconds) and Energy Integral / Power Consumption ($\text{kWh}$, calculated from $\frac{\text{Integral} \times 8}{\text{Runtime} \times 127} \times \text{RatedPower} \times \text{Time}$ when rated wattage is configured).

#### B. Relay Switches & Composite Switch Panels (`switch`, `event`, & `light` platforms)
Supports the **12 matched switch and composite panel types**:
* **1-Channel / 1-Gang (`44624` `50 ae` [`307`], `43525` `05 aa` [`316`]):** 1 `switch` entity (bit 0).
* **2-Gang (`43474` `d2 a9`):** `326` (`dev_version=0`, pure 2-gang), plus composite panels `366` (`dev_version=2`, 2+2), `358` (`dev_version=4`, 2+4), `319` (`dev_version=8`, 2+8) $\to$ 2 `switch` entities (bits 0–1).
* **3-Gang (`43463` `c7 a9`):** `327` (`dev_version=0`, pure 3-gang), plus composite panels `367` (`dev_version=3`, 3+3), `334` (`dev_version=6`, 3+6) $\to$ 3 `switch` entities (bits 0–2).
* **4-Gang (`43680` `a0 aa`):** `328` (`dev_version=0`, pure 4-gang), plus composite panels `318` (`dev_version=4`, 4+4), `317` (`dev_version=6`, 4+6) $\to$ 4 `switch` entities (bits 0–3).
* **Protocol Mapping:** Map bit $i$ in 2-byte `ctrl_mask` (`Byte 0`) and `output_mask` (`Byte 1`) to each gang entity; optionally use `ctrl_mask = 0x00` for firmware $\ge 18$ toggle commands.
* **Composite Scene Key Handling (`dev_version` $\in \{2, 3, 4, 6, 8\}$):** In addition to the $1 - 4$ relay `switch` entities, composite panels expose `event` entities (`fsl_button_press`) corresponding to their auxiliary scene keys ($2, 3, 4, 6,$ or $8$ keys per `dev_version`).
* **Panel Backlight Control:** Expose a `light` entity (brightness-only, `0 = off`, `1–127 = brightness`, `0x80 = restore`) using TLV `sub_type = 32` (`0x20`) for switch panels supporting backlight dimming.

#### C. Scene Panels (`event` platform)
Supports **4-Key Scene Panel (`329`, `43472`/`43473` [`d0 a9`, `d1 a9`])** and **6-Key Scene Panel (`330`, `43459`/`43461` [`c3 a9`, `c5 a9`])**.
* Fire Home Assistant `event` entities (`fsl_button_press`) with `key_id` ($0 - 3$ for 4-key, $0 - 5$ for 6-key) and the decoded 3-byte `SCENEID` (`[GroupID, 0x00, SceneSeq]`) payload when pressed.

#### D. Motorized Curtains (`cover` platform)
Supports **`309` `CURTAIN` (`43499` / `eb a9`, Drapery Motor)**.
* **Supported Features:** `OPEN`, `CLOSE`, `STOP`, `SET_POSITION`.
* **Command Mapping (`curtain_frame_t`, 6 bytes):**
  * Open: `01 FF 00 00 00 00`
  * Close: `02 FF 00 00 00 00`
  * Stop/Pause: `03 FF 00 00 00 00`
  * Set Position ($0 - 100\%$): `00 <pos_hex> 00 00 00 00`
* Parse `Byte 1` ($0 - 100\%$) and `Byte 0 Bits 0–1` (`01` opening, `10` closing, `00`/`11` stopped) from telemetry to report `current_cover_position`, `is_opening`, `is_closing`, and `is_closed`.

#### E. HVAC & Thermostats (`climate`, `fan`, `sensor`, & `binary_sensor` platforms)
Supports **`359` `AIR_CONDITION_GATEWAY` (`43756`)**, **`336` `THERMOSTAT` (`43919`)**, and **`354` `VIRTUAL_AC_CONTROL` (`43919`)**.
* **Standard AC Entity (`43756`, `43919`):**
  * TLV Control Types `0–6, 14` and 6–9 byte telemetry frame.
  * `HVACMode`: `OFF`, `AUTO`, `HEAT`, `COOL`, `FAN_ONLY`, `DRY`.
  * `FanMode`: `auto`, `low`, `medium`, `high`.
  * `SwingMode`: `off`, `vertical`, `horizontal`, `both`.
  * Temperature Range: $16^\circ\text{C} - 30^\circ\text{C}$ ($1^\circ\text{C}$ step), displaying signed ambient room temperature (`Byte 5`).
* **3-in-1 Thermostat Decomposition (when 15-byte 3-in-1 telemetry frame is reported):**
  * Primary `climate` entity for Air Conditioning (`16–30 °C`).
  * Secondary `climate` entity for Underfloor Heating (`16–45 °C`, `HEAT`/`OFF`).
  * `fan` entity for Fresh Air Ventilation (modes: `fresh_air`, `cool_wind`, `smart`, `high`, `sleep`, `purify`).
  * Diagnostic `sensor` entities for Outdoor Temp (`Byte 9`), Humidity (`Byte 10`), $\text{PM}_{2.5}$ (`Bytes 11–12`), and `binary_sensor` alert for Filter Replacement (`Byte 13`).

#### F. Sensors (`binary_sensor`, `sensor`, & `number` platforms)
Supports the **4 matched sensor device types**:
* **Door/Window Contact Sensor (`324`, `43505` / `f1 a9`):**
  * `binary_sensor` (`BinarySensorDeviceClass.DOOR`, Byte 0), Tamper (`TAMPER`, Byte 1), Low Battery (`BATTERY`, Byte 2).
* **5.8 GHz Motion Sensor (`308`, `43516` / `fc a9`):**
  * `binary_sensor` (`MOTION`, Byte 0), Tamper (`TAMPER`, Byte 1), Low Battery (`BATTERY`, Byte 2).
  * `number` entity for Vacancy Timeout ($20 - 524\text{ s}$, default $20\text{ s}$) configured via TLV `sub_type = 31` (`0x1F`).
* **24 GHz Human Presence Radar Sensor (`312`, `44619` / `4b ae`, BLE Module):**
  * `binary_sensor` (`OCCUPANCY`) reflecting real-time Type 15 presence telemetry.
  * Support Three-Stage Automation & Schedule Configuration via TLV `tlv_type = 24` (`onoff`, `high_scene_id`, `delay_time1`, `mid_scene_id`, `delay_time2`, `low_scene_id`) and Schedule Configuration frames (`switch` / `number` entities for radar enable and `delay_time1` / `delay_time2`). *(Note: RTL8720 `a5 b1` serial Type 27 parameters are excluded as `45477` is not in `default_dev_type.csv`).*
* **Temperature & Humidity Sensor (`360`, `43951`):**
  * `sensor` for Temperature (scaled integer `Bits 0–15`, auto-converting $^\circ\text{C}$ / $^\circ\text{F}$ based on `Bits 16–23` unit flag: `1 = °C`, `2 = °F`) and Humidity (`Bits 24–31`, $0 - 100\%$).
  * `binary_sensor` (`BATTERY`) for Low Battery (`Bits 32–39`).
  * Optional configuration service/number entities for TLV Types `0–3` (High/Low Temp and Humidity thresholds).

#### G. Virtual TV Remote (`remote` platform)
Supports **`355` `VIRTUAL_TV_CONTROL` (`44843` / `2b af`)**.
* Expose an HA `remote` entity with `send_command` support dispatching standard BroadLink RM TV media command codes (`0x01` Power On/Off, `0x02` Input Source, `0x03` Mute, `0x05` OK/Enter, `0x06–0x0F` Digits 1–0, `0x11` Vol+, `0x12` Vol-, `0x13` Ch+, `0x14` Ch-, `0x15–0x18` D-Pad Up/Down/Left/Right, `0x1D` Back, `0x1E` Home, `0x21` Pause, `0x22` Play, `0x30` Exit, `0x36` Stop, `0x38` HDMI Select, etc.).

### 4.3 Group & Scene Integration

#### Native Group Control (Type 13)
* Parse `grouplist` from the downloaded family JSON.
* **Virtual Group ID Resolution:** When `groupId > 255` (e.g., `257` = `0x0101` for Living Room Lights):
  * Compute physical group ID: $\text{TargetGroupID} = \text{groupId} \ \& \ 0\text{xFF}$.
  * Resolve Category Parent PID from `blecatetory` using the in-scope category table:
    * Lighting Fixtures (`1`) $\to$ `2A A8`
    * Motorized Curtains (`2`) $\to$ `EB A9`
    * Relay Switches (`3`) $\to$ `C3 A9`
    * Thermostats / AC / HVAC / Fresh Air / Underfloor Heating (`4`, `11`, `12`) $\to$ `EC AA`
* Expose groups as native HA entities (e.g., `light.fsl_living_room_lights`, `cover.fsl_living_room_curtains`, `switch.fsl_living_room_switches`, `climate.fsl_living_room_hvac`) that dispatch a single **Type 13** multicast packet rather than sequential unicast commands, eliminating "popcorn effect" latency.

#### Native Scene Entities (Type 11)
* Parse `scenelist` and create HA `scene` entities.
* Activating a scene in HA transmits **Type 11 (`0x000B`)** with the 3-byte Big-Endian Scene ID (`[RoomGroupID, 0x00, SceneSeq]`).

---

## 5. Non-Functional Requirements

| Category | Requirement | Target Metric |
| :--- | :--- | :--- |
| **Latency** | End-to-end local command execution (HA UI click $\to$ BLE device actuation) | $< 150\text{ ms}$ |
| **Reliability** | Automated heartbeat recovery without user intervention after Wi-Fi/Router reboot | $100\%$ recovery within $90\text{ s}$ |
| **Scalability** | Support large whole-house deployments with extended short addresses ($> 255$) | Up to $500+$ sub-devices per gateway |
| **Network Traffic** | Avoid BLE mesh radio congestion during status polling | Max 1 Type 17 broadcast every $2\text{ s}$ |
| **Code Quality** | Compliance with Home Assistant Integration Quality Scale | Async-only I/O (`asyncio.DatagramProtocol`), full type annotations, $> 90\%$ test coverage |

---

## 6. Phased Implementation Roadmap (Stages)

### Stage 1: Core Transport Engine, FSL Branding & MVP Device Support (Weeks 1–3)
**Goal:** Replace the legacy cloud-polling implementation with rock-solid local UDP connectivity, FSL device catalog resolution, auto-discovery, and primary lighting/switching/curtain/sensor control.
* **Features:**
  * Refactor `custom_components/fsl` (`manifest.json` `"iot_class": "local_push"`, Device Registry `manufacturer="FSL"`, `via_device` gateway hierarchy, and `type_no`/`dev_t`/`dev_version` capability table for the 35 supported FSL types).
  * Implement `asyncio` UDP client transport with Little-Endian header framing and 15-second heartbeat loop (Type 3/4).
  * Build Config Flow supporting Type 1/2 LAN broadcast discovery and manual IP/Port entry.
  * Implement Type 5/6 single-use URL retrieval, JSON/Base64 parsing, and automatic HA Area creation (`familyInfo`).
  * Implement Type 15 async telemetry listener with immediate Type 16 ACK replies (supporting both `0xC0` and `0xC1+` extended short addresses).
  * Deliver MVP platforms:
    * `light`: `301`–`306`, `315`, `331`, `332`, `352` (`W`, `CW`, `RGB`, `RGBCW` lights).
    * `switch`: `307`, `316`, `326`, `327`, `328` (1–4 gang relay switches) + switch gangs for composite panels (`317`–`319`, `334`, `358`, `366`, `367`).
    * `cover`: `309` (`CURTAIN` `43499` open/close/stop/position).
    * `binary_sensor`: `324` (`DOOR_SENSOR` `43505`) and `308` (`BODY_SENSOR` `43516`).

### Stage 2: Native Groups, Scenes, Polling & HVAC Climate (Weeks 4–6)
**Goal:** Eliminate multi-device latency via native multicast groups, enable scene execution, add scene/composite panel events, and add full HVAC support.
* **Features:**
  * Implement staggered, rate-limited active status polling using **Type 17** bitmask frames (104-device chunking).
  * Implement **Type 13** Group Control with automatic Virtual Group ID (`> 255`) bitwise extraction and Parent PID mapping (`2A A8`, `EB A9`, `C3 A9`, `EC AA`).
  * Expose `scenelist` items as native Home Assistant `scene` entities (**Type 11**).
  * Deliver `event` platform for Scene Panels (`329`, `330`) and composite switch panel scene keys (`317`–`319`, `334`, `358`, `366`, `367`), plus panel backlight `light` entities (`sub_type = 32`).
  * Deliver `climate` (and conditional `fan`/`sensor`/`binary_sensor`) platform supporting `359` (`43756`), `336` (`43919`), and `354` (`43919`).
  * Add firmware $\ge 58$ smooth fade transition support (`0x80`/`0x00` prefix) to `light` entities.

### Stage 3: Radar Lights, Presence Radar, Environmental Sensors & Virtual TV Remote (Weeks 7–9)
**Goal:** Complete coverage across the remaining targeted FSL device types and gateway diagnostics.
* **Features:**
  * Integrate **24 GHz Human Presence Radar (`312`, `44619`)** with occupancy `binary_sensor` and `tlv_type = 24` configuration/schedule entities.
  * Integrate **Temperature & Humidity Sensor (`360`, `43951`)** with automatic $^\circ\text{C}/^\circ\text{F}$ unit conversion, humidity, and low-battery alert.
  * Integrate **5.8 GHz Motion Sensor (`308`, `43516`)** vacancy timeout `number` entity (`sub_type = 31`).
  * Integrate **Radar/Induction Lights (`338`, `44876`/`44956` and `347`, `45160`)** with three-stage brightness parameters, radar enable switch, and runtime/energy reporting.
  * Integrate **Virtual TV Remote (`355`, `44843` / `2b af`)** via the HA `remote` platform.
  * Add FSL Gateway Diagnostic entities: Network Connectivity Status sensor (**Type 48/49**) and Gateway Reboot button (**Type 46/47**), plus optional **Gateway Client Mode** listener and Developer Services (`fsl.send_raw_command`, `fsl.reload_devices`).

### Stage 4: Ephemeral Group Optimization, Brand Submission & HACS Release (Weeks 10–11)
**Goal:** Optimize multi-light transitions, publish official FSL brand assets, and release for public adoption.
* **Features:**
  * Implement **Type 19 (Set Temporary Group)** dynamic cookie allocation when Home Assistant triggers simultaneous state changes across ad-hoc subsets of lights.
  * Submit official **FSL** vector/PNG logos and icons to `home-assistant/brands` (`custom_integrations/fsl`).
  * Complete end-to-end automated test suite (mock UDP gateway simulator testing all 35 FSL device types, packet loss, out-of-order `seq`, and $> 255$ short addresses).
  * Package and publish the **FSL** integration to **HACS (Home Assistant Community Store)** with complete user documentation and migration notes from v0.1.0.

---

## 7. Edge Cases & Risk Mitigation

1. **Single-Use Config URL Expiration (Type 6):**
   * *Risk:* The HTTP URL returned by Type 6 becomes invalid immediately after one HTTP GET request or after a short timeout.
   * *Mitigation:* Execute the HTTP GET immediately upon receiving Type 6; if the HTTP fetch fails (e.g., timeout or HTTP 404/403), automatically re-issue a fresh Type 5 request with an incremented `seq` (up to 3 retries).
2. **BLE Mesh Radio Congestion During Startup Polling:**
   * *Risk:* Querying 200+ devices simultaneously via Type 17 can flood the 2.4GHz BLE mesh and drop Type 15 responses.
   * *Mitigation:* Set `delay_max = 31` ($31 \times 15\text{ ms} = 465\text{ ms}$ random backoff window) on multi-device Type 17 sweeps and enforce a minimum 1.5-second cooldown between consecutive 104-device mask chunks.
3. **Extended Short Addresses ($> 255$):**
   * *Risk:* Large installations exceed 255 sub-devices, causing address collisions if only 1 byte is parsed.
   * *Mitigation:* Strictly parse the upper 4 bits of the Type 15 `0xC1+` report prefix byte alongside the LSB address byte, and use 2-byte Little-Endian addressing for Type 9 control commands and 2-byte Big-Endian (`MSB`, `LSB`) for Type 17 status queries.
4. **Light Off Command Quirk:**
   * *Risk:* Sending `00 00 00 00 00 00` fails to turn off lights per protocol rules.
   * *Mitigation:* Enforce single-byte `0x00` payload transmission whenever `light.turn_off` is invoked without a transition prefix.
5. **Shared PID (`dev_t`) Disambiguation Across `type_no` Variants:**
   * *Risk:* Multiple FSL `type_no` values share the same BroadLink `dev_t` (e.g., `43474`, `43463`, `43680` across standard vs. composite switch panels; `43051` across lighting form factors and `FAN_LIGHT`; `43919` across `THERMOSTAT` and `VIRTUAL_AC_CONTROL`).
   * *Mitigation:* Resolve entity models and auxiliary capabilities (such as composite scene key count via `dev_version`) by combining BroadLink `spid`/`dev_t` with FSL `type_no`/`dev_version` metadata, falling back gracefully to `spid` defaults when FSL-specific metadata is absent in local gateway `devlist` payloads.
