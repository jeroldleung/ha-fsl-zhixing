# BroadLink Whole-House Device Functions and Profile Specification

---

# 1. BroadLink Lighting Products

## 1.1 Universal 1–5 Channel Lights

Lighting fixtures are primarily divided into five major categories:

1. **White (W):** Supports On/Off and brightness adjustment.
2. **Tunable White (CW / CCT):** Supports On/Off, brightness, and color temperature adjustment.
3. **RGB:** Supports On/Off, brightness, and Red, Green, Blue color mixing.
4. **RGBW:** Supports On/Off, brightness, and Red, Green, Blue, White control.
5. **RGBCW:** Supports On/Off, brightness, color temperature (CW), and Red, Green, Blue (RGB) control.

### Light Product IDs (PIDs)

| DeviceType | PID (Hex) | Device Name |
| :--- | :--- | :--- |
| 43049 | `29 a8` | White Light (W) |
| 43051 | `2b a8` | Tunable White Light (CW) |
| 43168 | `a0 a8` | RGB Color Light |
| 43169 | `a1 a8` | RGBW Light |
| 43050 | `2a a8` *(also serves as the group control Parent PID for lighting)* | RGBCW Light |

### Supported System Features
- Network provisioning and onboarding
- Single device control (unicast)
- Group control (multicast)
- Scene editing and association
- Room migration / reassignment
- Status query
- Music rhythm sync
- Remote controller / panel binding
- Scene mode presets (optional)
- Local timers and schedules (optional)

---

### Device Control Protocol

The standard lighting control payload is defined as a 6-byte structure:

| Byte 0 | Byte 1 | Byte 2 | Byte 3 | Byte 4 | Byte 5 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Bits 0–6:** Brightness<br>**Bit 7:** Power Switch<br>*(If Bit 7 is 1 and Bits 0–6 are 0, the light restores its last brightness)* | Blue (B) | Red (R) | Green (G) | Warm White (W) | Cool White (C) |

- **Turn Off:** `00` *(Note: Turning off must be transmitted as a single `0x00` byte, not all 6 bytes as `0x00`)*
- **Turn On:** `80` *(Restores last brightness state)*
- **Brightness Adjustment:** Transmitted in the first byte (subsequent bytes omitted if adjusting brightness only).
  - *Example:* For $50\%$ brightness: $127 \times 50\% \approx 64$ (`0x40`).

#### Bit-Field Definitions

| Feature | Bit Range | Range / Values | Access |
| :--- | :--- | :--- | :---: |
| Brightness | Bits 0–6 | $0 - 127$ (maps to $0\% - 100\%$) | RW |
| Power Switch | Bit 7 | `0`: Off<br>`1`: On | RW |
| Blue (B) | Bits 8–15 | $0 - 255$ | RW |
| Red (R) | Bits 16–23 | $0 - 255$ | RW |
| Green (G) | Bits 24–31 | $0 - 255$ | RW |
| Warm White (W) | Bits 32–39 | $0 - 255$ | RW |
| Cool White (C) | Bits 40–47 | $0 - 255$ | RW |

**Calculation Formulas:**
- **Brightness:** Let target brightness percentage be $x\%$. $\text{Bri} = 127 \times x\%$.
- **Color Temperature (CCT):** Ranging from $2700\text{ K}$ to $6500\text{ K}$.
  - Daylight White ($6500\text{ K}$): Cool White $C = \text{0xFF}$, Warm White $W = \text{0x00}$.
  - Warm White ($2700\text{ K}$): Warm White $W = \text{0xFF}$, Cool White $C = \text{0x00}$.
  - Intermediate color temperatures must satisfy the condition: $C + W = 255$.

---

### Special Extended Commands

To interface with physical wall switch panels, knob dimmers, and remote controls, the first byte is overloaded with command opcodes, and an additional trailing `data` byte (specifying direction or speed) is appended:

| Byte 0 (Opcode) | Command Name | Framing / Example | Description |
| :---: | :--- | :--- | :--- |
| `0x81` | Toggle Power | `81 00 00 00 00 00` | Inverts current light state internally. |
| `0x82` | Stepless Dimming | `82 00 00 00 00 00 <data>` | `<data>` indicates direction:<br>• $1 - 127$: Dim up to maximum.<br>• $128 - 255$: Dim down to minimum. |
| `0x83` | Stepless CCT Tuning | `83 00 00 00 00 00 <data>` | `<data>` indicates direction:<br>• $1 - 127$: Tune warmer.<br>• $128 - 255$: Tune cooler. |
| `0x84` | Stepless Color Cycling | `84 00 00 00 00 00 <data>` | `<data>` sets RGB transition speed (higher is faster). |
| `0x85` | Non-directional Dimming | `85 00 00 00 00 00 10` | Continues dimming in previous direction until boundary is reached. Default step: `0x10`. |
| `0x85` | Stop Dimming | `85 00 00 00 00 00 00` | Halts continuous dimming immediately. |
| `0x87` | Non-directional CCT Tuning | `87 00 00 00 00 00 30` | Continues tuning in previous direction. Default step: `0x30`. |
| `0x87` | Stop CCT Tuning | `87 00 00 00 00 00 00` | Halts continuous CCT adjustment. |
| `0x88` | Relative Brightness Step | `88 00 00 00 00 00 <delta>` | `<delta>` is a signed integer ($\Delta\text{Bri}$):<br>• $+1 \text{ to } +127$: Increase brightness.<br>• $-1 \text{ to } -128$: Decrease brightness. |
| `0x89` | Relative CCT Step | `89 00 00 00 00 00 <delta>` | `<delta>` is a signed integer ($\Delta\text{CCT}$):<br>• $+1 \text{ to } +127$: Decrease color temperature.<br>• $-1 \text{ to } -128$: Increase color temperature. |
| `0x94` | Dynamic Pattern Report | `94 00 00 00 00 00 <delta> <data...>` | `<delta>`: Transition speed.<br>`<data>`: Dynamic mode flags (max 7 bytes).<br>• Bit 7: `0` = Fade / Smooth, `1` = Jump / Strobe.<br>• Bit 6: Fixed to `1`.<br>• Bit 4: Cool White enable.<br>• Bit 3: Warm White enable.<br>• Bit 2: Green enable.<br>• Bit 1: Red enable.<br>• Bit 0: Blue enable. |

#### Notes on Extended Commands
1. Setting `<data> = 0` stops any ongoing stepless transition.
2. For single-button toggle dimming, use `0x85`. For dual-button (up/down) dimmers, use `0x82`.

---

### Fade/Transition Curve Configuration (Firmware $\ge 58$)

To support driver-level dimming curves and smooth on/off transitions, an optional prefix byte is prepended to the standard 6-byte payload:

| Byte 0 | Byte 1 | Byte 2 | Byte 3 | Byte 4 | Byte 5 | Byte 6 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `0x00`: Disable fading transition<br>`0x80`: Enable fading transition (uses firmware default speed) | Brightness (Bits 0–6)<br>Power (Bit 7) | Blue | Red | Green | Warm | Cool |

