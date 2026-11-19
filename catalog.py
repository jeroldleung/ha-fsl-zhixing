"""Device catalog and manifest parsing for the FSL integration."""

from dataclasses import dataclass
import json
from typing import Any

from homeassistant.components.light import ColorMode

from .const import MAX_KELVIN, MIN_KELVIN


@dataclass(frozen=True, slots=True)
class FSLLightSpec:
    """Static capability specification for a supported FSL lighting type."""

    type_no: int
    dev_t: int
    category: str
    model: str
    lighting_class: str
    supported_color_modes: frozenset[ColorMode]
    dev_version: str | None = None


@dataclass(slots=True)
class FSLGatewayInfo:
    """Metadata for the connected FSL parent gateway."""

    mac: str
    ip: str
    port: int
    did: str = ""
    name: str = "FSL Gateway"
    model: str = "Gateway"
    dev_t: int | None = None
    version: str = ""


@dataclass(slots=True)
class FSLLightDevice:
    """Runtime descriptor for a supported FSL lighting sub-device."""

    did: str
    sdid: str
    short_addr: int
    spid: str
    dev_t: int
    type_no: int
    dev_version: str | None
    ble_category: str
    name: str
    room_id: int
    room_name: str
    version: str
    fw_version: int | None
    ignore_flag: bool
    spec: FSLLightSpec


@dataclass(slots=True)
class FSLLightState:
    """Cached lighting state decoded from Type 15 reports or optimistic writes."""

    is_on: bool
    brightness_ha: int | None = None
    color_temp_kelvin: int | None = None
    rgb_color: tuple[int, int, int] | None = None
    color_mode: ColorMode | None = None


GATEWAY_SPECS_BY_DEV_T: dict[int, tuple[int, str]] = {
    43500: (325, "Gateway"),
    44602: (333, "Wire Gateway"),
    44862: (345, "4G Wi-Fi Router"),
}
GATEWAY_TYPE_NOS: frozenset[int] = frozenset({325, 333, 345})

LIGHT_SPECS: tuple[FSLLightSpec, ...] = (
    FSLLightSpec(
        type_no=332,
        dev_t=43049,
        category="KW_WHITE_LIGHT",
        model="White Light (332)",
        lighting_class="W",
        supported_color_modes=frozenset({ColorMode.BRIGHTNESS}),
    ),
    FSLLightSpec(
        type_no=301,
        dev_t=43051,
        category="MAIN_LIGHT",
        model="Main Light (301)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="1",
    ),
    FSLLightSpec(
        type_no=302,
        dev_t=43051,
        category="CEILING_LIGHT",
        model="Ceiling Light (302)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="2",
    ),
    FSLLightSpec(
        type_no=303,
        dev_t=43051,
        category="LIGHT_BELT",
        model="Light Belt (303)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="3",
    ),
    FSLLightSpec(
        type_no=304,
        dev_t=43051,
        category="DOWN_LIGHT",
        model="Down Light (304)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="4",
    ),
    FSLLightSpec(
        type_no=305,
        dev_t=43051,
        category="MAGNET_DOWN_LIGHT",
        model="Magnet Down Light (305)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="5",
    ),
    FSLLightSpec(
        type_no=306,
        dev_t=43051,
        category="MAGNET_DOWN_LIGHT_NO_FLOODLIGHT",
        model="Magnet Down Light No Floodlight (306)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
        dev_version="6",
    ),
    FSLLightSpec(
        type_no=315,
        dev_t=43051,
        category="FAN_LIGHT",
        model="Fan Light (315)",
        lighting_class="CW",
        supported_color_modes=frozenset({ColorMode.COLOR_TEMP}),
    ),
    FSLLightSpec(
        type_no=352,
        dev_t=43168,
        category="UNIVERSAL_COLOR_LIGHT",
        model="Universal Color Light (352)",
        lighting_class="RGB",
        supported_color_modes=frozenset({ColorMode.RGB}),
    ),
    FSLLightSpec(
        type_no=331,
        dev_t=43050,
        category="KRGBCW_LIGHT",
        model="RGBCW Light (331)",
        lighting_class="RGBCW",
        supported_color_modes=frozenset({ColorMode.RGB, ColorMode.COLOR_TEMP}),
    ),
)

LIGHT_SPEC_BY_TYPE_NO: dict[int, FSLLightSpec] = {
    spec.type_no: spec for spec in LIGHT_SPECS
}
CW_SPEC_BY_DEV_VERSION: dict[str, FSLLightSpec] = {
    spec.dev_version: spec for spec in LIGHT_SPECS if spec.dev_version is not None
}
DEFAULT_LIGHT_SPEC_BY_DEV_T: dict[int, FSLLightSpec] = {
    43049: LIGHT_SPEC_BY_TYPE_NO[332],
    43051: LIGHT_SPEC_BY_TYPE_NO[315],
    43168: LIGHT_SPEC_BY_TYPE_NO[352],
    43050: LIGHT_SPEC_BY_TYPE_NO[331],
}


