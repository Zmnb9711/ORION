# ORION Project Memory

> Canonical long-term project context. Updated: 2026-08-13.
>
> Purpose: preserve approved product requirements, architectural invariants, milestone history, real-world test evidence, known risks, and the next agreed action across chats and development sessions.
>
> Precedence: current `main` is the source of truth for implementation. This document is the source of truth for project intent and historical context. When an implementation detail conflicts with this document, verify the latest explicit decision and repository state before changing code.

## 1. Product vision

ORION is an AI copilot, tactical assistant, mission-control and airspace-control layer for DCS World. It is not intended to be only a voice-command utility. The target product should understand aircraft state, cockpit state, mission context, friendly/enemy situation and phase of flight, and use that context to assist the player throughout a mission.

The original inspiration included Wizard-like natural interaction with DCS: ask what is around the aircraft, request actions, run checklists, coordinate supporting units, and interact with the mission by voice. ORION expands this into a maintainable product with persistent mission context, ATC, AWACS/GCI, Mission Control, JTAC/FAC, tanker coordination, aircraft knowledge, cockpit interaction and debriefing.

## 2. Approved top-level requirements

### Aircraft and simulator integration

- DCS World is the primary simulator.
- ORION must receive live DCS state through the supported export/integration layer.
- It must determine the current aircraft and relevant state automatically.
- Support is ultimately required for all supported fixed-wing aircraft and helicopters; individual aircraft may receive deeper knowledge/mapping incrementally.
- F/A-18C is the current primary aircraft used to prove the integration and aircraft-specific path.

### Interaction

- Voice control is a core product capability, but it must not be allowed to destabilize the canonical Core/Launcher/DCS runtime.
- Russian and English are required.
- Structured aviation phraseology and free natural-language interaction are both required.
- Free mode should allow the user to phrase requests naturally rather than memorizing command syntax.
- Casual conversation is approved, including ordinary small talk and occasional/random chatter. Discussion of current/world news was also approved as part of the conversational layer, subject to the availability of current information.

### Virtual ATC

Virtual ATC is a first-class subsystem and should cover the complete flight lifecycle rather than a small collection of canned calls:

- startup/clearance;
- ground/taxi;
- tower/takeoff;
- departure;
- approach/arrival;
- landing;
- emergency/divert/conflict handling;
- airport and carrier operations;
- Russian and English operation;
- strict phraseology plus free-form mode.

Carrier ATC and airport ATC have dedicated architecture/design documents in the repository and should remain consistent with the common ORION runtime.

### AWACS / GCI

Approved capabilities include tactical air-picture support such as:

- BRAA;
- Picture;
- Bogey Dope;
- Declare;
- threat/tactical picture assessment;
- interaction with friendly airborne early-warning/control assets where the mission exposes them.

### Mission Control

Mission Control should maintain mission awareness beyond the player's cockpit. Approved intent includes:

- awareness of friendly/enemy units available to ORION;
- positions and relevant movement;
- tactical/threat assessment;
- route/fuel/weapons recommendations;
- mission-phase continuity;
- coordination with supporting assets.

### JTAC / FAC / allied coordination

The player must be able to request support from friendly ground or airborne units where mission capabilities allow it. Approved functions include:

- target talk-on / targeting assistance;
- laser designation;
- ORION reporting the laser code;
- smoke marking;
- JTAC/FAC workflows;
- CAS / 9-line related workflows;
- attack/BDA-related continuation where supported by mission state.

### Aerial refuelling

ORION should support AAR/tanker interaction. The user must be able to request/refine:

- tanker availability;
- tanker callsign;
- radio frequency;
- TACAN;
- tanker location;
- range/relative position when available;
- coordination of the refuelling workflow.

### Debrief

Post-flight analysis is part of the product scope: mission execution, errors/events and useful recommendations should be available for debriefing.

## 3. Canonical runtime architecture

The architectural direction is a separated runtime, not a monolithic Launcher process.

Canonical flow:

`DCS -> Export.lua / integration -> telemetry transport -> ORION Core -> validated/normalized state and services -> API -> Launcher/UI and higher-level subsystems`

Important invariants:

- Launcher never embeds Core in-process.
- Core remains independently runnable.
- Closing Launcher must not terminate a healthy Core unless explicitly requested by the product design.
- Reopening Launcher should reconnect to the existing Core where appropriate.
- Installer must package the complete canonical runtime and DCS integration resources.
- Mission snapshot persistence must not be rolled back by failure of an optional observer.
- Optional observer failures must be visible in logs.
- `main` plus automated tests/build gates remain the implementation source of truth.

These invariants are also reflected in the #65.5 hardening baseline.

