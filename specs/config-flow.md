# Configuration & Options Flow

Component file: `custom_components/ha_fsl_zhixing/config_flow.py`

## Setup Flow

- **Integration Branding:** Appears in Home Assistant's *Add Integration* menu as **FSL** (`domain: "fsl"`).
- **Auto-Discovery:** Broadcast UDP Type 1 Probe Requests on the local subnet (`255.255.255.255`) during setup and list discovered FSL gateways by MAC address and IP (from Type 2 responses).
- **Manual Entry:** Allow manual configuration of:
  - Gateway IP address
  - UDP port (default: `51000`)
  - Custom 6-byte Client MAC identifier (auto-generated if omitted)
- **Connection Validation:** Validate gateway reachability and retrieve the gateway MAC using a derived locally-administered probe MAC (unicast Type 1 Probe first, falling back to Type 3 Heartbeat on timeout) so config-flow validation never binds the configured `client_mac` to a closed ephemeral UDP port immediately before coordinator startup.

## Options Flow

Allow users to configure runtime behavior after setup:

- **Polling interval:** Configure periodic Type 17 status polling (or disable).
- **Fade transitions:** Enable or disable smooth transition fading for lights with firmware `>= 58`.
- **Filter ignored devices:** Include or exclude devices marked with `ignoreflag: true` in the gateway manifest.
