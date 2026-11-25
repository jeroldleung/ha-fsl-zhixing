"""Tests for FSL config flow, options flow, and v1->v2 entry migration."""

from unittest.mock import MagicMock, patch

from custom_components.ha_fsl_zhixing import async_migrate_entry
from custom_components.ha_fsl_zhixing.config_flow import CONF_GATEWAY, MANUAL_CHOICE
from custom_components.ha_fsl_zhixing.const import (
    CONF_CLIENT_MAC,
    CONF_FADE_TRANSITION,
    CONF_FILTER_IGNORED,
    CONF_GATEWAY_MAC,
    CONF_POLL_INTERVAL,
    DEFAULT_CLIENT_MAC,
    DEFAULT_UDP_PORT,
    DOMAIN,
    MSG_HEARTBEAT_REQ,
    MSG_PROBE_REQ,
)
from custom_components.ha_fsl_zhixing.transport import parse_mac_bytes
import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_CODE, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.common import MockConfigEntry  # noqa: TID251

from .conftest import GATEWAY_IP, GATEWAY_MAC, MockUdpGateway


@pytest.mark.usefixtures("register_fsl")
async def test_user_discovery_select_gateway(
    hass: HomeAssistant, mock_gateway: MockUdpGateway, mock_session: MagicMock
) -> None:
    """Discover a gateway via Type 1/2 probe and create the entry on selection."""
    with (
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        patch(
            "custom_components.ha_fsl_zhixing.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_GATEWAY: GATEWAY_MAC}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FSL"
    assert result["result"].unique_id == GATEWAY_MAC
    assert result["data"] == {
        CONF_HOST: GATEWAY_IP,
        CONF_PORT: DEFAULT_UDP_PORT,
        CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
        CONF_GATEWAY_MAC: GATEWAY_MAC,
    }
    # Config-flow validation probe uses a distinct MAC; coordinator startup uses client_mac.
    probe_payloads = [payload for _, payload in mock_gateway.received_by_type[MSG_PROBE_REQ]]
    assert len(probe_payloads) >= 3
    assert probe_payloads[1] != parse_mac_bytes(DEFAULT_CLIENT_MAC)
    assert probe_payloads[2] == parse_mac_bytes(DEFAULT_CLIENT_MAC)


@pytest.mark.usefixtures("register_fsl")
async def test_user_discovery_manual_choice(
    hass: HomeAssistant, mock_gateway: MockUdpGateway, mock_session: MagicMock
) -> None:
    """Allow switching from discovered gateways to manual IP/port/MAC entry."""
    with (
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        patch(
            "custom_components.ha_fsl_zhixing.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_GATEWAY: MANUAL_CHOICE}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: GATEWAY_IP,
                CONF_PORT: 51001,
                CONF_CLIENT_MAC: "02-11-22-33-44-55",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: GATEWAY_IP,
        CONF_PORT: 51001,
        CONF_CLIENT_MAC: "02:11:22:33:44:55",
        CONF_GATEWAY_MAC: GATEWAY_MAC,
    }


@pytest.mark.usefixtures("register_fsl")
async def test_no_discovery_falls_back_to_manual(
    hass: HomeAssistant, mock_gateway: MockUdpGateway, mock_session: MagicMock
) -> None:
    """Fall back straight to manual entry when no gateway replies to Type 1."""
    mock_gateway.respond_probe = False
    with (
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        patch(
            "custom_components.ha_fsl_zhixing.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_HOST: GATEWAY_IP, CONF_PORT: DEFAULT_UDP_PORT},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_GATEWAY_MAC] == GATEWAY_MAC
    # Fallback Type 3 during config flow uses a distinct MAC so it does not collide
    # with the configured client_mac used immediately afterward by coordinator.async_start.
    hb_payloads = [payload for _, payload in mock_gateway.received_by_type[MSG_HEARTBEAT_REQ]]
    assert len(hb_payloads) >= 2
    assert hb_payloads[0] != parse_mac_bytes(DEFAULT_CLIENT_MAC)
    assert hb_payloads[1] == parse_mac_bytes(DEFAULT_CLIENT_MAC)


@pytest.mark.usefixtures("register_fsl", "mock_gateway")
async def test_duplicate_mac_aborts_and_updates_ip(hass: HomeAssistant) -> None:
    """Abort duplicate gateway setup while updating changed IP address."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=GATEWAY_MAC,
        data={
            CONF_HOST: "192.168.1.99",
            CONF_PORT: DEFAULT_UDP_PORT,
            CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
            CONF_GATEWAY_MAC: GATEWAY_MAC,
        },
    )
    existing.add_to_hass(hass)

    with patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_GATEWAY: GATEWAY_MAC}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert existing.data[CONF_HOST] == GATEWAY_IP


@pytest.mark.usefixtures("register_fsl")
@pytest.mark.parametrize(
    ("user_data", "drop_hb", "expected_field", "expected_error"),
    [
        pytest.param(
            {
                CONF_HOST: GATEWAY_IP,
                CONF_PORT: DEFAULT_UDP_PORT,
                CONF_CLIENT_MAC: "bad-mac",
            },
            False,
            CONF_CLIENT_MAC,
            "invalid_mac",
            id="invalid-mac",
        ),
        pytest.param(
            {
                CONF_HOST: GATEWAY_IP,
                CONF_PORT: DEFAULT_UDP_PORT,
                CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
            },
            True,
            "base",
            "cannot_connect",
            id="cannot-connect",
        ),
    ],
)
async def test_manual_form_errors_then_recover(
    hass: HomeAssistant,
    mock_gateway: MockUdpGateway,
    mock_session: MagicMock,
    user_data: dict[str, object],
    drop_hb: bool,
    expected_field: str,
    expected_error: str,
) -> None:
    """Display validation and UDP errors without saving, then recover on retry."""
    mock_gateway.respond_probe = False
    mock_gateway.drop_all_heartbeats = drop_hb

    with (
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        patch("custom_components.ha_fsl_zhixing.transport.REQUEST_TIMEOUT", 0.01),
        patch(
            "custom_components.ha_fsl_zhixing.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=user_data
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"
        assert result["errors"] == {expected_field: expected_error}

        mock_gateway.drop_all_heartbeats = False
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: GATEWAY_IP,
                CONF_PORT: DEFAULT_UDP_PORT,
                CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("register_fsl")
async def test_discovery_step_connect_error_and_unexpected(
    hass: HomeAssistant, mock_gateway: MockUdpGateway
) -> None:
    """Surface cannot_connect and unknown errors during gateway selection."""
    mock_gateway.drop_all_heartbeats = True
    with (
        patch("custom_components.ha_fsl_zhixing.transport.DISCOVERY_TIMEOUT", 0.01),
        patch("custom_components.ha_fsl_zhixing.transport.REQUEST_TIMEOUT", 0.01),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        mock_gateway.respond_probe = False
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_GATEWAY: GATEWAY_MAC}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}
        assert len(mock_gateway.received_by_type[MSG_PROBE_REQ]) >= 2

    with patch(
        "custom_components.ha_fsl_zhixing.config_flow.FSLConfigFlow._async_validate_connection",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_GATEWAY: GATEWAY_MAC}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


@pytest.mark.usefixtures("register_fsl")
async def test_reconfigure_flow_success_and_mismatch(
    hass: HomeAssistant,
    mock_gateway: MockUdpGateway,
    mock_session: MagicMock,
    fsl_entry: MockConfigEntry,
) -> None:
    """Allow updating host/port on matching MAC and abort on MAC mismatch."""
    with patch(
        "custom_components.ha_fsl_zhixing.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await fsl_entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: "192.168.1.77",
                CONF_PORT: 51002,
                CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert fsl_entry.data[CONF_HOST] == "192.168.1.77"
    assert fsl_entry.data[CONF_PORT] == 51002

    mock_gateway.mac = "aa:bb:cc:dd:ee:ff"
    mock_gateway.mac_bytes = bytes.fromhex("aabbccddeeff")
    result = await fsl_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: GATEWAY_IP,
            CONF_PORT: DEFAULT_UDP_PORT,
            CONF_CLIENT_MAC: DEFAULT_CLIENT_MAC,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_options_flow(
    hass: HomeAssistant, setup_fsl: MockConfigEntry
) -> None:
    """Update integration options and trigger automatic entry reload."""
    result = await hass.config_entries.options.async_init(setup_fsl.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_FADE_TRANSITION: False,
            CONF_FILTER_IGNORED: False,
            CONF_POLL_INTERVAL: 60,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_fsl.options == {
        CONF_FADE_TRANSITION: False,
        CONF_FILTER_IGNORED: False,
        CONF_POLL_INTERVAL: 60,
    }
    assert setup_fsl.runtime_data.fade_transition is False
    assert setup_fsl.runtime_data.filter_ignored is False
    assert setup_fsl.runtime_data.poll_interval == 60
    # Ignored spotlight (short_addr=10) is included now that filter_ignored=False.
    assert 10 in setup_fsl.runtime_data.data


@pytest.mark.parametrize(
    ("version", "data", "expected_result", "expected_version"),
    [
        pytest.param(1, {CONF_CODE: "legacy-cloud"}, False, 1, id="v1-cloud-unmigratable"),
        pytest.param(1, {CONF_HOST: GATEWAY_IP}, True, 2, id="v1-local-migrates"),
        pytest.param(3, {CONF_HOST: GATEWAY_IP}, False, 3, id="future-version-rejected"),
    ],
)
async def test_migrate_entry(
    hass: HomeAssistant,
    version: int,
    data: dict[str, object],
    expected_result: bool,
    expected_version: int,
) -> None:
    """Handle v1 cloud rejection, v1->v2 local migration, and unknown versions."""
    entry = MockConfigEntry(domain=DOMAIN, version=version, data=data)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is expected_result
    assert entry.version == expected_version
