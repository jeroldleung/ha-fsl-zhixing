"""Tests for FSL catalog resolution, manifest sync, Area sync, and polling."""

from unittest.mock import MagicMock, patch

import aiohttp
from custom_components.ha_fsl_zhixing.catalog import (
    parse_firmware_version,
    parse_pid_to_dev_t,
    resolve_light_spec,
)
from custom_components.ha_fsl_zhixing.const import (
    DOMAIN,
    HEARTBEAT_MAX_MISSED,
    MANIFEST_FETCH_MAX_RETRIES,
    POLL_CHUNK_COOLDOWN,
    SERVICE_RELOAD_DEVICES,
)
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from tests.common import MockConfigEntry  # noqa: TID251

from .conftest import (
    GATEWAY_DID,
    GATEWAY_MAC,
    MockUdpGateway,
    build_http_response,
    encode_manifest,
    make_sample_devlist,
    make_spid,
    wrap_http_request,
)


def test_pid_and_firmware_parsers() -> None:
    """Extract Little-Endian dev_t from 16-byte SPID hex strings and FW versions."""
    assert parse_pid_to_dev_t(make_spid(43051)) == 43051
    assert parse_pid_to_dev_t("2ba8") == 43051
    assert parse_pid_to_dev_t("invalid") is None
    assert parse_pid_to_dev_t("00" * 12 + "zzzz" + "0000") is None
    assert parse_firmware_version("4.1.0.2056.58") == 58
    assert parse_firmware_version("v79") == 79
    assert parse_firmware_version("") is None
    assert parse_firmware_version("abc") is None


@pytest.mark.parametrize(
    ("raw_dev", "expected_type_no"),
    [
        pytest.param(
            {"spid": make_spid(43051), "dev_version": "4"},
            304,
            id="cw-dev-version-fallback",
        ),
        pytest.param(
            {"spid": make_spid(43051)},
            315,
            id="cw-spid-only-fallback",
        ),
        pytest.param(
            {"spid": make_spid(43049)},
            332,
            id="white-spid-only",
        ),
        pytest.param(
            {"spid": make_spid(44876), "type_no": 338, "blecatetory": "LIGHT"},
            None,
            id="reject-radar-338",
        ),
        pytest.param(
            {"spid": make_spid(45160), "type_no": 347, "blecatetory": "LIGHT"},
            None,
            id="reject-radar-347",
        ),
        pytest.param(
            {"spid": make_spid(43051), "type_no": 332},
            None,
            id="reject-mismatched-type-and-pid",
        ),
        pytest.param(
            {"spid": make_spid(43051), "blecatetory": "SWITCH"},
            None,
            id="reject-non-light-category",
        ),
    ],
)
def test_resolve_light_spec_filtering(
    raw_dev: dict[str, object], expected_type_no: int | None
) -> None:
    """Match only the 10 supported lighting types and default cleanly via SPID."""
    spec = resolve_light_spec(raw_dev)
    actual_type_no = spec.type_no if spec is not None else None
    assert actual_type_no == expected_type_no


