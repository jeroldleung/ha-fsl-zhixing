# FSL Smart Lighting for Home Assistant

Local-first Home Assistant custom integration for **FSL** smart lights connected through a FSL BLE Gateway over LAN UDP.

## Prerequisites

- An FSL BLE Gateway on the same local network as Home Assistant with UDP **Server Mode** enabled.
- Your gateway's local IP address and UDP port (default: `51000`).

## Installation

1. Download or clone this repository.
2. Copy the `custom_components/ha_fsl_zhixing` directory into your Home Assistant configuration directory:

   ```text
   <HA config>/custom_components/ha_fsl_zhixing/
   ```

   For example:

   ```bash
   cp -r custom_components/ha_fsl_zhixing /path/to/homeassistant/config/custom_components/ha_fsl_zhixing
   ```

3. Restart Home Assistant.

## Configuration

1. In Home Assistant, go to **Settings → Devices & Services → Add Integration**.
2. Search for **FSL** and select it.
3. Choose a discovered gateway from the list, or select **Enter gateway manually** (this form opens automatically if no gateway is discovered via LAN broadcast):
   - **Host**: Local IP address of your FSL gateway (e.g. `192.168.1.50`).
   - **UDP port**: Gateway UDP Server Mode port (default: `51000`).
   - **Client MAC address** *(optional)*: 6-byte hex MAC identifier used by Home Assistant (default: `02:00:00:00:00:54`).
4. Click **Submit**. Home Assistant will connect to the gateway, import your rooms and supported lights, and poll their initial states.

## Options & Services

- **Options** (**Settings → Devices & Services → FSL → Configure**):
  - **Enable smooth fade transitions (FW >= 58)**: Toggle firmware fade transitions on supported lights.
  - **Filter ignored devices**: Exclude devices marked as ignored in the gateway manifest.
  - **Status polling interval**: Periodic status poll interval in seconds (`0` to disable, or `30`–`86400`).
- **Reload devices**: Call the `fsl.reload_devices` action in **Developer Tools → Actions** after adding or renaming lights in the gateway.