*(Note: Fading configuration is volatile and reverts to factory defaults upon reboot; it is ignored during dynamic color scene playback).*

#### New TLV Control Protocol Frame Structure

| Header (4 Bytes) | TLV Header (1 Byte) | Sub_type (1 Byte) | Data Content (16 Bytes) |
| :--- | :---: | :--- | :--- |
| Message Type (`msg_type = 5`) Control Request | Fixed to `0x00` | **Bit 7:** Fixed to `0`<br>**Bit 6:** Fixed to `1`<br>**Bits 0–5:**<br>• `6`: Unicast Short Address Control<br>• `7`: Multicast Group Control | **Unicast Control:**<br>• Byte 0: Length<br>• Byte 1: Device Short Address<br>• Bytes 2–15: Control Payload<br><br>**Group Control:**<br>• Byte 0: Length<br>• Bytes 1–2: Group PID<br>• Byte 3: Group ID<br>• Bytes 4–15: Control Payload |

---

## 1.2 Self-Learning Radar Lights (Parking Lots / Hallways)

These lights integrate microwave radar and peer-to-peer BLE mesh learning algorithms for adaptive lighting in parking garages and corridors.

### Product IDs (PIDs)

| DeviceType | PID (Hex) | Device Name |
| :--- | :--- | :--- |
| 44876 | `4c af` | Smart Light (BroadLink Universal) |
| 45559 | `f7 b1` | Smart Light (ADC Voltage Sensing) |
| 44956 | `9c af` | Smart Light (Customized) |
| 45408 | `60 b1` | Smart Tunable White Light |
| 45161 | `69 b0` | Smart Light (Customized) |
| 45160 | `68 b0` | Smart Light (Customized) |

### 1.2.1 Basic Power and Dimming
Uses the same 6-byte format as standard lights:
- **Turn Off:** `00`
- **Turn On:** `80`

### 1.2.2 Three-Stage Brightness Parameters

| Byte | Parameter Name | Description |
| :---: | :--- | :--- |
| 0 | Radar Enable | `1`: Radar active; `0`: Radar disabled. |
| 1 | High Brightness (Occupied) | Brightness when presence is detected. Default: $80\%$. |
| 2 | Low Brightness (Standby) | Brightness when area is vacant. Default: $10\%$. |
| 3–4 | Unoccupied Hold Time (`nobody_keep_time`) | Time in seconds (Little-Endian) radar must confirm absence before transitioning to standby. Default: $20\text{ s}$. |
| 5 | Mid Brightness (Intermediate) | Intermediate standby level (`0` = disabled). Default: $30\%$. |
| 6–7 | Mid Brightness Hold Time | Duration in seconds (Little-Endian) to stay at intermediate brightness. Default: $20\text{ s}$. |

### 1.2.3 Querying and Reporting Three-Stage Brightness
To read the active three-stage parameters, send a standard control frame setting $\text{Bri} = \text{0x91}$ with all subsequent color bytes zeroed (`91 00 00 00 00 00`).

The fixture responds with a 22-byte telemetry packet formatted as:
```hex
C1 1A 3B 58 02 00 E0 91 00 00 00 00 00 01 73 0D 14 00 26 14 00 00
```
- `C1`: Report Type flag (indicates short address in range $255 - 511$).
- `1A 3B 58`: Sequence counter, Family Key byte, Checksum.
- `02`: Short address low byte (combined with `C1` offset $\to 258$).
- `00 E0`: Three-stage brightness report type descriptor.
- `91 00 00 00 00 00`: Three-stage brightness identifier header.
- `01 73 0D 14 00 26 14 00 00`: 8-byte three-stage parameter payload + padding.

---

### 1.2.4 Radar Operating Schedule

| Byte | Bits | Field | Description |
| :---: | :---: | :--- | :--- |
| 0 | Bits 0–4 | Hour ($h$) | Current system hour ($0 - 23$). |
| 0 | Bits 5–7 | Week ($wek$) | Reserved / Day of week (Set to `0`). |
| 1 | Bits 0–5 | Minute ($min$) | Current system minute ($0 - 59$). |
| 1 | Bit 6 | Reserved | Fixed to `0`. |
| 1 | Bit 7 | Schedule Enable | `1`: Active; `0`: Disabled. |
| 2 | Bits 0–7 | Out-of-Schedule Brightness | Fallback brightness ($0\% - 100\%$; `0` = Off). |
| 3 | Bit 0 | Period 1 Switch | `1`: Period 1 Enabled; `0`: Disabled. |
| 3 | Bits 1–7 | Start Minute 1 ($min_1$) | Start minute for Period 1. |
| 4–5 | Bits 0–2 | Start Hour 1 Low ($h_{1\text{L}}$) | Start hour LSBs. |
| 4–5 | Bits 3–8 | End Minute 1 ($min_2$) | End minute for Period 1. |
| 4–5 | Bits 9–13 | End Hour 1 ($h_2$) | End hour for Period 1. |
| 4–5 | Bits 14–15| Start Hour 1 High ($h_{1\text{H}}$)| Start hour MSBs. |
| 6 | Bit 0 | Period 2 Switch | `1`: Period 2 Enabled; `0`: Disabled. |
| 6 | Bits 1–7 | Start Minute 2 ($min_1$) | Start minute for Period 2. |
| 7–8 | Bits 0–2 | Start Hour 2 Low ($h_{1\text{L}}$) | Start hour LSBs. |
| 7–8 | Bits 3–8 | End Minute 2 ($min_2$) | End minute for Period 2. |
| 7–8 | Bits 9–13 | End Hour 2 ($h_2$) | End hour for Period 2. |
| 7–8 | Bits 14–15| Start Hour 2 High ($h_{1\text{H}}$)| Start hour MSBs. |

---

### 1.2.5 Self-Learning Mesh Parameters

| Byte | Parameter | Values / Description |
| :---: | :--- | :--- |
| 0 | Learning Enable | `1`: Enabled; `0`: Disabled. |
| 1 | TX Power | Allowed values: `0xFD` ($-3\text{ dBm}$), `0xFB` ($-5\text{ dBm}$), `0xFA` ($-6\text{ dBm}$), `0xF6` ($-10\text{ dBm}$), `0xF1` ($-15\text{ dBm}$), `0xEC` ($-20\text{ dBm}$), `0` ($0\text{ dBm}$), `3` ($+3\text{ dBm}$), `4` ($+4\text{ dBm}$), `5` ($+5\text{ dBm}$), `10` ($+10\text{ dBm}$). Default: $5\text{ dBm}$. |
| 2 | Relay Hops | Range: $1 - 6$. Default: `3`. Maximum mesh retransmission hops for occupancy broadcasts. |
| 3 | Weight Divisor | Range: $1 - 10$. Default: `3`. Spatial learning radius weighting factor. |
| 4–5 | Timeout (Little-Endian) | Range: $1 - 65535\text{ s}$. Default: $4\text{ s}$. Maximum interval between adjacent detections to correlate peer fixtures. |

---

