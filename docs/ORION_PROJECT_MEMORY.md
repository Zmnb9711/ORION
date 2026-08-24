# ORION Project Memory

> Canonical long-term project context. Updated: 2026-08-24.
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

### DCS telemetry architecture — audit decision, 2026-08-13

The DCS telemetry audit established that ORION must not treat DCS data as one homogeneous telemetry stream. Four distinct data layers are required:

1. **Generic DCS telemetry** — simulator-level aircraft identity and kinematics that can be normalized across many aircraft: position, altitude, attitude, velocity and related flight state.
2. **Module-dependent generic API** — engines, fuel, mechanical state, payload, RWR/EW, navigation and similar data exposed by DCS APIs but not necessarily with identical completeness/semantics for every full-fidelity module. Preserve raw values when normalization is uncertain and validate per module.
3. **Aircraft-specific cockpit telemetry** — detailed clickable cockpit/device arguments and indications. This is the path to deep Aircraft Knowledge, but it requires a validated adapter/mapping for each aircraft.
4. **Mission World layer** — units, groups, airbases, weapons, events, coalition state, tasks, threats and tactical context. This remains a separate lower-rate mission-state source and must not be mixed blindly into the high-rate player-aircraft telemetry packet.

Approved architecture: **universal normalized telemetry core + specialized aircraft adapters**. F/A-18C is the first deep adapter/proof aircraft; later adapters should follow for other supported modules while generic telemetry continues to provide broad all-aircraft/helicopter coverage.

The target normalized telemetry domains are:

`Identity -> Kinematics -> Airframe -> Propulsion -> Fuel -> Navigation -> Radios -> Payload/Weapons -> Warnings -> EW/RWR -> Sensors -> Cockpit`, with Mission World alongside rather than inside the high-rate aircraft stream.

Important rules from the audit:

- Do not assume that a DCS API function has identical semantics or completeness on every module.
- Do not guess aircraft-specific cockpit argument IDs; mappings must be validated.
- Optional/restricted data must degrade to unavailable/restricted/null and must never break the telemetry loop.
- Multiplayer/server export restrictions must be respected; ORION must not infer data the server denies.
- Raw source values should be retained where normalized meaning is uncertain, allowing later correction without losing evidence.
- Capability reporting should explicitly distinguish available, restricted, unsupported and not-yet-mapped data.
- Generic telemetry and deep F/A-18C integration are complementary, not competing approaches.

At the time of this audit the existing ORION Export.lua was using only a small subset of the available data surface: aircraft identity, latitude/longitude/altitude, heading, vector-derived speed, vertical speed and a small set of Hornet cockpit arguments (COMM selectors, TACAN raw arguments and display brightness). The Core model already had a `fuel_fraction` field, but the exporter was not populating it.

The next telemetry generation is tracked as **Telemetry v0.3**: expand the schema and exporter so the 5,000-packet diagnostic recorder captures materially useful aircraft/system state before the next large F/A-18C smoke run.

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

### Module installation and runtime selection — 2026-08-20

Approved product requirement:

- During ORION installation, the user must be able to choose which optional functional modules are installed and which are omitted.
- The installer should present module selection as checkboxes, with **all available modules selected by default**.
- The Launcher must contain a **Modules** section where the user can choose which installed modules are enabled and allowed to operate at runtime.
- In the Launcher Modules section, **all installed modules are enabled by default**.
- Installation selection and runtime enablement are separate decisions: the installer controls what is present on disk; the Launcher controls what is active in the current ORION runtime.
- A module that is not enabled in the Launcher must not participate in normal ORION runtime/module routing until it is enabled again.

This requirement is part of the long-term modular product design and should be preserved when installer/module management is implemented or revised.

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

### DCS telemetry capability audit / Telemetry v0.3 — 2026-08-13

After proving the live DCS transport path, the project explicitly audited what data DCS can provide versus what ORION was actually collecting. The audit showed a large gap: the transport was working, but the payload represented only a small fraction of the useful aircraft/system state available to ORION.

Decision:

1. Do not spend another substantial F/A-18C user flight merely collecting thousands of minimally informative packets.
2. First expand the normalized telemetry schema and exporter.
3. Combine a broad generic layer with validated aircraft-specific adapters rather than choosing one approach.
4. Keep Mission World as a separate architecture/source.
5. Use the 5,000-packet recorder to validate actual values and module behavior, not assumptions from documentation.
6. Request the next large F/A-18C smoke only after the Telemetry v0.3 tranche has passed CI/Windows build gates.

