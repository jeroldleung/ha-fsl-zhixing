# Lighting Platform Specification

Home Assistant platform: `light`

All 10 supported lighting types (see [device-catalog.md](./device-catalog.md)) use the standard 6-byte BroadLink lighting control frame:

```text
[Bri/Power, B, R, G, W, C]
```

## Color Mode Mapping

Resolved from `dev_t` / `spid` and `blecatetory`:

| `dev_t` | PID (Hex, LE) | `type_no` | Home Assistant `ColorMode` |
| :---: | :---: | :--- | :--- |
| `43049` | `29 a8` | `332` (`KW_WHITE_LIGHT`) | `ColorMode.BRIGHTNESS` |
| `43051` | `2b a8` | `301`–`306`, `315` (`FAN_LIGHT`) | `ColorMode.COLOR_TEMP` |
| `43168` | `a0 a8` | `352` (`UNIVERSAL_COLOR_LIGHT`) | `ColorMode.RGB` |
| `43050` | `2a a8` | `331` (`KRGBCW_LIGHT`) | `ColorMode.RGBWW` (or `ColorMode.HS` + `ColorMode.COLOR_TEMP` mapped onto the 6-byte `Bri/B/R/G/W/C` frame) |

## Commands & Value Conversions

- **Turn Off:** Send single byte `0x00` (see quirk below).
- **Turn On (Restore):** Send single byte `0x80`.
- **Brightness (`0–255` -> `1–127`):**
  ```text
  Bri_BL = max(1, floor(Bri_HA / 255 * 127))
  ```
- **Color Temperature (`2700 K–6500 K` -> Warm `W` / Cool `C`, where `C + W = 255`):**
  ```text
  C = floor((T_Kelvin - 2700) / (6500 - 2700) * 255)
  W = 255 - C
  ```

## Fade Transitions (Firmware `>= 58`)

When `transition` is provided on `light.turn_on` or `light.turn_off` (and enabled in options):

- Prepend `0x80` for fade-enabled transition.
- Prepend `0x00` for instant change.

## Edge Case: Turn-Off Command Quirk

- **Risk:** Sending six zero bytes (`00 00 00 00 00 00`) fails to turn off lights under the BroadLink protocol.
- **Mitigation:** Always transmit a single byte `0x00` on `light.turn_off` when no transition prefix is applied.

## Edge Case: Type 15 Telemetry Power-State Decoding

- **Risk:** Real FSL/BroadLink lights can report an ON state in Type 15 telemetry with Bit 7 = `0` and non-zero brightness (`0x01–0x7F`, e.g., `0x7F` for 100% ON), whereas checking only `bool(byte0 & 0x80)` misreports them as OFF.
- **Mitigation:** Decode power state as `is_on = bool(byte0 & 0x80) or (byte0 & 0x7F) > 0` (`0x00` is OFF; `0x80` is ON restoring cached brightness).