def parse_pid_to_dev_t(pid_hex: str | None) -> int | None:
    """Extract the Little-Endian uint16 dev_t from a BroadLink PID/SPID hex string."""
    if not isinstance(pid_hex, str):
        return None
    cleaned = pid_hex.replace(" ", "").strip()
    if len(cleaned) == 32:
        le_hex = cleaned[24:28]
    elif len(cleaned) == 4:
        le_hex = cleaned
    else:
        return None
    try:
        raw = bytes.fromhex(le_hex)
    except ValueError:
        return None
    return int.from_bytes(raw, "little")


def parse_firmware_version(version_str: str | None) -> int | None:
    """Parse trailing integer firmware version from strings like '4.1.0.2056.58'."""
    if not isinstance(version_str, str):
        return None
    cleaned = version_str.strip().lstrip("vV")
    if not cleaned:
        return None
    tail = cleaned.split(".")[-1]
    try:
        return int(tail)
    except ValueError:
        return None


def _extract_extend_info(raw_dev: dict[str, Any]) -> dict[str, Any]:
    """Parse optional JSON extendInfo dict safely."""
    extend_info = raw_dev.get("extendInfo")
    if isinstance(extend_info, dict):
        return extend_info
    if isinstance(extend_info, str) and extend_info.strip():
        try:
            parsed = json.loads(extend_info)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _coerce_int(value: Any) -> int | None:
    """Convert an integer or numeric string to int, returning None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_str(value: Any) -> str | None:
    """Convert a non-empty scalar to a stripped string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_light_spec(raw_dev: dict[str, Any]) -> FSLLightSpec | None:
    """Resolve a raw devlist entry into one of the 10 supported lighting specs."""
    ble_category = str(raw_dev.get("blecatetory") or raw_dev.get("blecategory") or "")
    if ble_category and "LIGHT" not in ble_category.upper():
        return None

    extend = _extract_extend_info(raw_dev)
    dev_t = parse_pid_to_dev_t(raw_dev.get("spid"))
    if dev_t is None:
        dev_t = _coerce_int(
            raw_dev.get("dev_t") or raw_dev.get("devTypeId") or extend.get("dev_t")
        )
    if dev_t not in DEFAULT_LIGHT_SPEC_BY_DEV_T:
        return None

    type_no = _coerce_int(
        raw_dev.get("type_no")
        or raw_dev.get("devType")
        or extend.get("type_no")
        or extend.get("devType")
    )
    dev_version = _coerce_str(
        raw_dev.get("dev_version")
        or raw_dev.get("devVersion")
        or extend.get("dev_version")
        or extend.get("devVersion")
    )

    if type_no is not None:
        spec = LIGHT_SPEC_BY_TYPE_NO.get(type_no)
        if spec is None or spec.dev_t != dev_t:
            return None
        return spec

    if dev_t == 43051 and dev_version is not None:
        if spec := CW_SPEC_BY_DEV_VERSION.get(dev_version):
            return spec

    return DEFAULT_LIGHT_SPEC_BY_DEV_T[dev_t]


def parse_light_device(
    raw_dev: dict[str, Any],
    room_map: dict[int, str],
    *,
    filter_ignored: bool = True,
) -> FSLLightDevice | None:
    """Parse a raw devlist entry into an FSLLightDevice if supported."""
    if not isinstance(raw_dev, dict):
        return None

    ignore_flag = bool(raw_dev.get("ignoreflag", False))
    if filter_ignored and ignore_flag:
        return None

    short_addr = _coerce_int(raw_dev.get("shortaddr"))
    if short_addr is None or short_addr <= 0:
        return None

    spec = resolve_light_spec(raw_dev)
    if spec is None:
        return None

    sdid = str(raw_dev.get("sdid") or "").strip()
    if not sdid:
        return None

    extend = _extract_extend_info(raw_dev)
    dev_version = (
        _coerce_str(
            raw_dev.get("dev_version")
            or raw_dev.get("devVersion")
            or extend.get("dev_version")
            or extend.get("devVersion")
        )
        or spec.dev_version
    )
    room_id = _coerce_int(raw_dev.get("roomId")) or 0
    room_name = str(raw_dev.get("room") or room_map.get(room_id) or "").strip()
    version = str(raw_dev.get("version") or "").strip()
    ble_category = str(
        raw_dev.get("blecatetory") or raw_dev.get("blecategory") or ""
    ).strip()

    return FSLLightDevice(
        did=str(raw_dev.get("did") or "").strip(),
        sdid=sdid,
        short_addr=short_addr,
        spid=str(raw_dev.get("spid") or "").strip(),
        dev_t=spec.dev_t,
        type_no=spec.type_no,
        dev_version=dev_version,
        ble_category=ble_category,
        name=str(raw_dev.get("devname") or f"FSL Light {short_addr}").strip(),
        room_id=room_id,
        room_name=room_name,
        version=version,
        fw_version=parse_firmware_version(version),
        ignore_flag=ignore_flag,
        spec=spec,
    )