### Qwen Live field-validated baseline — Build #402, 2026-08-20

**Status: FIELD TEST VALIDATED**

Control point:

- ORION Alpha Windows Build **#402**;
- commit `4e8b49afff0b8f5d1ec1a008f09f79ae08e1a546`.

Live field tests confirmed:

- WebSocket transport is reference-aligned from Build #401 onward;
- playback is reference-aligned FIFO from Build #402 onward;
- field tests pass both without VPN and with VPN;
- the previously observed abrupt disconnects and early Qwen Live failures are resolved;
- `response.audio.done` and `response.done` arrive normally;
- clean WebSocket close is confirmed;
- playback overflow is zero;
- dropped provider audio is zero;
- artificial zero padding is zero;
- speech is subjectively normal;
- VPN increases jitter/starvation, but no longer causes Qwen Live failure or PCM loss.

Known observation / technical debt:

- FIFO backlog can grow significantly in individual tests; approximately 10–11 seconds has been observed.
- This has not been established as a user-facing problem and is not, by itself, a reason to change the working playback path.
- Do not optimize the backlog without separate measurement and regression A/B validation against Build #402.

Baseline freeze: do not change the following without a separately justified change and regression/A-B test against Build #402:

- Qwen WebSocket transport;
- socket runtime semantics;
- shutdown semantics;
- Qwen event flow;
- `server_vad` flow;
- playback FIFO architecture;
- output worker architecture;
- absence of artificial zero padding;
- absence of a drop-oldest playback policy.

Build #402 is the control point for all future Qwen Live work. Future Qwen Live changes must be compared with it and must not regress connection stability, response completion, playback continuity, audio loss, or Stop behavior.

### Qwen activation, ATC routing and deferred VR status overlay — 2026-08-20

Approved interaction contract for the first Qwen/ATC integration:

- Qwen Live must **not** remain continuously active merely because DCS is running. An idle cloud realtime session is unnecessary and uneconomical.
- A single user-assignable button is configured in the Launcher. The existing Launcher Qwen controls otherwise remain unchanged for the first ATC integration.
- The button is a **toggle**, not hold-to-talk: when Qwen is inactive, pressing it starts the Qwen Live session; pressing the same button again ends the session.
- Outside an active DCS mission, a button-started Qwen session exposes **free conversation only**. DCS/Core mission capabilities must not be presented as available when there is no active mission.
- During an active DCS mission, the same Qwen session exposes both **free conversation** and **Core-backed mission interaction**. Requests relevant to ATC and, later, other ORION modules are routed through Core and must use validated mission/telemetry/module state rather than invented simulator facts.
- The first ATC integration should implement and field-test this button/session/context-routing contract before adding a DCS/VR status display. The button behavior may be adjusted after real in-simulator testing if needed.

A future status-display concept was also reviewed, but is explicitly **deferred from the first ATC integration**:

- Desired user-visible states include at least `QWEN READY` when ORION is ready but no cloud Qwen session exists, and `QWEN ON` while the Qwen Live session is active; transitional/error states may be added later if useful.
- The desired display is a small status indicator in the upper-left area of the DCS/VR view and must not require modifying DCS executable code or embedding ORION logic into DCS itself.
- For VR, the preferred future architecture is a **minimal OpenXR API layer that appends an `XrCompositionLayerQuad`** at frame submission, rather than drawing directly into DCS eye/projection render targets.
- The quad should carry only a small transparent status texture and be positioned in view/reference space. ORION Core/Qwen state should reach the overlay through a minimal IPC/shared-state boundary.
- The OpenXR component must remain deliberately small: no Qwen client, ATC logic, HTTP/Python runtime or Core business logic inside the layer.
- Overlay failure must degrade gracefully: it must not stop Qwen, Core or DCS.
- This approach was preferred conceptually because it keeps the DCS projection image untouched and should isolate the indicator better from DCS rendering, Quad Views/foveated rendering and aircraft-specific code. Actual compatibility with the user's OpenXR/Pimax path must be field-tested when this deferred feature is implemented.
- The OpenXR Toolkit approach was used as a design reference for how VR-resident status/UI can participate in the OpenXR pipeline, but ORION should not copy its full rendering architecture for this small indicator.