### 1.2.6 Radar Hardware Parameters

| Byte | Parameter | Values / Description |
| :---: | :--- | :--- |
| 0 | Operating Mode | `0`: Self-learning Mesh (Default); `1`: Group Mode; `2`: Radar Off. |
| 1 | Photosensor / AC Frequency | • Bits 0–4: Photosensor Enable (`0`: Off, `1`: On).<br>• Bit 5: AC Frequency (`0`: $50\text{ Hz}$, `1`: $60\text{ Hz}$). |
| 2–3 | Radar Sensitivity Threshold | $0 - 1023$ (Higher value indicates shorter detection range). Default: `30`. |
| 4–5 | Output Hold Time (`output_timeout`)| Duration in ms that high-level presence signal is sustained. Default: $300\text{ ms}$. |
| 6–7 | BLE TX Radar Blanking Window | Blanking window in ms to prevent false triggers during BLE radio TX. Default: $1000\text{ ms}$ ($\ge \text{output\_timeout}$). |
| 8 | Occupancy Broadcast Repetitions | Number of repeated BLE broadcast bursts. Default: `3`. |
| 9 | Packet Burst Size | Number of raw packets per broadcast cycle. Default: `10`. |
| 10–11 | Ambient Light Sensor Threshold | Reserved (2 Bytes). |
| 12–13 | Turn-Off Filter Duration | Debounce delay in ms prior to turning off lights. |

---

### 1.2.7 Telemetry & Energy Reporting

#### Format for Firmware Versions $\le \text{v}78$ (15 Bytes Data Payload)
- **Byte 0:** Brightness (Bits 0–6: $0 - 127$) & Switch (Bit 7: `1` = On, `0` = Off).
- **Bytes 1–3:** Radar Trigger Count (Little-Endian, Bits 8–31).
- **Byte 4:** Warm White (Bits 32–39).
- **Byte 5:** Cool White (Bits 40–47).
- **Bytes 6–9:** Energy Consumption Integral (Little-Endian, Bits 48–79). $\text{Reported Integral} = \frac{\text{Actual Integral}}{8}$.
- **Bytes 10–13:** Cumulative Operating Runtime (Seconds, Little-Endian, Bits 80–111).
- **Byte 14:** Most Significant Byte of Radar Trigger Count.

#### Format for Firmware Versions $\ge \text{v}79$
| Byte 0 | Byte 1 | Bytes 2–5 | Bytes 6–9 | Bytes 10–14 |
| :--- | :--- | :--- | :--- | :--- |
| **Bit 7:** Power (`1` = On, `0` = Off)<br>**Bits 0–6:** Brightness ($0 - 127$) | MAC Byte 5 | Operating Runtime (Seconds, Little-Endian) | Energy Integral (Little-Endian)<br>$\text{Value} = \frac{\text{Bri} \times \text{Seconds}}{8}$ | MAC Bytes 0–4 |

$$\text{Actual Power (W)} = \left(\frac{\text{Energy Integral} \times 8}{\text{Runtime (s)}} \div 127\right) \times \text{Rated Wattage}$$

---

# 2. Relay Switches, Power Sockets, and Power Strips

## 2.1 Universal Switch Panels

Switch panels provide 1-gang to 4-gang physical relays.

### Switch and Socket Product IDs (PIDs)

| DeviceType | PID (Hex) | Description |
| :--- | :--- | :--- |
| 43525 | `05 aa` | 1-Gang Switch Panel |
| 43474 | `d2 a9` | 2-Gang Switch Panel |
| 43463 | `c7 a9` | 3-Gang Switch Panel |
| 43680 | `a0 aa` | 4-Gang Switch Panel |
| 44624 | `50 ae` | Universal Relay Module (1-Channel) |
| 44606 | `3e ae` | 1-Gang Curtain Switch Panel (Open/Close interlocked) |
| 44607 | `3f ae` | 2-Gang Curtain Switch Panel |
| **All Panels** | **`c3 a9`** | **Group Control Parent PID for Wall Switches** |
| 44181 | `95 ac` | 1-Gang Wall Socket / Receptacle |
| 44180 | `94 ac` | 2-Gang Power Strip |
| 44167 | `87 ac` | 3-Gang Power Strip |
| 44164 | `84 ac` | 4-Gang Power Strip |
| 44165 | `85 ac` | 5-Gang Power Strip |
| 44166 | `86 ac` | 6-Gang Power Strip |
| **All Sockets**| **`95 ac`** | **Group Control Parent PID for Power Strips** |

---

### Relay Control and State Reporting Protocol

Standard payload consists of 2 bytes:

| Byte 0: `ctrl_mask` | Byte 1: `output_mask` |
| :--- | :--- |
| **Channel Selection Mask**<br>• Bit 0: Gang 1 Enabled<br>• Bit 1: Gang 2 Enabled<br>• Bit 2: Gang 3 Enabled<br>• Bit 3: Gang 4 Enabled | **Target State Value**<br>• Bit 0: Gang 1 State (`1` = On, `0` = Off)<br>• Bit 1: Gang 2 State<br>• Bit 2: Gang 3 State<br>• Bit 3: Gang 4 State |

#### Invert / Toggle Mode (Firmware $\ge 18$)
When `ctrl_mask == 0x00`, `output_mask` acts as a **Toggle Bitmask**. Any gang whose corresponding bit is set to `1` will toggle its current state.

---

### Switch Panel Backlight Control Protocol (New TLV Format)

| Header (4 Bytes) | TLV Header (1 Byte) | Sub_type (1 Byte) | Request Payload (2 Bytes) |
| :--- | :---: | :---: | :--- |
| `msg_type = 5` (Control Request) | Fixed to `0x00` | `32` (`0x20`) (Backlight Control) | • Byte 0: `short_addr` (Panel Short Address)<br>• Byte 1: `bright`<br>  - `0`: Turn off backlight.<br>  - Bit 7 = `1`: Turn on (restore last level).<br>  - $1 - 127$: Set absolute brightness level. |

---

## 2.2 Power Metering Sockets

### Configuration Frame Format

| Byte | Parameter | Description |
| :---: | :--- | :--- |
| 0 | `ctrl_mask` | Channel selection mask (`0x00` = Toggle). |
| 1 | `output_mask` | Channel output states. Must be `0x0001` (Gang 1) to configure subsequent parameters. |
| 2 | Features & Operations | • Bits 4–7: Feature enables (Bit 7: Child Lock, Bit 6: LED, Bit 5: Clear Energy Accumulator).<br>• Bits 0–3: Actions (Bit 3: Child Lock On/Off, Bit 2: LED On/Off, Bit 1: Clear Energy Accumulator). |
| 3 | Threshold Alarm Enables | • Bit 0: Over-Current<br>• Bit 1: Under-Current<br>• Bit 2: Over-Voltage<br>• Bit 3: Under-Voltage<br>• Bit 4: Over-Power<br>• Bit 5: Under-Power<br>*(Set Byte 3 to `0x00` to clear all threshold alarms)* |
| 4 | High Current Threshold | In steps of $100\text{ mA}$ ($0 - 16000\text{ mA}$). |
| 5 | Low Current Threshold | In steps of $100\text{ mA}$ ($0 - 16000\text{ mA}$). |
| 6–7 | High Voltage Threshold | In steps of $0.1\text{ V}$ ($0 - 255\text{ V}$). |
| 8–9 | Low Voltage Threshold | In steps of $0.1\text{ V}$ ($0 - 255\text{ V}$). |
| 10–11 | High Power Threshold | In Watts ($0 - 6000\text{ W}$). |
| 12–13 | Low Power Threshold | In Watts ($0 - 6000\text{ W}$). |

