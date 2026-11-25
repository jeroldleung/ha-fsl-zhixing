# Manifest & Area Synchronization

Capability: fetch gateway topology metadata, decode device/room lists, and synchronize Home Assistant Areas and device inventory.

## Sync Flow (Type 5 / Type 6)

Triggered on initial connection and manually via the `fsl.reload_devices` service:

1. Send **Type 5** over UDP to request the gateway configuration URL.
2. Receive **Type 6** containing a single-use ephemeral HTTP URL.
3. Immediately perform an HTTP `GET` to download the JSON manifest.
4. Base64-decode `devlist` and `familyInfo` from the manifest payload.
5. Map `roomlist` entries in `familyInfo` to Home Assistant **Areas**.
6. Register/update the parent gateway and supported lighting sub-devices (see [device-catalog.md](./device-catalog.md) and [brand.md](./brand.md)).

## Edge Case: Single-Use Config URL Expiration

- **Risk:** The Type 6 HTTP URL becomes invalid immediately after a single HTTP `GET` or after a short timeout.
- **Mitigation:**
  - Issue the HTTP `GET` immediately upon receiving Type 6.
  - If the download fails (timeout, HTTP 403/404, or invalid payload), re-issue a fresh Type 5 request with an incremented `seq` for up to **3 retries**.