Decision: **do not implement the QWEN READY/ON VR overlay in the first ATC integration. Preserve the design as a later milestone.**

### SRS/Yandex no-DCS field-validated baseline — 2026-08-24

**Status: FIELD TEST VALIDATED AND ARCHITECTURALLY FROZEN**

Control point:

- commit `1a06a093eb8e9b9efbf2f33793ed84f7e7b40040`;
- subject `Fix SRS radio registration handshake`;
- standalone proof component `reference_tests/yandex_realtime_gui/`;
- detailed decision and protected invariants: ADR-007.

The controlled test ran without DCS. A local SRS Server 2.4.0.0 connected an
official SRS Client as the human participant and YandexRealtimeTester as the
headless AI participant. Both used External AWACS Mode BLUE (`coalition = 2`)
and 251.000 MHz AM with encryption off. The human heard two completed Yandex
answers through the official SRS Client.

Measured evidence: SRS reached `READY` with `radio_registered = True`; 125 UDP
packets produced 78,720 decoded and 216,970 resampled samples; two human
transmissions started and completed; Yandex received 286 input blocks and
completed successful voice responses with first useful audio at approximately
1,187 ms and 985 ms; SRS returned two transmissions / 382 frames. Maximum TX
jitter was 15 ms and 14 ms, cumulative pacing drift 3 ms and 0 ms. Malformed
packets, Opus errors, duplicates, out-of-order packets and sequence gaps were
all zero.

Two collisions and later `bot_tx_collision` drops prove the intentional v0.1
half-duplex collision protection. They are not interpreted as a defect;
barge-in remains a separate future policy.

The root cause immediately preceding success is a protected integration
checkpoint. Initial `SYNC` had omitted `Client.RadioInfo`, so SRS stored a null
radio state and threw `NullReferenceException` in `HandleClientRadioUpdate` on
the following `RADIO_UPDATE`. UDP GUID echo nevertheless caused false `READY`,
while `udp_packets_received` remained zero. The fix requires non-null canonical
radio state in initial `SYNC`, semantically identical state in the later
`RADIO_UPDATE`, and readiness ordered as `matching own server RADIO_UPDATE ->
UDP GUID echo -> READY`.

The canonical model is the SRS 2.4.0 11-slot `PlayerRadioInfoBase`: active
`radios[1]` at 251000000.0 / AM, encryption and retransmit off, secondary
frequency 1.0, other slots disabled, `unitId = 100000`.

Approved architecture: AI Provider and Voice Transport are independent
selections. Qwen/Yandex remain providers; Direct Audio/SRS Radio are
transports. Direct Audio remains the personal assistant/conversation and
fallback path. SRS Radio is the future path for ATC, AWACS/GCI, JTAC, tanker,
wingman and multiplayer radio participation. The reference Tester proves the
transport but its GUI/diagnostic architecture must not be copied wholesale or
imported by production.

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
- a bounded history of important connectivity/state transitions;
- up to **5,000 last validated telemetry packets** for post-session analysis;
- a last-known-good state/session summary so diagnostics remain useful after DCS exits.

Desired post-session diagnostic behavior: after a successful F/A-18C session and DCS shutdown, diagnostics should still be able to say that the last detected aircraft was F/A-18C, how much telemetry was received, when the last packet arrived, why the connection is now stale/disconnected, and expose a sufficiently large validated telemetry sample for detailed analysis.

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

As of 2026-08-24, preserve Qwen Build #402, Yandex Direct Voice and the proven
SRS baseline while proceeding in these explicit stages:

1. Freeze the SRS baseline in project history and complete the read-only
   production integration audit.
2. Implement only production SRS transport v0.1; do not add DCS or ATC logic.
3. Add independent provider and transport selection while preserving Qwen +
   Direct Audio and Yandex + Direct Audio.
4. Field-test production Yandex + SRS without DCS.
5. Add only DCS radio context: aircraft, cockpit radios, frequencies, callsign
   and position.
6. Add `RadioRouter`, then Core-owned durable `FlightContext`.
7. Prove provider-neutral tool calling through SRS with `orion.test.ping`, then
   one safe ATC tool.
