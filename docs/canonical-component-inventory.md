# ORION canonical component inventory

This inventory is the deployment source of truth for the canonical-architecture migration. A component listed here belongs to ORION Core/runtime unless explicitly marked UI-only.

## DCS integration and runtime boundary

- `dcs-export/Export.lua` — DCS ownship exporter.
- `orion/udp_bridge.py` — local telemetry receiver/validator.
- live telemetry handshake and DCS connection diagnostics.
- active DCS installation / readiness / first-run services.
- Mission Bridge and Mission Pack resources.

## Aircraft layer

### F/A-18C — first acceptance aircraft

Confirmed repository implementation includes dedicated Hornet modules for:

- aircraft knowledge;
- cockpit mapping registry and mapping API;
- cockpit adapter/live state;
- COMM decoding;
- TACAN/COMM semantic systems;
- calibration API/wizard/value profiles;
- automatic mapping progress;
- live validation;
- proactive mapping and readiness notifications;
- live cockpit voice queries.

Production deployment must package these as part of ORION Core/aircraft resources and expose their state through Core. They must not be reimplemented inside the launcher.

### Additional aircraft

Additional aircraft packs, including MiG-21bis work, are deployed only when their current implementation is verified in the repository. The launcher may display their status but does not own their knowledge/state.

## Mission and tactical layer

- unified Mission Context service;
- Tactical Situation Summary / tactical intelligence;
- Mission Control / AWACS runtime;
- proactive Mission Control runtime;
- multi-threat / multi-designator coordination;
- JTAC designation runtime;
- CAS 9-line workflow;
- AAR rendezvous/session/event runtime.

## Virtual ATC

- domain-neutral Virtual ATC Core;
- fixed-airfield Ground/Tower runway operations;
- Ground taxi guidance/navigation;
- controller orchestration;
- departure procedural engine;
- carrier architecture/design work that is already implemented or explicitly marked design-only.

## Voice and AI interaction

- grounded dialogue runtime;
- Voice Core and message scheduling;
- radio/intercom/system lanes;
- Windows audio worker / radio DSP;
- RU/EN voice paths and existing agent personas.

Provider-specific AI adapters must be classified separately as implemented, configured, or unavailable. Launcher presentation must never convert a configured selector into a connected provider state without Core evidence.

## Application-level services

- `orion.app:app` is the canonical Core API/lifecycle surface.
- settings and runtime state;
- diagnostics;
- updater/release services where they belong to product runtime rather than UI presentation.

## UI-only responsibilities

The launcher owns only:

- presentation;
- user input;
- external Core process lifecycle;
- navigation;
- displaying Core-reported health/readiness/state;
- invoking canonical Core operations.

It does **not** own DCS installation truth, launch profiles, telemetry truth, aircraft identity, mission state, ATC state, AI state or readiness state.

## Known architectural debt to remove

1. Embedded `CoreServer` lifecycle inside the desktop launcher.
2. Single frozen `ORION.exe` serving both headless Core and desktop UI roles.
3. Parallel DCS selected-installation and launch-profile state that can disagree.
4. Launcher-local readiness/presentation state that can be mistaken for Core readiness.
5. Packaging that installs one monolithic bundle rather than explicit Core + Launcher product roles.

These items are migration blockers for the canonical deployment and must be removed or reduced to compatibility-only paths before a new user-test installer is produced.
