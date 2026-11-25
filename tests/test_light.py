"""Tests for the FSL light platform covering all 10 lighting device types."""

from unittest.mock import MagicMock, patch

from custom_components.ha_fsl_zhixing.const import DEFAULT_UDP_PORT, DOMAIN
from custom_components.ha_fsl_zhixing.light import (
    bl_brightness_to_ha,
    ha_brightness_to_bl,
    kelvin_to_wc,
    wc_to_kelvin,
)
import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
)
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from tests.common import MockConfigEntry  # noqa: TID251

from .conftest import (
    GATEWAY_DID,
    MockUdpGateway,
    build_http_response,
    encode_manifest,
    make_spid,
    wrap_http_request,
)


@pytest.mark.parametrize(
    ("type_no", "dev_t", "dev_version", "ble_cat", "expected_modes", "expected_model"),
    [
        pytest.param(
            332, 43049, None, "LIGHT", {ColorMode.BRIGHTNESS}, "White Light (332)", id="332-w"
        ),
        pytest.param(
            301, 43051, "1", "CWLIGHT", {ColorMode.COLOR_TEMP}, "Main Light (301)", id="301-cw"
        ),
        pytest.param(
            302, 43051, "2", "CWLIGHT", {ColorMode.COLOR_TEMP}, "Ceiling Light (302)", id="302-cw"
        ),
        pytest.param(
            303, 43051, "3", "CWLIGHT", {ColorMode.COLOR_TEMP}, "Light Belt (303)", id="303-cw"
        ),
        pytest.param(
            304, 43051, "4", "CWLIGHT", {ColorMode.COLOR_TEMP}, "Down Light (304)", id="304-cw"
        ),
        pytest.param(
            305, 43051, "5", "CWLIGHT", {ColorMode.COLOR_TEMP}, "Magnet Down Light (305)", id="305-cw"
        ),
        pytest.param(
            306,
            43051,
            "6",
            "CWLIGHT",
            {ColorMode.COLOR_TEMP},
            "Magnet Down Light No Floodlight (306)",
            id="306-cw",
        ),
        pytest.param(
            315, 43051, None, "CWLIGHT", {ColorMode.COLOR_TEMP}, "Fan Light (315)", id="315-cw"
        ),
        pytest.param(
            352,
            43168,
            None,
            "RGBLIGHT",
            {ColorMode.RGB},
            "Universal Color Light (352)",
            id="352-rgb",
        ),
        pytest.param(
            331,
            43050,
            None,
            "RGBCWLIGHT",
            {ColorMode.RGB, ColorMode.COLOR_TEMP},
            "RGBCW Light (331)",
            id="331-rgbcw",
        ),
    ],
)
@pytest.mark.usefixtures("register_fsl", "mock_gateway")
async def test_all_10_lighting_types_register(
    hass: HomeAssistant,
    mock_session: MagicMock,
    fsl_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    type_no: int,
    dev_t: int,
    dev_version: str | None,
    ble_cat: str,
    expected_modes: set[ColorMode],
    expected_model: str,
) -> None:
    """Register each of the 10 supported lighting types with expected ColorModes."""
    sdid = f"sdid_{type_no}"
    dev_entry: dict[str, object] = {
        "did": GATEWAY_DID,
        "sdid": sdid,
        "shortaddr": "5",
        "spid": make_spid(dev_t),
        "type_no": type_no,
        "dev_version": dev_version,
        "blecatetory": ble_cat,
        "devname": f"Light {type_no}",
        "room": "Living Room",
        "roomId": 1,
        "version": "4.1.0.2056.58",
        "ignoreflag": False,
    }

    manifest = encode_manifest([dev_entry])
    mock_session.get.return_value = wrap_http_request(build_http_response(manifest))

    with patch("custom_components.ha_fsl_zhixing.async_get_clientsession", return_value=mock_session):
        assert await hass.config_entries.async_setup(fsl_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(f"light.living_room_light_{type_no}")
    assert state is not None
    assert set(state.attributes[ATTR_SUPPORTED_COLOR_MODES]) == expected_modes

    device = device_registry.async_get_device(identifiers={(DOMAIN, sdid)})
    assert device is not None
    assert device.model == expected_model

    await hass.config_entries.async_unload(fsl_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("ha_bri", "expected_bl"),
    [
        pytest.param(1, 1, id="min-non-zero"),
        pytest.param(128, 63, id="mid"),
        pytest.param(255, 127, id="max"),
    ],
)
def test_brightness_conversion(ha_bri: int, expected_bl: int) -> None:
    """Verify HA (0-255) to BroadLink (1-127) brightness scaling."""
    assert ha_brightness_to_bl(ha_bri) == expected_bl


def test_bl_brightness_and_cct_conversions() -> None:
    """Verify BroadLink brightness decode and 2700K-6500K W+C=255 mapping."""
    assert bl_brightness_to_ha(127) == 255
    assert bl_brightness_to_ha(64) == 129
    assert kelvin_to_wc(2700) == (255, 0)
    assert kelvin_to_wc(6500) == (0, 255)
    warm, cool = kelvin_to_wc(4600)
    assert warm + cool == 255
    assert wc_to_kelvin(255, 0) == 2700
    assert wc_to_kelvin(0, 255) == 6500
    assert wc_to_kelvin(0, 0) is None


async def test_light_control_payloads(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Verify 1-byte off/restore, 6-byte BRGWC, FW>=58 transitions, and >255 addr."""
    mock_gateway.control_commands.clear()

    # White light (addr=1): restore on, brightness max, single-byte 0x00 off.
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": "light.living_room_white_bulb"},
        blocking=True,
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": "light.living_room_white_bulb", ATTR_BRIGHTNESS: 255},
        blocking=True,
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {"entity_id": "light.living_room_white_bulb"},
        blocking=True,
    )
    assert mock_gateway.control_commands[:3] == [
        (1, b"\x80"),
        (1, b"\xff\x00\x00\x00\x00\x00"),
        (1, b"\x00"),
    ]
    assert hass.states.get("light.living_room_white_bulb").state == STATE_OFF

    # CW light (addr=2, FW=58): CCT + brightness + transition fade/instant prefixes.
    mock_gateway.control_commands.clear()
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            "entity_id": "light.living_room_main_ceiling",
            ATTR_BRIGHTNESS: 128,
            ATTR_COLOR_TEMP_KELVIN: 6500,
        },
        blocking=True,
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            "entity_id": "light.living_room_main_ceiling",
            ATTR_BRIGHTNESS: 255,
            ATTR_TRANSITION: 1.5,
        },
        blocking=True,
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {"entity_id": "light.living_room_main_ceiling", ATTR_TRANSITION: 0},
        blocking=True,
    )
    assert mock_gateway.control_commands == [
        (2, bytes([0x80 | 63, 0, 0, 0, 0, 255])),
        (2, bytes([0x80, 0xFF, 0, 0, 0, 0, 255])),
        (2, b"\x00\x00"),
    ]

    # RGB light (addr=3): verify [Bri, B, R, G, W, C] channel order.
    mock_gateway.control_commands.clear()
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            "entity_id": "light.bedroom_rgb_strip",
            ATTR_BRIGHTNESS: 255,
            ATTR_RGB_COLOR: (10, 20, 30),
        },
        blocking=True,
    )
    assert mock_gateway.control_commands == [(3, bytes([0xFF, 30, 10, 20, 0, 0]))]

    # Extended RGBCW light (addr=264): switch RGB and CCT modes.
    mock_gateway.control_commands.clear()
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            "entity_id": "light.bedroom_extended_rgbcw_lamp",
            ATTR_RGB_COLOR: (255, 0, 128),
        },
        blocking=True,
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            "entity_id": "light.bedroom_extended_rgbcw_lamp",
            ATTR_COLOR_TEMP_KELVIN: 2700,
        },
        blocking=True,
    )
    assert mock_gateway.control_commands == [
        (264, bytes([0x80, 128, 255, 0, 0, 0])),
        (264, bytes([0x80, 0, 0, 0, 255, 0])),
    ]


async def test_telemetry_updates_light_states(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Update HA light states from standard and extended Type 15 telemetry reports."""
    mock_gateway.push_telemetry(
        42,
        [
            (1, bytes([0x7F, 0, 0, 0, 0, 0])),
            (2, bytes([0x80 | 64, 0, 0, 0, 255, 0])),
            (3, bytes([0xFF, 30, 10, 20, 0, 0])),
            (264, bytes([0xFF, 0, 0, 0, 0, 255])),
        ],
    )
    await hass.async_block_till_done()

    white = hass.states.get("light.living_room_white_bulb")
    assert white.state == STATE_ON
    assert white.attributes[ATTR_BRIGHTNESS] == 255

    ceiling = hass.states.get("light.living_room_main_ceiling")
    assert ceiling.state == STATE_ON
    assert ceiling.attributes[ATTR_COLOR_TEMP_KELVIN] == 2700

    rgb = hass.states.get("light.bedroom_rgb_strip")
    assert rgb.state == STATE_ON
    assert rgb.attributes[ATTR_RGB_COLOR] == (10, 20, 30)

    ext = hass.states.get("light.bedroom_extended_rgbcw_lamp")
    assert ext.state == STATE_ON
    assert ext.attributes[ATTR_COLOR_MODE] == ColorMode.COLOR_TEMP
    assert ext.attributes[ATTR_COLOR_TEMP_KELVIN] == 6500

    mock_gateway.push_telemetry(
        43,
        [
            (264, bytes([0xFF, 200, 100, 50, 0, 0])),
            (1, b"\x00"),
        ],
    )
    await hass.async_block_till_done()

    ext_rgb = hass.states.get("light.bedroom_extended_rgbcw_lamp")
    assert ext_rgb.attributes[ATTR_COLOR_MODE] == ColorMode.RGB
    assert ext_rgb.attributes[ATTR_RGB_COLOR] == (100, 50, 200)
    assert hass.states.get("light.living_room_white_bulb").state == STATE_OFF


async def test_control_timeout_raises_ha_error(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Surface UDP control failure as HomeAssistantError without mutating state."""
    mock_gateway.drop_control = True
    with (
        patch("custom_components.ha_fsl_zhixing.transport.REQUEST_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="Failed to send command"),
    ):
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {"entity_id": "light.living_room_white_bulb"},
            blocking=True,
        )
    assert hass.states.get("light.living_room_white_bulb").state != STATE_ON
    assert mock_gateway.port == DEFAULT_UDP_PORT