8. Implement full Virtual ATC only after each preceding layer is independently
   proven.

The deferred QWEN READY/ON OpenXR overlay remains outside this sequence unless
separately reprioritized.

## 13. Items that must not be forgotten

- ORION is larger than voice commands: ATC + Mission Control + tactical support are core identity.
- All-aircraft/helicopter support remains a long-term requirement.
- F/A-18C is the current proof aircraft and first deep adapter, not the final scope.
- The approved telemetry strategy is **universal normalized core + specialized aircraft adapters**.
- DCS telemetry has distinct generic, module-dependent, aircraft-specific cockpit and Mission World layers; do not collapse them into one undifferentiated stream.
- Mission World remains separate from high-rate player-aircraft telemetry.
- Preserve raw values when DCS/module semantics are uncertain and validate before normalization.
- Respect multiplayer/server export restrictions and represent unavailable/restricted capabilities explicitly.
- Laser designation must include reporting/handling the laser code.
- Smoke designation is required.
- AAR must expose frequency, TACAN and tanker location, not merely say that a tanker exists.
- AWACS integration and tactical picture are required.
- Russian, English and free natural-language modes are required.
- Casual/random conversation is approved.
- Qwen Live is user-activated by a Launcher-assigned toggle button; do not keep an idle cloud realtime session active merely because DCS is running.
- AI Provider (Qwen/Yandex) and Voice Transport (Direct Audio/SRS Radio) are independent selections; never encode SRS as a Yandex-only provider mode.
- Initial SRS `SYNC` must contain non-null canonical `RadioInfo`; matching own server radio confirmation plus UDP readiness is required before `READY`.
- SRS transport is field-proven without DCS; production must not make DCS a prerequisite for basic radio transport.
- Do not import the standalone Tester into production or place ATC/DCS/provider credentials inside the future SRS transport.
- Outside an active mission Qwen exposes free conversation only; in an active mission it additionally gains Core-backed ORION module interaction.
- The QWEN READY/ON VR status indicator is deferred from the first ATC integration; preferred later design is a minimal OpenXR API layer + `XrCompositionLayerQuad` with graceful degradation.
- Installer module selection is user-controlled, with all modules selected by default; Launcher runtime module selection is also user-controlled, with all installed modules enabled by default.
- Core must remain independent of Launcher.
- All user-facing ORION field-test builds must be delivered and validated as
  the complete normal ORION product. The user launches the standard
  `ORION-Launcher.exe`, which controls the standard `ORION-Core.exe` through
  the production installation/layout contract. Stage/Test/Smoke-named
  executables may be created internally for CI validation, but must never be
  delivered as the user field-test artifact. A field-test artifact is accepted
  only after the exact delivered Launcher/Core pair passes an integrated
  Launcher -> Core startup, health, and shutdown smoke with the same filenames
  and relative layout that the user will run.
- Real Windows/DCS smoke evidence outranks optimistic progress estimates.

## 14. AI Voice Session control model — approved 2026-08-24

**Status: APPROVED PRODUCT / ARCHITECTURE INVARIANTS**

This decision generalizes the earlier Qwen-specific activation model. Where an
older decision describes a `QWEN SESSION TOGGLE` or a provider-specific session
lifecycle, the provider-neutral model below supersedes that naming and lifecycle
policy. It does not alter the field-validated provider audio transports or the
protected SRS wire/readiness baseline.

### One provider-neutral, Core-owned realtime session

- The control is named **AI SESSION TOGGLE**. It controls the currently selected
  Core-owned realtime AI session and belongs to neither Qwen nor Yandex.
- HOTAS behavior is a short-press toggle: the first button-down edge changes
  `OFF -> ON`, and the next short press changes `ON -> OFF`. It is not
  hold-to-talk. Preserve the existing assign, change, reset/clear, and current
  binding UI, generalized to the provider-neutral name and state.
- Launcher controls, HOTAS input, and future automatic DCS lifecycle hooks all
  act on the same session. They must not create parallel provider sessions.
  `RealtimeLiveCoordinator` is the single lifecycle and exclusivity authority.
- `START LIVE` and `STOP LIVE` remain available as manual, test, and diagnostic
  controls for that same production session; they are not a separate test-only
  implementation. The Launcher must show actual Core state regardless of
  whether Launcher, HOTAS, or future DCS automation initiated the transition.