### Telemetry Reporting Profile (Query Command: `00 01 00 00 FF FF FF FF FF FF FF FF FF FF`)

| Byte Offset | Parameter | Unit / Scaling |
| :---: | :--- | :--- |
| Bytes 0–1 | Current | $100\text{ mA}$ ($0 - 16000\text{ mA}$) |
| Bytes 2–3 | Voltage | $0.1\text{ V}$ ($0 - 255.0\text{ V}$) |
| Bytes 4–5 | Active Power | $1\text{ W}$ ($0 - 6000\text{ W}$) |
| Bytes 6–9 | Cumulative Energy | Watt-hours ($\text{Wh}$, Little-Endian) |

---

# 3. Scene Panels

Scene panels are battery-operated or mains-powered trigger devices. They do not execute loads directly; instead, pressing a key broadcasts an unacknowledged 3-byte `SCENEID`.

### Product IDs (PIDs)

| DeviceType | PID (Hex) | Description |
| :--- | :--- | :--- |
| 43459 | `c3 a9` | Low-Power 6-Key Scene Panel (Battery) |
| 43461 | `c5 a9` | Always-Powered 6-Key Scene Panel (Mains) |
| 43472 | `d0 a9` | Low-Power 4-Key Scene Panel (Battery) |
| 43473 | `d1 a9` | Always-Powered 4-Key Scene Panel (Mains) |

### Key Numbering
- **Key 1:** `0`
- **Key 2:** `1`
- **Key 3:** `2`
- **Key 4:** `3`
- **Key 5:** `4`
- **Key 6:** `5`

### `SCENEID` Structure (3 Bytes)

| Byte 0 | Byte 1 | Byte 2 |
| :---: | :---: | :---: |
| `GroupID` (Room ID where scene resides) | `0x00` (Fixed) | Scene Sequence Number / Short Address |

---

# 4. Sensor Devices

## 4.1 Door / Window Contact Sensor
- **DeviceType:** 43505 | **PID:** `f1 a9` (Battery-powered)

### Telemetry Report Payload

| Feature | Bits | Access | Values |
| :--- | :---: | :---: | :--- |
| Door Contact | Bits 0–7 | R | • Telemetry: `0` = Closed, `1` = Open.<br>• Binding Trigger: `0` = Trigger on Open, `1` = Trigger on Close. |
| Tamper Alarm | Bits 8–15 | R | `0` = Normal, `1` = Tamper Detected. |
| Low Battery | Bits 16–23 | R | `0` = Normal, `1` = Low Battery Alert. |

---

## 4.2 5.8 GHz Microwave Motion Sensor
- **Low-Power Version:** DeviceType 43516 | PID `fc a9`
- **Always-Powered Version:** DeviceType 43808 | PID `20 ab`

### Telemetry Report Payload

| Feature | Bits | Access | Values |
| :--- | :---: | :---: | :--- |
| Occupancy | Bits 0–7 | R | • Telemetry: `0` = Vacant, `1` = Occupied.<br>• Binding Trigger: `0` = Trigger on Occupied, `1` = Trigger on Vacant. |
| Tamper Alarm | Bits 8–15 | R | `0` = Normal, `1` = Tamper Detected. |
| Low Battery | Bits 16–23 | R | `0` = Normal, `1` = Low Battery Alert. |

### Vacancy Delay Configuration (New TLV Format)

| Header (4 Bytes) | TLV Header (1 Byte) | Sub_type (1 Byte) | Payload (3 Bytes) |
| :--- | :---: | :---: | :--- |
| `msg_type = 5` | Fixed to `0x00` | `31` (`0x1F`) | • Byte 0: `short_addr` (Sensor Short Address)<br>• Bytes 1–2: `timeout` (Seconds, range $20 - 524\text{ s}$; Default $20\text{ s}$). |

---

## 4.3 Temperature & Humidity Sensor
- **DeviceType:** 43951

### Threshold Configuration Command (TLV Format)

| Type | Function | Length | Values |
| :---: | :--- | :---: | :--- |
| `0` | High Temperature Threshold | 1 | $0 - 255$ |
| `1` | Low Temperature Threshold | 1 | $0 - 255$ |
| `2` | High Humidity Threshold | 1 | $0 - 100\%$ |
| `3` | Low Humidity Threshold | 1 | $0 - 100\%$ |

*Example:* Set high temperature threshold to $26^\circ\text{C}$: `00 01 1A`

### Telemetry Report Payload

| Feature | Bits | Access | Values |
| :--- | :---: | :---: | :--- |
| Temperature | Bits 0–15 | R | Scaled integer ($0 - 2000$). |
| Unit | Bits 16–23 | R | `1` = Celsius ($^\circ\text{C}$); `2` = Fahrenheit ($^\circ\text{F}$). |
| Humidity | Bits 24–31 | R | $0\% - 100\%\text{ RH}$. |
| Low Battery | Bits 32–39 | R | `0` = Normal; `1` = Low Battery. |

---

## 4.4 Water Leak / Immersion Sensor
- **DeviceType:** 43791 | **PID:** `0f ab`
- **Telemetry Payload:**
  - Bits 0–7: Water Immersion (`0` = Normal, `1` = Leak Detected).
  - Bits 8–15: Tamper Alarm (`0` = Normal, `1` = Tampered).
  - Bits 16–23: Low Battery Alert (`0` = Normal, `1` = Low Battery).

---

## 4.5 Rain Sensor
- **DeviceType:** 45659 | **PID:** `5b b2`
- **Telemetry Payload:**
  - Bits 0–7: Rain Detection (`0` = Dry, `1` = Rain Present).
  - Bits 8–15: Tamper Alarm (`0` = Normal, `1` = Tampered).
  - Bits 16–23: Low Battery Alert (`0` = Normal, `1` = Low Battery).
  - Bits 24–39: Detection Voltage (mV, Little-Endian).

---

## 4.6 24 GHz Human Presence Radar Sensor
- **BLE Module:** DeviceType 44619 | PID `4b ae`
- **RTL8720 Module:** DeviceType 45477 | PID `a5 b1`

### Three-Stage Automation Sequence
1. **Presence Detected:** Executes `high_scene_id` immediately.
2. **Vacancy Stage 1:** After `delay_time1` of no presence, executes `mid_scene_id`.
3. **Vacancy Stage 2:** After an additional `delay_time2`, executes `low_scene_id`.

### Parameter Configuration Frame (`tlv_type = 24`)