## 4. Launcher / Windows product direction

The Launcher is the user-facing control surface for the real ORION runtime, not a disconnected demo product.

Approved/implemented direction includes:

- Windows installer/portable delivery during alpha development;
- automatic discovery of DCS installation where possible;
- automatic discovery of DCS Saved Games;
- installation/repair of DCS integration;
- start/connect to ORION Core;
- diagnostic/status surfaces;
- capabilities catalog;
- later voice-device setup and testing.

Audio-device design already approved for the voice layer:

- separate microphone and audio-output selection;
- real Windows endpoints;
- `Windows Default` option;
- stable device IDs and display names;
- refresh without restarting;
- microphone test and output test;
- persistence and fallback if a device disappears;
- selected devices must eventually feed real voice input and TTS/WASAPI output.

## 5. Development history and major decisions

### Early project phase — 2026-08-04/05

- Project ORION was defined as an AI assistant/dispatcher for DCS.
- Core requirements established: DCS integration, aircraft-state recognition, voice interaction, real-time assistance and post-flight analysis.
- Scope expanded to a persistent Virtual ATC / Mission Control system.
- Support for all aircraft and helicopters was explicitly required.
- Russian/English ATC, free-form interaction and casual conversation were approved.
- Mission-level awareness, target designation, tanker coordination and AWACS integration were approved.
- GitHub repository `Zmnb9711/ORION` became the development repository.

### Functional expansion

The project accumulated dedicated architecture/design work for airport ATC, carrier ATC, aircraft knowledge, Mission Pack, Mission Control and related runtime components. Product scope was deliberately broad, but implementation was to proceed in controlled milestones rather than attempting all features at once.

### PR #65 / #65.5 decision — 2026-08-09/10

A repository/code audit found the project generally substantive rather than placeholder code, but identified hardening risks including broad exception handling, dependency/static-analysis gaps, Windows/Lua CI gaps, legacy/duplicate desktop paths and runtime robustness concerns.

Decision:

1. Finish #65 first.
2. Run regression/audit.
3. Make #65.5 hardening/cleanup mandatory before resuming new product functionality.
4. Continue to the next ATC/product milestone only after the hardened baseline is green.

The #65.5 document on `main` records the hardening contract: classify broad catches, inventory legacy/dead code, expand Pyright/Ruff carefully, preserve runtime invariants, keep coverage >=80%, and avoid mixing new product features into the cleanup.

### Launcher reconstruction / Alpha path

Launcher/Core deployment became the immediate priority because the product needed a trustworthy Windows entry point and canonical runtime before further feature expansion.

Alpha 0.1 / Launcher V2 established installer/portable and Windows build paths. Later builds improved clean installation, DCS discovery, Core lifecycle and uninstall behavior.

By Alpha 0.2 Build #137, the deliberately narrow Windows smoke scope was:

- install ORION;
- launch Launcher/Core;
- discover DCS installation;
- discover Saved Games;
- repair/restore integration;
- receive live F/A-18C telemetry;
- verify Core survives Launcher closure;
- verify Launcher can reconnect.

Explicit exclusion for this smoke pass: voice, microphone, TTS and voice commands. Those remain product requirements, but are deferred until Launcher/Core/DCS connectivity is stable.

## 6. Real Windows/DCS test evidence

### Earlier Alpha evidence

- Build #118 completed a useful clean-install lifecycle including DCS auto-discovery and uninstall while Core was running.
- Build #131 passed CI, Installer Smoke and Windows Build checks.
- Build #137 was supplied for the focused Alpha 0.2 Windows/DCS smoke pass.

### 2026-08-12/13 live telemetry smoke

The user ran DCS in the F/A-18C and later saved the smoke archive after DCS had been closed.

Observed diagnostic evidence:

- Steam DCS installation discovered at `D:\SteamLibrary\steamapps\common\DCSWorld`.
- `Saved Games\DCS` was discovered.
- DCS integration/Export.lua was active.
- ORION received **12,224 telemetry packets** during the session.
- After DCS stopped, the diagnostic state transitioned to stale/degraded rather than crashing.
- The final saved snapshot contained `aircraft_type = null`, `source = null`, and `protocol_version = null`.

Interpretation: the 12,224 packet count proves the DCS -> ORION telemetry path was active. The null aircraft/source/protocol values in the final archive do **not yet prove an F/A-18C identification defect**, because the archive was saved after DCS had closed and the current live state may have been cleared before diagnostics were captured.

## 7. Newly approved diagnostic requirement — 2026-08-13

Do not require unnecessary repeated DCS flights merely to capture an instantaneous diagnostic snapshot. Diagnostics should preserve useful last-known session history so that the user can finish/close DCS and then save the archive.

