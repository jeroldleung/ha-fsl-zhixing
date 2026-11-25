# Device Catalog & Scope

Current scope is the intersection of [`dev_docs/default_dev_type.csv`](../dev_docs/default_dev_type.csv) and [`dev_docs/broadlink_whole_house_device_functions_and_profile_specification.md`](../dev_docs/broadlink_whole_house_device_functions_and_profile_specification.md): **10 FSL lighting device types** across **4 BroadLink `dev_t` PIDs**.

## Supported Lighting Devices

| `type_no` | Category (`CSV`) | Chinese Name | English Name | `dev_t` | PID (Hex, LE) | `dev_version` | Lighting Class |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
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

### Shared `dev_t` (`43051`) Handling

Seven form factors (`301`–`306` and `315`) share `dev_t = 43051` (`2b a8`) and identical `ColorMode.COLOR_TEMP` control semantics:

- Preserve `type_no` and `dev_version` as device model metadata in the Home Assistant Device Registry.
- Fall back cleanly via `spid` / `dev_t` when `type_no` or `dev_version` is absent.

## Supported Parent Gateways

Gateways act solely as the local UDP bridge and parent `via_device` in the Device Registry:

| `type_no` | Category | `dev_t` |
| :---: | :--- | :---: |
| `325` | `GATEWAY` | `43500` |
| `333` | `WIRE_GATEWAY` | `44602` |
| `345` | `4G_WIFI_ROUTER` | `44862` |

## Out of Scope (Current Version)

- **Radar / Induction Lights:** Microwave induction lights (`338` `LIGHT_INDUCTION` / `44876`, `44956`) and hanging wire lamp panels (`347` `HANGING_WIRE_LAMP_PANEL` / `45160`).
- **Groups & Scenes:** Lighting groups (`grouplist` / Type 13) and scenes (`scenelist` / Type 11); use native Home Assistant groups and scenes instead.
- **Non-Lighting Categories:** Relay switches, composite panels, scene panels, curtains, thermostats/HVAC, standalone sensors, and virtual remotes.
- **Unmatched / Unverified Lights:**
  - BroadLink spec PIDs not in `default_dev_type.csv`: `43169` (`a1 a8` RGBW), `45559` (`f7 b1`), `45408` (`60 b1`), `45161` (`69 b0`).
  - `default_dev_type.csv` lighting rows without a documented BroadLink `dev_t` profile: `335` (`44841`), `348` (`44838`), `349` (`45509`), `350` (`45510`), `351` (`45648`), `356` (`45712`), `357` (`45789`), `361` (`46017`), `362` (`99997`), `363` (`400`), `364` (`46133`).