| Byte | Parameter | Description |
| :---: | :--- | :--- |
| 0 | `onoff` | `1`: Enabled; `0`: Disabled; `0x5A`: Subordinate Sensor Mode. |
| 1–2 | `high_scene_id` | Scene ID triggered on presence detection.<br>*(If `onoff == 0x5A`, Byte 1 = Subordinate Sensor Address, Byte 2 = Master Sensor Address).* |
| 3–4 | `delay_time1` | Vacancy hold delay in seconds before intermediate scene. Default: $30\text{ s}$. |
| 5–6 | `mid_scene_id` | Intermediate scene ID (Omitted/Zero if `onoff == 0x5A`). |
| 7–8 | `delay_time2` | Secondary vacancy delay in seconds (Omitted/Zero if `onoff == 0x5A`). |
| 9–10 | `low_scene_id` | Final unoccupied scene ID (Omitted/Zero if `onoff == 0x5A`). |

---

### Radar Schedule Configuration Frame

| Byte | Bits | Field | Description |
| :---: | :---: | :--- | :--- |
| 0 | Bits 0–7 | Schedule Enable | `1`: Enabled; `0`: Disabled. |
| 1–2 | Bits 0–15 | Out-of-Schedule Scene ID | Scene executed during off-schedule hours. |
| 3 | Bit 0 | Period 1 Enable | `1`: Period 1 Enabled; `0`: Disabled. |
| 3 | Bits 1–7 | Start Minute 1 ($min_1$) | Start minute. |
| 4–5 | Bits 0–2 | Start Hour 1 Low | Start hour LSBs. |
| 4–5 | Bits 3–8 | End Minute 1 ($min_2$) | End minute. |
| 4–5 | Bits 9–13 | End Hour 1 ($h_2$) | End hour. |
| 4–5 | Bits 14–15| Start Hour 1 High | Start hour MSBs. |
| 6 | Bit 0 | Period 2 Enable | `1`: Period 2 Enabled; `0`: Disabled. |
| 6 | Bits 1–7 | Start Minute 2 ($min_1$) | Start minute. |
| 7–8 | Bits 0–2 | Start Hour 2 Low | Start hour LSBs. |
| 7–8 | Bits 3–8 | End Minute 2 ($min_2$) | End minute. |
| 7–8 | Bits 9–13 | End Hour 2 ($h_2$) | End hour. |
| 7–8 | Bits 14–15| Start Hour 2 High | Start hour MSBs. |

---

### Extended MCU Parameters for PID `a5 b1` (Serial Type 27)

| Byte | Bit(s) | Parameter | RW | Description |
| :---: | :---: | :--- | :---: | :--- |
| 0 | 0 | Presence Status | R | `0` = Vacant, `1` = Occupied. |
| 0 | 1 | Radar Power | RW | `0` = Disabled, `1` = Enabled (Default). |
| 0 | 2 | Presence Sensing Switch | RW | `0` = Motion Only, `1` = Micro-motion Presence Enabled. |
| 0 | 3 | Indicator LED | RW | `0` = LED Off, `1` = LED On (Default). |
| 0 | 4–5 | Detection Zone Mask | RW | `00` = Full Zone, `01` = Left Zone Only, `10` = Right Zone Only. |
| 0 | 6–7 | Sensitivity Level | RW | `00` = Low, `01` = Medium, `10` = High (Default). |
| 1 | 0 | Factory Reset | W | `1` = Reset parameters to default. |
| 1 | 1 | Find Device | W | `1` = Flash LED for 5 seconds. |
| 1 | 2 | Environment Learning | RW | `1` = Start background RF/noise baseline calibration. |
| 2–3 | — | Illuminance (Lux) | R | $0 - 65535\text{ Lux}$. |
| 4 | — | Lux Delta Trigger | RW | $1 - 100\text{ Lux}$ change threshold to prompt report. |
| 5 | — | Lux Calibration Multiplier| RW | Multiplier ($0 - 10\times$) to align sensor reading with desk plane. |
| 6–7 | — | Vacancy Delay | RW | $0 - 3600\text{ s}$. Default: $30\text{ s}$. |
| 8 | — | Detection Distance Gate | RW | Levels $1 - 8$ ($0.5\text{ m} - 4.0\text{ m}$ in $0.5\text{ m}$ increments). |
| 9 | — | Learning Duration | RW | $1 - 30\text{ minutes}$. Default: $5\text{ minutes}$. |

---

# 5. Motors & Smart Curtains

Shared protocol for drapery openers, roller blinds, vertical dream blinds, and venetian blinds.

### Product IDs (PIDs)

| DeviceType | PID (Hex) | Description |
| :--- | :--- | :--- |
| 44111 | `4f ac` | Drapery Motor (Auto-calibration limits) |
| 44112 | `50 ac` | Roller Blind Motor |
| 44113 | `51 ac` | Dream / Vertical Blind Motor |
| 44724 | `b4 ae` | Venetian Blind Motor |
| 44725 | `b5 ae` | Day & Night Blind Motor |
| 44726 | `b6 ae` | Dual-Motor Drapery Controller |
| 43499 | `eb a9` *(Group Control PID)* | Drapery Motor (Manual travel limit setup) |

---

### Curtain Control & State Frame Structure (`curtain_frame_t`)

| Byte | Bit Field | Function | Allowed Values |
| :---: | :---: | :--- | :--- |
| **0** | Bits 0–1 | Motor 1 Motion | `00`: Stop / Inching Stop<br>`01`: Open / Up<br>`10`: Close / Down<br>`11`: Pause |
| | Bits 2–3 | Motor Direction | `00`: Unchanged<br>`01`: Reverse<br>`10`: Normal<br>`11`: Invert Direction |
| | Bit 4 | Inching Confirmation | `1`: Jog motor once as tactile feedback |
| | Bits 5–6 | Inching Mode | `00`: Unchanged<br>`01`: Continuous Run Mode<br>`10`: Step Inching Mode |
| | Bit 7 | Intermediate Position | `1`: Move to 3rd Favorite Limit Position |
| **1** | — | Primary Travel Percentage | $0 - 100\%$ (`0xFF` = Do not adjust position). |
| **2** | Bits 0–3 | Motor 2 Limits | `0001`: Set Upper; `0010`: Del Upper; `0100`: Set Lower; `1000`: Del Lower; `1010`: Del Both; `0101`: Set 3rd Limit; `1111`: Limit Exists (Report). |
| | Bits 4–5 | RF Learning | `01`: Pairing Mode (Copy Code); `10`: Clear Codes. |
| | Bits 6–7 | Manual Pull-to-Start | `01`: Disabled; `10`: Enabled (Default). |
| **3** | — | Secondary Travel / Tilt | $0 - 100\%$ ($0 - 180^\circ$ slat tilt angle; `0xFF` = Ignore). |
| **4** | Bits 0–3 | Motor 1 Limits | Same encoding as Byte 2 Bits 0–3. |
| | Bits 4–7 | LED / Speed Setting | `0001`: Slow Flash; `0010`: Fast Flash; `0011`: Const On; `0100`: Off.<br>`1001`: Speed Gear 1; `1010`: Speed Gear 2; `1011`: Speed Gear 3. |
| **5** | Bit 0 | Child Lock | `0`: Disabled; `1`: Active. |
| | Bits 1–3 | Blade Slat Rotation | `001`: Tilt Left / Page Up; `010`: Tilt Right / Page Down; `011`: Pause.<br>*(For dual motor, controls Motor 2 Up/Down/Pause)*. |
| | Bits 4–5 | High-Voltage AC Mode | `0x00`: Dual momentary; `0x01`: Dual latching; `0x02`: Smart switch; `0x03`: Single-button toggle. |
| | Bits 6–7 | Dry-Contact Mode | `0x00`: Dual latching; `0x01`: Hotel mode; `0x02`: Dual momentary; `0x03`: Single-button toggle. |