- The future normal DCS lifecycle is automatic: valid current mission/telemetry
  authority starts the selected realtime AI session, and mission end stops it.
  A normal user should not need to press `START LIVE`; the buttons remain for
  manual and diagnostic use.
- **AI SESSION TOGGLE** remains the manual override in DCS. Switching it off
  ends only the AI provider session; it does not terminate SRS, DCS, or Core.
  Automatic mission lifecycle logic must retain and respect this manual-off
  state instead of immediately re-enabling the session while the same mission
  remains active.

### SRS PTT and receive behavior are independent of AI session lifecycle

- SRS PTT remains a separate transmission boundary. PTT down/up starts and ends
  one SRS speech transmission; it must not create or destroy the selected AI
  provider session. The provider session stays alive between PTT transmissions.
- SRS listening must not be gated by local PTT. ORION must be able to receive
  relevant radio traffic while the player is silent; for example, a Mayday call
  may update `FlightContext` and ATC state without any local transmission. PTT
  defines transmission boundaries, not radio or AI lifecycle.

### Operational authority boundaries

- SRS is the communications nervous system. DCS telemetry and Mission World are
  the senses. Core-owned `FlightContext` is durable operational memory. The
  selected AI provider supplies language/reasoning. Core and ATC remain the
  controller and authoritative source of operational truth.
- Yandex or Qwen conversational memory is not authoritative `FlightContext` and
  must not replace Core-owned mission, traffic, clearance, or ATC state.

### Protected SRS baseline and current acceptance status

- Preserve the proven SRS readiness sequence exactly: initial `SYNC` contains
  non-null canonical `RadioInfo`; the client receives a matching own server
  `RADIO_UPDATE`; UDP GUID echo then proves the UDP path; only then may the SRS
  transport become `READY`. This checkpoint does not approve any SRS wire,
  radio-model, codec, routing, or readiness change.
- The integrated Stage 4.1 product plus the successful production no-DCS
  SRS/Yandex field run is a **BASELINE CANDIDATE**, not a final baseline. Final
  status requires the Stage 5 evidence to be captured formally and the Stage
  5.1 lifecycle/persistence tranche to be resolved.

### Next proposed tranche: STAGE 5.1 — PERSISTENCE & AI VOICE LIFECYCLE

Stage 5.1 is the next proposed tranche; it is not implemented by this
documentation checkpoint. Its bounded scope is:

- persist normal non-secret Voice configuration across restart;
- securely persist Yandex/API credentials and any SRS credentials that ORION
  genuinely needs across restart;
- rename/generalize the session toggle and expose one common Core-owned state;
- prepare future DCS automatic start/stop hooks without adding DCS radio context;
- retain `START LIVE` / `STOP LIVE` as controls of the same session;
- perform a read-only audit of official SRS Client/Server 2.4.0.0 configuration
  persistence, including why user-visible values may not survive restart.

Non-secret settings belong in normal ORION configuration. Secrets must not be
stored as plaintext in `cloud-voice.json`; Stage 5.1 must evaluate an appropriate
Windows-protected store such as Credential Manager or DPAPI and explicitly
define credential cleanup/preservation behavior during uninstall.

The official SRS applications remain authoritative for radios/frequencies,
AM/FM, encryption, PTT, audio devices, volumes, and ordinary SRS settings.
ORION persists only its own genuinely required integration settings. Stage 5.1
must audit official SRS Client/Server 2.4.0.0 persistence read-only before
assigning ownership or attempting any correction.

## 15. Stage 5.1 persistence and AI voice lifecycle — implemented 2026-08-25

**Status: IMPLEMENTED; LOCAL AUTOMATED SUITES AND FROZEN COMPONENT SMOKES
VALIDATED; EXACT INTEGRATED CI AND CONTROLLED FIELD REGRESSION PENDING. THE
STAGE 4.1 PRODUCT REMAINS A BASELINE CANDIDATE, NOT A FINAL BASELINE.**

This checkpoint implements the bounded Stage 5.1 tranche from section 14. It
does not add DCS radio context, DCS lifecycle automation, ATC behavior, or any
SRS wire/provider/audio changes.

### Persistence ownership and credential lifecycle