def parse_gateway_device(
    raw_devlist: list[dict[str, Any]],
    *,
    gateway_mac: str,
    host: str,
    port: int,
) -> FSLGatewayInfo:
    """Resolve parent gateway metadata from devlist or fall back to connection info."""
    normalized_mac_hex = gateway_mac.replace(":", "").replace("-", "").lower()

    for item in raw_devlist:
        if not isinstance(item, dict):
            continue
        if item.get("shortaddr") is not None:
            continue
        did = str(item.get("did") or "").strip()
        pid = str(item.get("pid") or "").strip()
        dev_t = parse_pid_to_dev_t(pid)
        ble_cat = str(item.get("blecatetory") or item.get("blecategory") or "").upper()
        type_no = _coerce_int(item.get("type_no") or item.get("devType"))
        is_matching_did = bool(normalized_mac_hex and did.lower().endswith(normalized_mac_hex))
        is_gateway = (
            is_matching_did
            or ble_cat == "GATEWAY"
            or dev_t in GATEWAY_SPECS_BY_DEV_T
            or type_no in GATEWAY_TYPE_NOS
        )
        if not is_gateway:
            continue

        model = "Gateway"
        if dev_t in GATEWAY_SPECS_BY_DEV_T:
            gw_type_no, gw_label = GATEWAY_SPECS_BY_DEV_T[dev_t]
            model = f"{gw_label} ({gw_type_no})"
        return FSLGatewayInfo(
            mac=gateway_mac,
            ip=host,
            port=port,
            did=did,
            name=str(item.get("devname") or "FSL Gateway").strip(),
            model=model,
            dev_t=dev_t,
            version=str(item.get("version") or "").strip(),
        )

    return FSLGatewayInfo(mac=gateway_mac, ip=host, port=port)


def ha_brightness_to_bl(brightness: int) -> int:
    """Convert Home Assistant brightness (0-255) to BroadLink brightness (1-127)."""
    clamped = max(1, min(255, brightness))
    return max(1, (clamped * 127) // 255)


def bl_brightness_to_ha(bri_bl: int) -> int:
    """Convert BroadLink brightness (0-127) to Home Assistant brightness (0-255)."""
    clamped = max(0, min(127, bri_bl))
    return min(255, round(clamped * 255 / 127))


def kelvin_to_wc(kelvin: int) -> tuple[int, int]:
    """Convert Kelvin (2700-6500) to (warm_white, cool_white) channels summing to 255."""
    clamped = max(MIN_KELVIN, min(MAX_KELVIN, kelvin))
    cool = ((clamped - MIN_KELVIN) * 255) // (MAX_KELVIN - MIN_KELVIN)
    warm = 255 - cool
    return warm, cool


def wc_to_kelvin(warm: int, cool: int) -> int | None:
    """Convert (warm_white, cool_white) channel bytes back to Kelvin."""
    total = warm + cool
    if total <= 0:
        return None
    kelvin = MIN_KELVIN + round((cool / total) * (MAX_KELVIN - MIN_KELVIN))
    return max(MIN_KELVIN, min(MAX_KELVIN, kelvin))


def decode_light_state(payload: bytes, spec: FSLLightSpec) -> FSLLightState | None:
    """Decode a BroadLink Type 15 lighting payload into an FSLLightState."""
    if not payload:
        return None

    byte0 = payload[0]
    is_on = bool(byte0 & 0x80)
    bri_bl = byte0 & 0x7F
    brightness_ha = bl_brightness_to_ha(bri_bl) if is_on and bri_bl > 0 else None

    b_val = payload[1] if len(payload) > 1 else 0
    r_val = payload[2] if len(payload) > 2 else 0
    g_val = payload[3] if len(payload) > 3 else 0
    w_val = payload[4] if len(payload) > 4 else 0
    c_val = payload[5] if len(payload) > 5 else 0

    rgb_color: tuple[int, int, int] | None = None
    color_temp_kelvin: int | None = None
    color_mode: ColorMode | None = None

    if spec.lighting_class == "W":
        color_mode = ColorMode.BRIGHTNESS
    elif spec.lighting_class == "CW":
        color_mode = ColorMode.COLOR_TEMP
        color_temp_kelvin = wc_to_kelvin(w_val, c_val)
    elif spec.lighting_class == "RGB":
        color_mode = ColorMode.RGB
        if r_val or g_val or b_val:
            rgb_color = (r_val, g_val, b_val)
    elif spec.lighting_class == "RGBCW":
        if (r_val or g_val or b_val) and not (w_val or c_val):
            color_mode = ColorMode.RGB
            rgb_color = (r_val, g_val, b_val)
        elif w_val or c_val:
            color_mode = ColorMode.COLOR_TEMP
            color_temp_kelvin = wc_to_kelvin(w_val, c_val)

    return FSLLightState(
        is_on=is_on,
        brightness_ha=brightness_ha,
        color_temp_kelvin=color_temp_kelvin,
        rgb_color=rgb_color,
        color_mode=color_mode,
    )