#### Common Command Examples (Hex)
- **Open:** `01 FF 00 00 00 00` (or `01 FF 00 FF 00 00`)
- **Close:** `02 FF 00 00 00 00` (or `02 FF 00 FF 00 00`)
- **Pause:** `03 FF 00 00 00 00` (or `03 FF 00 FF 00 00`)
- **Reverse:** `0C FF 00 00 00 00`
- **Percentage ($50\%$):** `00 32 00 00 00 00`

---

# 6. HVAC & Thermostats

Unified protocol controlling Air Conditioning (AC), Underfloor Heating, and Fresh Air Systems.
- **Gateway Bridge:** DeviceType 43756
- **Individual Thermostat:** DeviceType 43919
- **Group Parent PID:** `ec aa`

## 6.1 Standard AC Commands (TLV Format)

| Type | Parameter | Length | Values |
| :---: | :--- | :---: | :--- |
| `0` | Power Switch | 1 | `0`: Off; `1`: On |
| `1` | Mode | 1 | `0`: Auto; `1`: Heat; `2`: Cool; `4`: Vent/Fan; `8`: Dry/Dehumidify |
| `2` | Target Temperature | 1 | Integer in $^\circ\text{C}$ (AC: $16 - 30^\circ\text{C}$; Underfloor: $16 - 45^\circ\text{C}$) |
| `3` | Fan Speed | 1 | `0`: Auto; `1`: Low; `2`: Med; `3`: High |
| `4` | Auxiliary Features | 1 | • Bits 0–3: Action (Bit 0: Display Light On/Off, Bit 1: Child Lock On/Off).<br>• Bits 4–7: Mask (Bit 4: Display Light Mask, Bit 5: Child Lock Mask). |
| `5` | Swing & Health | 1 | • Bits 0–3: Action (Bit 0: Horiz Swing, Bit 1: Vert Swing, Bit 2: Screen, Bit 3: Health/Ionizer).<br>• Bits 4–7: Mask (Bit 4: Horiz Mask, Bit 5: Vert Mask, Bit 6: Screen Mask, Bit 7: Health Mask). |
| `6` | Auto-Off Timer | 1 | Steps of $0.5\text{ h}$ ($0 - 8 \to 0 - 4\text{ hours}$; `0` = Cancel). |
| `14`| Eco & Sleep | 1 | • Bits 0–3: Action (Bit 0: Sleep, Bit 1: Eco, Bit 2: Electric Aux Heat).<br>• Bits 4–7: Mask (Bit 4: Sleep Mask, Bit 5: Eco Mask, Bit 6: Aux Heat Mask). |

*Examples:*
- Turn Off: `00 01 00`
- Power On + Set Cooling: `00 01 01 01 01 02`

---

### AC Telemetry Report Format (Non-TLV Fixed Frame: 6–9 Bytes)

| Byte | Parameter | Values |
| :---: | :--- | :--- |
| 0 | Power State | `0`: Off; `1`: On |
| 1 | Mode | `0`: Auto; `1`: Heat; `2`: Cool; `4`: Fan; `8`: Dry |
| 2 | Target Temp | Target temperature in $^\circ\text{C}$. |
| 3 | Fan Speed | `0`: Auto; `1`: Low; `2`: Med; `3`: High |
| 4 | Fault Code | Error code (`0` = Normal). |
| 5 | Room Ambient Temp | Signed integer:<br>• `0x00 - 0x32`: $0^\circ\text{C} \text{ to } +50^\circ\text{C}$.<br>• `0xCE - 0xFF`: $-50^\circ\text{C} \text{ to } -1^\circ\text{C}$. |
| 6 | Auxiliary Status | Bits 0–3: Light/Lock states; Bits 4–7: Masks. |
| 7 | Swing/Health Status | Bits 0–3: Swing states; Bits 4–7: Masks. |
| 8 | Sleep/Eco Status | Bits 0–3: Mode states; Bits 4–7: Masks. |

---

## 6.2 Real Estate 3-in-1 Thermostat (AC + Underfloor Heat + Fresh Air)

### Control & Status Matrix (15-Byte Telemetry Frame)

| Byte / Type | Function | RW | Values / Description |
| :---: | :--- | :---: | :--- |
| **0** | System Power | RW | • Bits 0–3: Actions (Bit 0: AC On/Off, Bit 1: Floor Heat On/Off, Bit 2: Fresh Air On/Off).<br>• Bits 4–7: Mask (Bit 4: AC Mask, Bit 5: Floor Heat Mask, Bit 6: Fresh Air Mask). |
| **1** | System Mode | RW | • Bits 0–3 (AC): `0` = Auto, `1` = Heat, `2` = Cool, `4` = Fan, `8` = Dry.<br>• Bits 4–7 (Fresh Air): `1` = Fresh Air, `2` = Cool Wind, `3` = Smart, `4` = High, `5` = Sleep, `6` = Purify. |
| **2** | AC Setpoint | RW | $16 - 30^\circ\text{C}$. |
| **3** | Fan Speed | RW | • Bits 0–3 (AC): `0` = Auto, `1` = Low, `2` = Med, `3` = High, `4` = Turbo, `5` = Quiet.<br>• Bits 4–7 (Fresh Air): `1` = Low, `2` = Med, `3` = High, `4` = Med-Low, `5` = Med-High, `6` = Auto. |
| **4** | AC Error Code | R | $0 - 255$ (`0` = No Fault). |
| **5** | Indoor Temp | R | Signed byte ($-50^\circ\text{C} \text{ to } +50^\circ\text{C}$). |
| **6** | Underfloor Temp | RW | $16 - 45^\circ\text{C}$. |
| **7** | AC Vane Swing | RW | • Bits 0–3 (Vert): $1 - 5$ Positions, `6` = Swing, `7` = Stop.<br>• Bits 4–7 (Horiz): $1 - 5$ Positions, `6` = Swing, `7` = Stop. |
| **8** | Fresh Air / Floor Error | R | • Bits 0–3 (Fresh Air): `1` = Comm, `2` = Sensor, `3` = Fan Motor, `4` = Exhaust Motor, `5` = Damper.<br>• Bits 4–7 (Underfloor Heat): Error codes. |
| **9** | Outdoor Temp | R | Signed byte ($-50^\circ\text{C} \text{ to } +50^\circ\text{C}$). |
| **10** | Humidity | R | $0\% - 100\%\text{ RH}$. |
| **11–12**| PM2.5 Level | R | $0 - 999\ \mu\text{g/m}^3$ (Unsigned integer). |
| **13** | Filter Life Alert | R | `0` = Normal; `1` = Filter Replacement Due. |
| **14** | Eco Mode | RW | • Bit 0: Sleep On/Off; Bit 1: Eco On/Off.<br>• Bit 4: Sleep Mask; Bit 5: Eco Mask. |