- `cloud-voice.json` remains the normal ORION store for non-secret Voice
  configuration: provider, transport, Qwen region/workspace/model, Yandex
  folder ID, ORION's SRS host/port, and the selected SRS Server/Client
  executable paths.
- Audio-device selection remains in `audio-device-selection.json`.
- The existing `qwen-controller-binding.json` filename is retained for backward
  compatibility, but its product meaning is now the provider-neutral **AI
  SESSION TOGGLE** binding.
- Qwen API key, Yandex API key, and the SRS EAM password used by ORION are
  stored as user credentials in Windows Credential Manager under versioned
  ORION target names. They are not written to `cloud-voice.json`, runtime
  status, diagnostics, exception text, or model representations.
- `CLEAR SAVED CREDENTIALS` deletes the three ORION Voice credentials without
  deleting ordinary Voice configuration. Normal uninstall invokes the same
  narrow credential cleanup before deleting ORION runtime files.
- A frozen-product smoke performs an ephemeral Credential Manager write/read/
  delete round trip and verifies that no smoke credential remains and no
  credential value is exposed in its result.

### One common session lifecycle

- Launcher `START LIVE`, `STOP LIVE`, and the HOTAS **AI SESSION TOGGLE** now
  use one `RealtimeSessionController`, one transition lock, and the generic
  `/v1/realtime/live/*` Core API.
- Core `RealtimeLiveCoordinator` remains the single provider/transport
  lifecycle and exclusivity authority. The HOTAS start payload is built from
  the same persisted provider and transport selection as the Launcher Voice
  page, including Yandex + SRS.
- A stopped Core state can start the selected session. Starting, connected,
  streaming, and error states require a stop transition; error is never treated
  as permission to create a second session. UI status continues to come from
  the generic Core status endpoint.
- The future DCS hook seam is deliberately the same generic Core start/stop/
  status contract. No DCS hook is implemented in Stage 5.1. The approved future
  manual-OFF rule is: once the user turns AI off during a mission, automatic
  lifecycle logic must latch that override for that mission epoch and may not
  start AI again until mission end or an explicit manual ON.

### Read-only official SRS 2.4.0.0 persistence audit

- The installed official SRS Server and Client report version 2.4.0.0. The
  official implementation loads Server `server.cfg` relative to its working
  directory; the Client likewise uses its selected/default configuration path
  relative to its working directory when no explicit `-cfg` path is supplied.
- ORION already starts each selected SRS executable with the executable's own
  directory as its working directory. No SRS process-launch correction was
  required. An old `C:\Windows\System32\server.cfg` is consistent with a
  historical launch from that working directory; ORION did not modify or
  remove it.
- The official SRS applications remain authoritative for radios/frequencies,
  modulation, encryption, PTT, audio devices, volumes, client profiles, EAM
  enablement, and SRS Server settings. CONNECT and CONNECT EAM remain explicit
  user actions. ORION persists only its integration host/port, executable paths,
  and ORION's protected EAM credential.
- The SRS protocol, canonical RadioInfo, readiness gate, Opus, resampling,
  routing, transmission boundary, guard, and pacing implementation were not
  changed in this tranche.

### Automated and packaging checkpoint

- The isolated full regression result is 1,194 passed with 80.60% coverage.
  Isolation only avoids the already-running installed Core's UDP port and the
  machine's real DCS Saved Games known folder; it does not replace product code.
- The focused security/lifecycle result is 75 passed. Ruff, compileall, and
  pyright over the changed production scope are clean.
- Frozen Core SRS native smoke confirms libopus 1.6.1 and samplerate 0.2.4 with
  no network or audio device. Frozen Launcher process-control and Credential
  Manager smokes are also offline and leave no external process or credential.
- The normal installer is `ORION-Alpha-0.2-Setup.exe`, 71,576,308 bytes,
  SHA-256 `6518C349973464AF35EC996EE4B2E3D4EBC7B103E5D20AA9C8957E6F53848ABD`.
  The clean Launcher bundle contains neither SRS codec dependencies nor
  official SRS executables; those executables are never bundled by ORION.
- A local exact-layout Launcher-to-Core smoke cannot bind the fixed DCS UDP
  port while the user's already-installed Core remains active. That user
  process was deliberately not stopped. The same exact smoke, including the
  frozen credential round trip, remains a mandatory clean Windows CI gate
  before this checkpoint can be called integrated-automation validated.
