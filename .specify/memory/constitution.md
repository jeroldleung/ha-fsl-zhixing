<!--
Sync Impact Report
- Version change: template (unratified) → 1.0.0
- Modified principles:
  - [PRINCIPLE_1_NAME] → I. Local-First, Zero-Cloud Operation (NON-NEGOTIABLE)
  - [PRINCIPLE_2_NAME] → II. Real-Time Push & Resilient Local Session Management
  - [PRINCIPLE_3_NAME] → III. FSL Smart Lighting Focus & Automatic Area Synchronization
  - [PRINCIPLE_4_NAME] → IV. Home Assistant Core Integration Standards
  - [PRINCIPLE_5_NAME] → V. HACS Integration Packaging & Verifiable Quality
- Added sections:
  - Repository Layout & Technical Constraints
  - Development Workflow & Quality Gates
- Removed sections:
  - None
- Follow-up TODOs:
  - None (all template placeholders resolved)
-->

# ha-fsl-zhixing Constitution

## Core Principles

### I. Local-First, Zero-Cloud Operation (NON-NEGOTIABLE)
All device discovery, topology synchronization, lighting control, and state updates MUST operate
exclusively over the local area network (LAN) via UDP (and ephemeral local gateway HTTP manifest
retrieval) through the FASTCON BLE Gateway. The integration MUST declare `"iot_class": "local_push"`
and MUST NOT require cloud accounts, internet connectivity, external APIs, or cloud telemetry at
runtime. All network and protocol I/O MUST be fully asynchronous (`asyncio`, including
`asyncio.DatagramProtocol` and Home Assistant's shared `aiohttp` client session); blocking I/O on
the Home Assistant event loop is strictly prohibited.
*Rationale*: Eliminating cloud dependencies guarantees low-latency (<150 ms) actuation, user
privacy, and uninterrupted smart lighting control during internet outages.

### II. Real-Time Push & Resilient Local Session Management
State updates MUST rely primarily on real-time asynchronous UDP push reports from the FASTCON BLE
Gateway, sending immediate protocol acknowledgements matching the incoming sequence number to
prevent gateway retransmission storms. Active status polling MUST be limited to initial state
hydration, explicit reload actions, or user-configured staggered sweeps bounded to prevent 2.4 GHz
BLE mesh congestion. The UDP transport MUST maintain session liveness through periodic heartbeats,
deduplicate rolling sequence numbers, support extended short addresses (>255 sub-devices), mark
entities `unavailable` after consecutive heartbeat timeouts, and self-heal automatically without
manual user intervention. Every frame MUST strictly obey FASTCON/BroadLink byte-order and payload
invariants (such as single-byte off commands).
*Rationale*: Keeps Home Assistant lighting state responsive and accurate across large BLE meshes
while maintaining unattended recovery across Wi-Fi or router restarts.

### III. FSL Smart Lighting Focus & Automatic Area Synchronization
The integration MUST be branded under **FSL** (`manufacturer="FSL"`, official FSL brand assets) and
focus strictly on FSL smart lighting fixtures bridged via the FASTCON BLE Gateway
(`"integration_type": "hub"`). The parent gateway and every discovered lighting fixture MUST be
registered in the Home Assistant Device Registry with stable unique identifiers, hardware/firmware
metadata, and `via_device` linkage to the parent gateway. Room metadata retrieved from the gateway
manifest MUST synchronize automatically with Home Assistant Areas so lighting devices are placed in
their corresponding areas out of the box, while lighting groups and scenes remain managed natively
by Home Assistant. Only verified FSL lighting profiles with documented protocol mappings MUST be
exposed on the `light` platform; unverified or out-of-scope hardware MUST be safely ignored.
*Rationale*: Preserves a clean, predictable FSL lighting experience that embraces Home Assistant's
native Device, Area, Group, and Scene registries instead of duplicating them.

### IV. Home Assistant Core Integration Standards
Architecture and code MUST conform to the Home Assistant Core Integration Contributor Guidelines
(`https://contributors.home-assistant.io/core/integrations/`) and target the Home Assistant
Integration Quality Scale (Bronze tier mandatory baseline; Silver, Gold, and Platinum practices
adopted incrementally). Setup MUST be UI-driven via `config_flow.py` (supporting LAN broadcast
discovery, manual entry, and an Options Flow) with `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`;
YAML configuration is prohibited. Runtime state MUST be stored on typed `ConfigEntry.runtime_data`
(never ad-hoc `hass.data` dictionaries), coordinated centrally via `coordinator.py`, and cleaned up
completely in `async_unload_entry` without leaking sockets, timers, or listeners. Entities MUST set
`has_entity_name = True`, define deterministic `unique_id` values, keep all user-facing text in
`strings.json` and `translations/`, and raise idiomatic Home Assistant exceptions
(`ConfigEntryNotReady`, `HomeAssistantError`, `ServiceValidationError`).
*Rationale*: Following Home Assistant core conventions ensures forward compatibility with Core
releases, clean entry lifecycles, and a native user experience.

### V. HACS Integration Packaging & Verifiable Quality
The repository MUST conform to HACS Integration Publishing Requirements
(`https://hacs.xyz/docs/publish/integration/`): exactly one integration directory under
`custom_components/<domain>/` whose directory name matches `manifest.json`'s `domain`, a valid root
`hacs.json`, a complete `manifest.json` (`domain`, `name`, `codeowners`, `documentation`,
`issue_tracker`, `iot_class`, `integration_type`, `config_flow`, and SemVer `version`), brand assets
(`icon.png`, `logo.png`), and a user-facing `README.md`. Every change affecting transport framing,
session management, config flows, coordinator synchronization, or lighting entities MUST include
automated `pytest` tests covering both nominal and failure/edge paths, targeting >=90% coverage
with complete Python type annotations. Releases MUST pass HACS validation (`hacs/action`) and Home
Assistant `hassfest` checks with zero errors.
*Rationale*: Guarantees reliable installation and upgrades through HACS while catching protocol,
packaging, and Home Assistant compatibility regressions before release.

## Repository Layout & Technical Constraints

- **Standard HACS + Home Assistant Structure**:
  - `hacs.json` and `README.md` MUST live at the repository root.
  - All runtime integration code MUST reside inside `custom_components/<domain>/` (`__init__.py`,
    `manifest.json`, `config_flow.py`, `const.py`, `coordinator.py`, `transport.py`, `light.py`,
    `strings.json`, `translations/`, `brand/`).
  - Automated tests MUST reside under `tests/` mirroring integration modules (`test_transport.py`,
    `test_config_flow.py`, `test_coordinator.py`, `test_light.py`).
- **Runtime & Dependencies**:
  - Target the Python version and Home Assistant minimum version declared in `pyproject.toml` and
    `hacs.json`.
  - Keep third-party runtime `requirements` empty whenever Python's standard library and Home
    Assistant bundled libraries (`aiohttp`, `voluptuous`) suffice; any added dependency MUST be
    explicitly justified, pinned cleanly, and compatible with Home Assistant's dependency resolver.
- **Operational Budgets**:
  - Local command latency target: <150 ms from Home Assistant service call to UDP dispatch.
  - Heartbeat recovery target: automated reconnection within 90 seconds of gateway availability.
  - Scalability target: support 500+ sub-devices per gateway via extended short addressing and
    chunked, rate-limited Type 17 status polling.

## Development Workflow & Quality Gates

- **Spec-Driven Delivery**: Features and architectural changes MUST be specified and planned against
  this constitution before implementation; any intentional deviation MUST be documented and
  justified in the feature plan's Complexity Tracking table.
- **Automated Verification Gate**: `pytest` MUST pass locally and in CI before merging any code
  change. Protocol codec changes MUST include byte-level round-trip and edge-case unit tests.
- **Static & Packaging Validation**: Code MUST pass type checking, formatting/linting, HACS
  validation, and `hassfest` validation prior to release tagging.
- **Backward-Compatible Evolution**: Breaking changes to `ConfigEntry.data` or `ConfigEntry.options`
  schemas MUST bump the config entry `VERSION` and implement `async_migrate_entry` with graceful
  handling for non-migratable legacy entries.

## Governance

This constitution supersedes all informal practices, ad-hoc scripts, and legacy conventions in the
`ha-fsl-zhixing` repository. Every pull request, specification, implementation plan, and code review
MUST verify compliance with all five Core Principles and both constraint sections above.

**Amendment Procedure**:
1. Propose amendments via a documented PR or `/speckit-constitution` update stating the rationale
   and impact on existing code, specifications, and HACS/Home Assistant compliance.
2. Increment `CONSTITUTION_VERSION` using Semantic Versioning:
   - **MAJOR**: Removing or redefining a Core Principle in a backward-incompatible way.
   - **MINOR**: Adding a new principle or section, or materially expanding mandatory guidance.
   - **PATCH**: Clarifications, wording improvements, typo fixes, or non-semantic refinements.
3. Update `Last Amended` to the ISO date (`YYYY-MM-DD`) of the amendment while preserving the
   original `Ratified` date.
4. Remove the temporary Sync Impact Report HTML comment before committing the final amended
   constitution to the default branch.

**Version**: 1.0.0 | **Ratified**: 2026-11-24 | **Last Amended**: 2026-11-24