---

# 7. Smart Clothes Drying Rack
- **DeviceType:** 44007

### Control Protocol (TLV Format)

| Type | Function | Length | Values |
| :---: | :--- | :---: | :--- |
| `00` | Lift Motor | 1 | `0`: Up; `1`: Down; `2`: Stop; `3`: No action |
| `01` | Lighting | 1 | `0`: Off; `1`: On; `2`: No action |
| `02` | Air Dry (Fan) | 1 | `0`: Off; `1`: On; `2`: No action |
| `03` | Heated Dry | 1 | `0`: Off; `1`: On; `2`: No action |
| `04` | UV Disinfection | 1 | `0`: Off; `1`: On; `2`: No action |

*Examples:*
- Lift Up: `00 01 00`
- Heated Dry On: `03 01 01`

### Status Report Payload (6 Bytes Fixed Frame)
- **Byte 0 (Lift):** `0` = Top Limit Reached; `1` = Bottom Limit Reached; `2` = Traveling / Mid-point.
- **Byte 1 (Light):** `0` = Off; `1` = On.
- **Byte 2 (Air Dry):** `0` = Off; `1` = On.
- **Byte 3 (Heated Dry):** `0` = Off; `1` = On.
- **Byte 4 (UV Disinfect):** `0` = Off; `1` = On.
- **Byte 5 (Fault Code):** `0x00` = No Fault; Non-zero = Error.

---

# 8. Multi-functional Dry-Contact Input Box

Interfaces 1 to 4 external dry-contact switches/sensors with the BroadLink BLE ecosystem.

### Control Frame (2 Bytes)
- **Byte 0 (`ctrl_mask`):** Bits 0–3 select target channels 1 to 4.
- **Byte 1 (`output_mask`):** Bits 0–3 set output polarity (`1` = High level, `0` = Low level).

---

# 9. SOS Emergency Alarm Button
- **DeviceType:** 44207 | **PID:** `af ac`
- Features: Push alerts, scene triggers, event log tracking.
- **Cancel Alarm Payload (App $\to$ Device):** `01 00`

---

# 10. Electric Fans & Ceiling Fan Lights

- **Fan Light Controller PID:** `ad 94` (DeviceType 44436)

### Control Frame (`Type + Data`, 2 Bytes per Command)

| Control Function | Type | Data Byte Definition | Report Format |
| :--- | :---: | :--- | :--- |
| Speed Step Offset | `0x00` | Signed Integer ($\pm \Delta\text{Speed}$) | *(Not reported)* |
| Speed Control | `0x01` | `0x00` = Off; `0x80` = On; $0 - 127$ = Absolute Speed | Byte 1 |
| Function Switch | `0x02` | `0x00`: Normal Mode<br>`0x01`: Natural Breeze Mode<br>`0x02`: Sleep Mode<br>`0x03`: Forward Rotation (Downdraft)<br>`0x04`: Reverse Rotation (Updraft)<br>`0x05`: Invert Direction<br>`0x06`: Buzzer Beep On<br>`0x07`: Buzzer Beep Off<br>`0x08`: Louver / Deflector On<br>`0x09`: Louver / Deflector Off<br>`0x0A`: Ionizer Air Purifier On<br>`0x0B`: Ionizer Air Purifier Off | Byte 2:<br>• Bits 0–1: Mode<br>• Bit 2: Direction<br>• Bit 3: Buzzer<br>• Bit 4: Louver |
| Timer Off | `0x03` | `0` = Cancel; $1 - 255$ minutes | Byte 3 |

---

# 11. Multi-functional Air Quality Detector
- **DeviceType:** 44603 | **PID:** `3b ae` (Little-Endian)
- Form-factor: Type 86 in-wall panel monitoring Temp, RH, $\text{PM}_{2.5}$, $\text{PM}_{10}$, $\text{CO}_2$, Lux, HCHO, and TVOC.

### Threshold Setup (TLV Commands)
- **Type 0 (High Temp):** 1 Byte unsigned ($^\circ\text{C}$). Range: $-10^\circ\text{C} \text{ to } +50^\circ\text{C}$.
- **Type 1 (Low Temp):** 1 Byte unsigned ($^\circ\text{C}$). Range: $-10^\circ\text{C} \text{ to } +50^\circ\text{C}$.
- **Type 2 (High RH):** 1 Byte unsigned ($\%\text{ RH}$). Range: $0\% - 99\%\text{ RH}$.

### Telemetry Reporting Profile (15 Bytes)

| Byte Offset | Parameter | Tag | Range | Scale Multiplier | Unit |
| :---: | :--- | :--- | :--- | :---: | :---: |
| 0–1 | Temperature | `envtemp` | $-1000 \text{ to } 7000$ | $0.01$ | $^\circ\text{C}$ |
| 2 | Humidity | `envhumid` | $0 - 99$ | $1$ | $\%\text{ RH}$ |
| 3–4 | $\text{PM}_{2.5}$ | `aclnr_pm25` | $0 - 999$ | $1$ | $\mu\text{g/m}^3$ |
| 5–6 | $\text{CO}_2$ | `envco2` | $0 - 5000$ | $1$ | $\text{ppm}$ |
| 7–8 | $\text{PM}_{10}$ | `pm10` | $0 - 999$ | $1$ | $\mu\text{g/m}^3$ |
| 9–10 | Illuminance | `envlux` | $0 - 9999$ | $1$ | $\text{Lux}$ |
| 11–12 | Formaldehyde (HCHO)| `envmethanal`| $0 - 2400$ | $0.001$ | $\text{mg/m}^3$ |
| 13–14 | TVOC | `voc_value` | $0 - 5000$ | $0.001$ | $\text{mg/m}^3$ |

*(Note: If a specific sensor hardware component is not fitted, its corresponding bytes return `0xFF`).*

---

# 12. BroadLink RM Sub-Devices (IR / RF Blasters)

Virtual peripheral sub-devices bridged via BroadLink RM infrared/RF transmitters.

### Product IDs (PIDs - Little-Endian)