Add/preserve at least:

- `current_aircraft_type`;
- `last_seen_aircraft_type`;
- last telemetry source;
- last protocol version;
- `last_packet_at`;
- total packet count;
- useful packet-rate statistics (current/last and, where practical, average/max for the session);
- live-session start/end timestamps;
- reason/state transition for disconnect/stale;
- a small bounded/ring-buffer history of important connectivity/state transitions where practical.

Desired post-session diagnostic behavior: after a successful F/A-18C session and DCS shutdown, diagnostics should still be able to say that the last detected aircraft was F/A-18C, how much telemetry was received, when the last packet arrived, and why the connection is now stale/disconnected.

This is the immediate engineering action before asking for another user DCS smoke run.

## 8. Current product capability map

The repository capability catalog currently groups ORION into:

- Flight / aircraft state;
- Virtual ATC;
- AWACS;
- Mission Control;
- allied-unit coordination;
- aerial refuelling;
- navigation;
- combat assistance;
- Debrief;
- conversational modes;
- Mission Pack;
- Flight Console;
- diagnostics;
- voice/audio-device configuration.

This catalog is product intent plus implemented surfaces; it must not be interpreted as proof that every listed capability is production-complete.

## 9. Historical progress estimates

Progress percentages used in chats were planning snapshots, not release guarantees. They changed as architecture and implementation were audited. A representative snapshot around 2026-08-09 estimated Core/API and DCS foundations as the most mature areas, F/A-18C/ATC/Mission Control/JTAC at intermediate maturity, and all-aircraft support/AAR/remaining ATC phases at earlier maturity.

Do not use old percentages as current truth without re-auditing `main` and tests. Prefer evidence: merged code, tests, CI, Windows build and real DCS smoke results.

## 10. Engineering quality rules

- Develop ORION as a maintainable product, not a prototype pile.
- Avoid placeholder/stub functionality being presented as complete.
- Do not add broad `except Exception` catches without a justified boundary-isolation rationale.
- Add focused regression tests before behavior-changing cleanup.
- Avoid repository-wide cosmetic churn during hardening.
- Keep canonical dependencies centralized.
- Maintain CI gates for supported Python versions, coverage, Windows smoke/build paths and Lua validation as defined by the current repository baseline.
- Delete legacy/duplicate implementations only after proving they are unused by imports, packaging, Windows builds and tests.
- New feature work should not be mixed into a hardening-only milestone unless explicitly approved.

## 11. Decision protocol / how to use this memory

When starting a new ORION chat or development session:

1. Read this file first.
2. Inspect current `main`, relevant PRs/issues and current CI before assuming implementation status.
3. Treat explicit user approvals recorded here as requirements unless a later explicit decision supersedes them.
4. Record significant new approvals, rejected alternatives, real-world smoke evidence and milestone transitions here.
5. Keep detailed architecture in dedicated docs/ADRs; this file should remain the cross-session index and narrative memory.
6. Do not silently overwrite history. When a decision changes, record what superseded it and when.

This follows the same durable principle as Architecture Decision Records: preserve not only what was chosen but enough context and rationale for future development sessions to understand why. Dedicated ADR/design documents remain appropriate for single architectural decisions; this Project Memory connects those decisions to product history and current work.

## 12. Current immediate plan

As of 2026-08-13:

1. Improve telemetry diagnostics/history so a useful session record survives DCS shutdown.
2. Build/test that change through the normal CI/Windows Alpha path.
3. Ask for the next F/A-18C smoke run only after the improved diagnostic build is ready.
4. In that smoke, verify live telemetry, aircraft identification/history, Core survival after Launcher closure and Launcher reconnection.
5. Close the Launcher/Core/DCS-connectivity milestone only on real Windows/DCS evidence.
6. Then resume deferred product layers in the agreed sequence rather than mixing them into the current smoke pass.

## 13. Items that must not be forgotten

- ORION is larger than voice commands: ATC + Mission Control + tactical support are core identity.
- All-aircraft/helicopter support remains a long-term requirement.
- F/A-18C is the current proof aircraft, not the final scope.
- Laser designation must include reporting/handling the laser code.
- Smoke designation is required.
- AAR must expose frequency, TACAN and tanker location, not merely say that a tanker exists.
- AWACS integration and tactical picture are required.
- Russian, English and free natural-language modes are required.
- Casual/random conversation is approved.
- Core must remain independent of Launcher.
- Real Windows/DCS smoke evidence outranks optimistic progress estimates.
- Voice/audio work is intentionally outside the current Alpha 0.2 connectivity smoke pass.
- The next user flight should wait until telemetry history diagnostics are improved.