async def test_gateway_and_area_sync(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Sync gateway DeviceInfo, room->Area mapping, and filter unsupported devices."""
    coordinator = setup_fsl.runtime_data
    assert set(coordinator.data) == {1, 2, 3, 264}

    assert area_registry.async_get_area_by_name("Living Room") is not None
    assert area_registry.async_get_area_by_name("Bedroom") is not None
    assert area_registry.async_get_area_by_name("Whole House") is None

    gw_device = device_registry.async_get_device(identifiers={(DOMAIN, GATEWAY_MAC)})
    assert gw_device is not None
    assert gw_device.manufacturer == "FSL"
    assert gw_device.model == "Gateway (325)"
    assert gw_device.name == "FSL Main Gateway"
    assert (dr.CONNECTION_NETWORK_MAC, GATEWAY_MAC) in gw_device.connections

    light_entity = entity_registry.async_get("light.bedroom_extended_rgbcw_lamp")
    assert light_entity is not None
    light_device = device_registry.async_get(light_entity.device_id)
    assert light_device is not None
    assert light_device.via_device_id == gw_device.id
    assert light_device.manufacturer == "FSL"
    assert light_device.model == "RGBCW Light (331)"

    assert hass.states.get("light.living_room_ignored_spotlight") is None
    assert hass.states.get("light.living_room_out_of_scope_radar") is None


@pytest.mark.usefixtures("register_fsl")
async def test_type6_url_retry_success_and_exhaustion(
    hass: HomeAssistant,
    mock_gateway: MockUdpGateway,
    mock_session: MagicMock,
    fsl_entry: MockConfigEntry,
) -> None:
    """Re-issue Type 5 with incremented seq up to 3x on expired Type 6 HTTP URLs."""
    manifest = encode_manifest(make_sample_devlist())
    mock_session.get.side_effect = [
        wrap_http_request(
            build_http_response(
                None,
                status=404,
                error=aiohttp.ClientResponseError(MagicMock(), (), status=404),
            )
        ),
        TimeoutError(),
        wrap_http_request(build_http_response(manifest)),
    ]

    with patch("custom_components.ha_fsl_zhixing.async_get_clientsession", return_value=mock_session):
        assert await hass.config_entries.async_setup(fsl_entry.entry_id)
        await hass.async_block_till_done()

    assert fsl_entry.state is ConfigEntryState.LOADED
    assert mock_session.get.call_count == 3
    urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert len(set(urls)) == 3

    await hass.config_entries.async_unload(fsl_entry.entry_id)
    await hass.async_block_till_done()

    mock_session.get.side_effect = [TimeoutError()] * MANIFEST_FETCH_MAX_RETRIES
    with patch("custom_components.ha_fsl_zhixing.async_get_clientsession", return_value=mock_session):
        assert await hass.config_entries.async_setup(fsl_entry.entry_id) is False
        await hass.async_block_till_done()
    assert fsl_entry.state is ConfigEntryState.SETUP_RETRY


async def test_rate_limited_type17_chunk_cooldown(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Enforce 1.5s cooldown between consecutive 104-device Type 17 poll chunks."""
    mock_gateway.status_triggers.clear()
    coordinator = setup_fsl.runtime_data
    addrs = list(range(1, 121))

    with patch("custom_components.ha_fsl_zhixing.coordinator.asyncio.sleep") as mock_sleep:
        await coordinator.async_poll_device_statuses(addrs)

    assert len(mock_gateway.status_triggers) == 2
    assert mock_gateway.status_triggers[0][1] == 1
    assert mock_gateway.status_triggers[1][1] == 105
    mock_sleep.assert_called_once_with(POLL_CHUNK_COOLDOWN)


async def test_two_round_status_poll_retries_missing_devices(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Use delay_max=7 on round 1 and retry only missing short_addrs with delay_max=31."""
    mock_gateway.status_triggers.clear()
    coordinator = setup_fsl.runtime_data

    with (
        patch("custom_components.ha_fsl_zhixing.coordinator.POLL_ROUND1_WAIT", 0.02),
        patch("custom_components.ha_fsl_zhixing.coordinator.POLL_ROUND2_WAIT", 0.02),
    ):
        await coordinator.async_poll_device_statuses([1, 2], schedule_retry=True)
        # Only device 1 responds in round 1; device 2 is missing.
        mock_gateway.push_telemetry(901, [(1, bytes([0x7F, 0, 0, 0, 0, 0]))])
        assert coordinator._poll_followup_task is not None  # noqa: SLF001
        await coordinator._poll_followup_task  # noqa: SLF001

    assert len(mock_gateway.status_triggers) == 2
    # Round 1: delay_max=7, start_addr=1, mask bit0+bit1 (0x03)
    assert mock_gateway.status_triggers[0][0] == 7
    assert mock_gateway.status_triggers[0][1] == 1
    assert mock_gateway.status_triggers[0][2][0] == 0x03
    # Round 2: delay_max=31, start_addr=2, mask bit0 (0x01)
    assert mock_gateway.status_triggers[1][0] == 31
    assert mock_gateway.status_triggers[1][1] == 2
    assert mock_gateway.status_triggers[1][2][0] == 0x01


async def test_reload_devices_service(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_session: MagicMock,
    area_registry: ar.AreaRegistry,
) -> None:
    """Reload manifest via ha_fsl_zhixing.reload_devices and register newly added lights."""
    updated_devlist = [
        *make_sample_devlist(),
        {
            "did": GATEWAY_DID,
            "sdid": "sdid_kitchen_belt",
            "shortaddr": "4",
            "spid": make_spid(43051),
            "type_no": 303,
            "dev_version": "3",
            "blecatetory": "CWLIGHT",
            "devname": "Kitchen Belt",
            "room": "Kitchen",
            "roomId": 3,
            "version": "4.1.0.2056.58",
            "ignoreflag": False,
        },
    ]
    updated_manifest = encode_manifest(
        updated_devlist,
        roomlist=[
            {"roomId": 0, "roomName": "Whole House"},
            {"roomId": 1, "roomName": "Living Room"},
            {"roomId": 2, "roomName": "Bedroom"},
            {"roomId": 3, "roomName": "Kitchen"},
        ],
    )
    mock_session.get.return_value = wrap_http_request(
        build_http_response(updated_manifest)
    )

    assert hass.states.get("light.kitchen_kitchen_belt") is None
    await hass.services.async_call(
        DOMAIN, SERVICE_RELOAD_DEVICES, {"entry_id": setup_fsl.entry_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get("light.kitchen_kitchen_belt") is not None
    assert area_registry.async_get_area_by_name("Kitchen") is not None

    await hass.services.async_call(DOMAIN, SERVICE_RELOAD_DEVICES, blocking=True)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_RELOAD_DEVICES, {"entry_id": "nonexistent"}, blocking=True
        )

    mock_session.get.side_effect = [TimeoutError()] * MANIFEST_FETCH_MAX_RETRIES
    with pytest.raises(HomeAssistantError, match="Failed to reload FSL devices"):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD_DEVICES, blocking=True)


async def test_availability_watchdog_marks_lights_unavailable_and_recovers(
    hass: HomeAssistant,
    setup_fsl: MockConfigEntry,
    mock_gateway: MockUdpGateway,
) -> None:
    """Transition lights to unavailable after 5 missed heartbeats and recover cleanly."""
    coordinator = setup_fsl.runtime_data
    mock_gateway.push_telemetry(10, [(1, b"\x80\x00\x00\x00\x00\x00")])
    await hass.async_block_till_done()
    assert hass.states.get("light.living_room_white_bulb").state == "on"

    mock_gateway.drop_all_heartbeats = True
    with (
        patch("custom_components.ha_fsl_zhixing.transport.REQUEST_TIMEOUT", 0.01),
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
    ):
        for _ in range(HEARTBEAT_MAX_MISSED):
            await coordinator.client.async_heartbeat_tick()
        await hass.async_block_till_done()

        assert hass.states.get("light.living_room_white_bulb").state == STATE_UNAVAILABLE

        mock_gateway.drop_all_heartbeats = False
        mock_gateway.status_triggers.clear()
        await coordinator.client.async_heartbeat_tick()
        await hass.async_block_till_done()

    assert hass.states.get("light.living_room_white_bulb").state == "on"
    assert len(mock_gateway.status_triggers) >= 1
