# Brand & Component Identity

## Integration Metadata

- **Display Name:** `FSL` (shown in Home Assistant's *Add Integration* menu)
- **Domain (`manifest.json`):** `fsl`
- **Component Path:** `custom_components/ha_fsl_zhixing`
- **IoT Class:** `local_push`
- **Target Platform:** Home Assistant (Core / HACS Custom Integration)

## Device Registry Attribution

- Register both the parent **FSL Gateway** and each **lighting sub-device** in the Home Assistant Device Registry.
- Set `manufacturer="FSL"` on the gateway and all child lighting devices.
- Preserve `type_no`, `dev_t`, and `dev_version` as device model/hardware metadata.
- Link every lighting sub-device to its parent FSL Gateway via `via_device`.

## Brand Assets

Include assets structured for `home-assistant/brands` under `custom_components/ha_fsl_zhixing/brand/`:

- `icon.png`
- `logo.png`