| DeviceType | PID | Category | DeviceType | PID | Category |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 44843 | `2b af` | TV | 45660 | `5c b2` | Audio / Soundbar |
| 44844 | `2c af` | Set-Top Box | 45661 | `5d b2` | Power Amplifier |
| 44845 | `2d af` | Projector | 45153 | `61 b0` | Motorized Curtain |
| 44847 | `2f af` | DVD Player | 44846 | `2e af` | Fan |
| 43050 | `2a a8` | Lighting | 45662 | `5e b2` | Air Purifier |
| 45663 | `5f b2` | Water Heater | 45666 | `62 b2` | Humidifier |
| 45667 | `63 b2` | Robot Vacuum | 45669 | `65 b2` | Clothes Drying Rack |
| 44850 | `32 af` | Learning IR Remotes | 45534 | `de b1` | Learning RF Remotes |

---

### Command Codes (`cmd`) for Media Devices (TV, STB, Projectors, Audio)

| Code | Key / Action | Code | Key / Action | Code | Key / Action | Code | Key / Action |
| :---: | :--- | :---: | :--- | :---: | :--- | :---: | :--- |
| `0x01` | Power On/Off | `0x0B` | Digit 6 | `0x15` | D-Pad Up | `0x27` | Audio Mode |
| `0x02` | Input Source | `0x0C` | Digit 7 | `0x16` | D-Pad Down | `0x28` | Net Streaming |
| `0x03` | Mute | `0x0D` | Digit 8 | `0x17` | D-Pad Left | `0x2A` | EPG Guide |
| `0x04` | TV Mode OK | `0x0E` | Digit 9 | `0x18` | D-Pad Right | `0x2B` | Red Button |
| `0x05` | OK / Enter | `0x0F` | Digit 0 | `0x1B` | Info / Display | `0x2C` | Green Button |
| `0x06` | Digit 1 | `0x10` | Replay | `0x1C` | Context Menu | `0x2D` | Yellow Button |
| `0x07` | Digit 2 | `0x11` | Volume Up | `0x1D` | Back / Return | `0x2E` | Blue Button |
| `0x08` | Digit 3 | `0x12` | Volume Down | `0x1E` | Home / Main | `0x2F` | Help |
| `0x09` | Digit 4 | `0x13` | Channel Up | `0x1F` | Fast Forward | `0x30` | Exit |
| `0x0A` | Digit 5 | `0x14` | Channel Down | `0x20` | Rewind | `0x38` | HDMI Select |
| `0x21` | Pause | `0x22` | Play | `0x36` | Stop | `0x3D` | Auto |

---

# 13. Ethernet Gateway & IHG Configuration

### Control Protocol (TLV Format)

| Type | Function | Payload Structure |
| :---: | :--- | :--- |
| `0` | Server Mode | • Bytes 0–1: UDP Listening Port<br>• Bytes 2–5: Reserved (Zero)<br>• Bytes 6–7: LAN Sharing Port |
| `1` | Client Mode | • Bytes 0–1: Server UDP Target Port<br>• Bytes 2–5: Server Target IPv4 Address (Little-Endian) |
| `3` | DHCP & Static IP | • Bytes 0–3: Static IP (Little-Endian)<br>• Bytes 4–7: Primary DNS (Little-Endian)<br>• Byte 8: Bit 0 = DHCP Enable (`1`: On, `0`: Off); Bits 1–6 = Netmask CIDR prefix length ($0 - 32$). |

### Special Query Instructions

1. **Query UDP Operating Mode:**
   - **Send:** `FF 00 00 00 00 00 00 00`
   - **Response Payload:**
     - Byte 0: Bitmask (Bit 0: Server Mode, Bit 1: Client Mode, Bit 2: DHCP On, Bit 3: Static IP On).
     - Bytes 1–2: UDP Port.
     - Bytes 3–6: Server IP Address.
     - Bytes 7–8: LAN Sharing Port.

2. **Query Static IP Configuration:**
   - **Send:** `FF FF 00 00 00 00 00 00`
   - **Response Payload:**
     - Byte 0: Network mode bitmask.
     - Bytes 1–4: Static IP (Little-Endian).
     - Bytes 5–8: Subnet Mask (Little-Endian).
     - Bytes 9–12: Primary DNS (Little-Endian).

---

# 14. USB Music Rhythm Controller
- **DeviceType:** 45739 | **PID:** `ab b2`

### Parameter Profile (and Telemetry)
- **Byte 0 (Rhythm Algorithm):** `0`: Retain Previous; `1`: Amplitude Envelope; `2`: Frequency Band Division.
- **Byte 1 (Pattern Mode):** `0`: Retain Previous; `1`: Classical; `2`: Rock; `3`: Classical + Random Colors; `4`: Rock + Random Colors.
- **Byte 2 (Rhythm Switch):** Bit 0 = `1`: On; `0`: Off.
- **Bytes 3–4 (Frame Interval):** $100\text{ ms} - 60000\text{ ms}$. Default: $300\text{ ms}$.

---

# 15. Universal In-line Breaker Module
- **DeviceType:** 45733 | **PID:** `a5 b2`

### Configuration Profile

| Byte Offset | Parameter | Description |
| :---: | :--- | :--- |
| Bytes 0–1 | Channel Mask & State | Byte 0: Channel mask; Byte 1: Power output state (`0x0001` = Gang 1). |
| Byte 2 | Mode Configuration | • Bit 0: Trigger Mode (`1` = Edge Triggered, `0` = Latching Level).<br>• Bit 1: Default Logic Level (`1` = Active High, `0` = Active Low). |
| Byte 3 | Pulse Duration | Pulse duration in steps of $100\text{ ms}$ ($0 - 25.5\text{ s}$). |
| Byte 4 | Trigger Conditions | • Bits 0–3: Initial edge change (`1` = High-to-Low, `2` = Low-to-High).<br>• Bits 4–7: External state interlock (`0` = Off, `1` = On, `2` = Any). |
| Byte 5 | State Feedback Source | • Bits 0–3: `0` = Local relay, `1` = External input, `2` = Bound device state.<br>• Bits 4–7: Beacon TX power (`0` = Default, `1` = High, `2` = Med, `3` = Low). |
| Bytes 6–7 | Associated Door Sensor | Short address of bound door sensor. |

---

# 16. Device Categories & Group Control Parent PIDs

When issuing multicast group control commands (Type 13), the following **Parent PIDs** must be specified:

| Category ID | Category Name | Parent PID (Big-Endian Hex) | Parent PID (Little-Endian Hex) |
| :---: | :--- | :---: | :---: |
| `0` | Scenes | None | None |
| `1` | Lighting Fixtures | `2A A8` | `a8 2a` |
| `2` | Motorized Curtains | `EB A9` | `a9 eb` |
| `3` | Relay Switches | `C3 A9` | `a9 c3` |
| `4` | Thermostats / AC / HVAC | `EC AA` | `aa ec` |
| `5` | Gateway Central Hub | Reserved | Reserved |
| `6` | Scene Panels | None | None |
| `7` | Sensors | None | None |
| `8` | Sockets & Power Strips | `95 AC` | `ac 95` |
| `9` | Smart Touch Panels | Reserved | Reserved |
| `10`| Small Home Appliances | None | None |
| `11`| Fresh Air Systems | `EC AA` | `aa ec` |
| `12`| Underfloor Heating | `EC AA` | `aa ec` |