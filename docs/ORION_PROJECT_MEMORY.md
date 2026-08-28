# ORION Project Memory

> Canonical long-term project context. Updated: 2026-08-26.
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

## 16. Stage 5.1 field validation and Stage 6A FlightContext — 2026-08-25

**Status: STAGE 5.1 FIELD-VALIDATED; STAGE 6A IMPLEMENTED, AUTOMATED AND
PACKAGING VALIDATION PASSED.**

### Field-proven SRS/Yandex baseline

- The normal production chain passed in DCS: human microphone -> normal
  official SRS Client -> SRS Server -> ORION SRS transport -> Yandex Realtime
  -> ORION SRS transmission -> official SRS Client/headset.
- F/A-18C COMM1 frequency isolation passed `251.000 AM -> 252.000 AM ->
  251.000 AM`: ORION heard/responded on matching 251 MHz, stopped receiving
  when the human cockpit/client moved to 252 MHz, and resumed after returning
  to 251 MHz.
- The human pilot uses the normal official SRS Client connection and
  cockpit-controlled aircraft radios. The human pilot does **not** use
  External AWACS Mode for normal DCS flying. EAM remains enabled only for
  ORION's external radio endpoint. Preserve this ownership invariant.
- The field evidence contained 16,315 valid telemetry records and consistently
  identified `FA-18C_hornet`; aircraft detection was already working. The gap
  was propagation from Core state into the active conversational AI session.

### Core-owned FlightContext boundary

- The existing `LiveTelemetryStore` remains the single authoritative owner of
  current high-rate player-aircraft telemetry. It now also owns only the
  current receive timestamp/source/protocol and a monotonic in-memory
  generation. It remains ephemeral and retains no additional history.
- `FlightContextService` is the provider- and transport-neutral, read-only Core
  boundary over that existing current store. It exposes only the current
  aircraft type, position, altitude/AGL, heading, true airspeed and vertical
  speed required by Stage 6A. It contains no credentials and does not mix in
  Mission World state.
- Freshness semantics are deterministic: no received Export state is
  `no_dcs`; a current Export heartbeat without a player aircraft is
  `dcs_connected_no_aircraft`; aircraft telemetry no older than five seconds
  is `fresh`; older data is `stale` and its flight values are withheld from AI.
  A heartbeat after leaving the aircraft immediately invalidates the previous
  aircraft rather than waiting for the stale timeout.
- `FA-18C_hornet` is resolved through the generic Aircraft Knowledge profiles
  to `F/A-18C Hornet`; the answer is not a Hornet-specific prompt constant.
  Unknown future DCS types degrade to a sanitized DCS type name.

### Realtime AI context semantics

- One compact semantic FlightContext projection is used by Qwen Direct,
  Yandex Direct and Yandex SRS. Audio transport does not own or interpret it.
  Qwen + SRS remains explicitly unsupported with no fallback.
- The initial provider `session.update` includes the current context. During
  the same live WebSocket/provider session, identity and availability changes
  propagate immediately; kinematic changes are coalesced to at most one update
  per five seconds; an unchanged context refreshes no more often than every 30
  seconds. Realtime conversation/audio sessions are not recreated, so their
  lifecycle and conversational continuity remain intact.
- Provider diagnostics record only bounded/sanitized context state, freshness,
  aircraft type, generation and update count. Exact high-frequency position,
  credentials, audio and encoded payloads are not added to context diagnostics.
- Stage 5.1 manual session semantics remain authoritative: Launcher and HOTAS
  control the same `RealtimeLiveCoordinator` session. Stage 6A does not add
  automatic DCS mission start/stop behavior.

### Read-only SRS radio-context audit and Stage 6B boundary

- Official SRS 2.4.0.0 obtains Hornet state through its DCS Lua exporter. The
  F/A-18C module reads COMM1/COMM2 devices 38/39 and exports frequency,
  modulation, Guard/secondary frequency, volume, encryption state/key, radio
  names, unit identity/ID and position to the official Client over local UDP
  port 9084 at its periodic export cadence.
- The Hornet exporter declares `dcsPtt=false` and `dcsRadioSwitch=false`;
  selected transmission/PTT behavior is completed by official SRS Client
  input/profile logic, not proven solely by the DCS Lua packet.
- UDP 9084 is an internal SRS integration boundary already consumed by the
  official Client, not an approved stable ORION product API. Stage 6B should
  prefer a minimal independent mapping based on public DCS Export interfaces,
  unless a separately documented/supported SRS integration contract is
  established. ORION must not copy GPL SRS production code or ship SRS source
  or assemblies.
- Stage 6A does not implement cockpit radio mapping, RadioRouter, ATC,
  AWACS/GCI/JTAC/Tanker behavior, automatic mission lifecycle or an overlay.
  The field-proven SRS wire/RadioInfo/readiness, Opus, resampler, routing,
  transmission boundary, guard and pacing baseline remains protected.

### Permanent project workflow invariant

- Use one canonical Codex work thread. Historical Codex threads are read-only
  reference. The GitHub repository plus this Project Memory are authoritative
  project state; chat history is not authoritative project state.

### Stage 6A automated and packaging checkpoint

- The isolated full regression result is 1,206 passed with 80.50% coverage;
  the focused DCS/realtime/provider/SRS/security result is 236 passed. Ruff,
  pyright over changed production modules, compileall and diff checks are
  clean. The isolation redirects only the machine-specific DCS Saved Games
  known-folder lookup to a temporary directory.
- Frozen Core native smoke confirms libopus 1.6.1 and samplerate 0.2.4 with no
  network or audio device. The exact delivered Launcher-to-Core layout passed
  the loopback-only integrated smoke, including clean shutdown and the frozen
  Credential Manager round trip; it started no SRS process and left no orphan.
- Canonical Stage 6A artifacts retain the normal product names and layout. The
  installer is `ORION-Alpha-0.2-Setup.exe`, 71,600,109 bytes, SHA-256
  `1573E3B85215DD26F71C1174F0FFC4DF34EF3C364E5077B85DC98A73B7F69FD5`.

## 17. Stage 6A real field quality audit and Stage 6A.1 — 2026-08-25

**Status: STAGE 6A.1 IMPLEMENTED; STAGE 6B NOT STARTED.**

### Real-field result and measured latency

- The Stage 6A F/A-18C field session proved the functional path from DCS
  telemetry through `LiveTelemetryStore` and `FlightContextService` into the
  live realtime AI. Aircraft, heading, altitude, speed-related values and
  coordinates reached the model. SRS voice continued to work.
- Field-quality defects were generic `assistant` identity, ambiguous negative
  speed wording, raw coordinates, only an approximate Afghanistan location,
  off-context answers and severe first-audio latency outliers.
- Seventeen field responses had complete correlatable
  `response.created -> first audio` observations: median 6,784 ms, nearest-rank
  p90 30,282 ms and maximum 36,163 ms. The long delay was after provider
  `response.created` and before provider audio, not in SRS transmission.
- The field evidence showed 25 FlightContext applies and 50 inbound
  `session.updated` events. Repository evidence proves one outbound update per
  apply, but the provider's reason for two inbound events per outbound update
  is not proven because the old diagnostic path did not retain event IDs.

### Proven corrections

- Yandex's old base prompt identified only a generic conversational assistant.
  Qwen used provider-specific ORION wording. Both now share one provider-neutral
  canonical identity: the assistant's name is ORION, and Core is authoritative
  for current DCS facts.
- A canonical composer replaces exactly one marked current FlightContext block.
  Initial and subsequent provider session updates therefore preserve identity
  and behavioral rules without accumulating prompt history or recreating the
  WebSocket conversation.
- The AI-facing view explicitly distinguishes DCS heading in degrees (without
  claiming unproven magnetic semantics), MSL and AGL in feet plus source meters,
  non-negative TAS in knots plus m/s, and signed vertical speed in ft/min plus
  m/s. Positive vertical speed means climb and negative means descent.
- Coordinates use deterministic degrees-and-decimal-minutes hemisphere format.
  There is no licensed/reliable local ORION airfield catalog in this tranche;
  the model is told not to infer country or airfield. Deterministic local
  airfield resolution is deferred to the next dedicated micro-stage.
- Provider sessions keep only the latest pending context and apply it at a safe
  boundary after user speech/pending turn/active response completes. There are
  no arbitrary sleeps and telemetry ownership/cadence remains unchanged.

### Observability and privacy boundary

- Provider-neutral turn state now correlates speech stop, response creation,
  first audio and completion with bounded rolling median/p90/max latency.
  Context diagnostics include state, generation, a non-coordinate semantic
  version, and sent/deferred/coalesced counts. Yandex SRS records the first
  successful TX packet marker without changing transmission behavior.
- An explicitly started Core-only Test Evidence recorder exports
  `ORION-Test-Evidence-<timestamp>.zip` through Core API. Its allowlist excludes
  transcript text, exact coordinates, audio/PCM/Opus/Base64 and credentials.
  It intentionally does not race or copy external DCS/SRS logs. Launcher
  START/STOP buttons and optional explicitly consented richer snapshots remain
  an immediate follow-up.
- The protected DCS Export/UDP 45100, `LiveTelemetryStore`, SRS protocol,
  RadioInfo/readiness, Opus/resampler/routing/400 ms boundary/250 ms guard/40 ms
  pacing/EAM, audio-device, credential and shared-session baselines are
  unchanged. COMM1/COMM2 awareness remains Stage 6B and is not started.

### Stage 6A.1 automated and packaging checkpoint

- The focused realtime/provider/SRS result is 209 passed. The isolated full
  regression result is 1,215 passed with 80.77% branch coverage. Isolation only
  redirects this workstation's real DCS Saved Games known folder to a temporary
  empty directory. Ruff, pyright over changed production modules, compileall,
  security/privacy regressions and diff checks are clean.
- Fresh frozen Core native, Launcher SRS-control, Credential Manager and exact
  Launcher-to-Core loopback smokes passed without physical audio devices,
  external SRS processes or non-loopback networking. No credentials, user logs,
  test evidence or official SRS applications are bundled; Launcher has no
  Core-only Opus/samplerate/numpy runtime.
- The canonical installer is `ORION-Alpha-0.2-Setup.exe`, 71,632,558 bytes,
  SHA-256 `326CFA7CE6765BA165AD9FF63A1A5E1C4EECD3F3B559BD4887E9AAB28FD231C1`.

## 18. Stage 6A.2 test evidence transcripts and Launcher controls — 2026-08-26

**Status: STAGE 6A.2 IMPLEMENTED; STAGE 6B NOT STARTED.**

- The Stage 6A.1 field test passed ORION identity and showed materially improved
  subjective and recorded provider-audio latency. Human observation still found
  incorrect heading (approximately -104 degrees), unnatural speed presentation
  and unnatural coordinate presentation. Those semantics are deliberately not
  changed here; exact utterance evidence is required before the next forensic
  tranche.
- Transcript evidence is enabled only inside an explicitly user-started Test
  Evidence session. Final provider-exposed user transcription and assistant
  audio/text transcription events are correlated with available test session,
  provider, transport, turn, response, provider item, event, context-version and
  timestamp identifiers. Missing provider transcript events remain explicitly
  `NOT OBSERVABLE`; no STT, TTS or additional model is introduced.
- Core remains the sole recorder and export owner. The existing bounded recorder
  and the existing start/status/stop-export Core endpoints are reused. Outside
  an active Test Evidence session, the new transcript path is a no-op and
  production transcript persistence remains disabled.
- Settings places `START TEST SESSION`, `STOP & EXPORT TEST SESSION`, compact
  recorder status and a Windows-native `OPEN EXPORT FOLDER` action beside the
  existing `START LIVE` / `STOP LIVE` controls. Launcher is only an API client;
  refresh reads Core status and duplicate start does not create another owner.
- Raw audio, PCM, Opus, Base64 payloads, provider request bodies, system prompts,
  credentials and unrelated environment data remain excluded. The explicit
  transcript text may naturally contain spoken flight values or coordinates.
- Heading normalization, speed/TAS/vertical-speed semantics, coordinate
  formatting, airfield resolution, FlightContext behavior, SRS, DCS Export,
  RadioContext and RadioRouter remain unchanged. Their forensic correction is
  deferred. Stage 6B and Local Decision/Planner AI have not started.

### Stage 6A.2 automated and packaging checkpoint

- The focused recorder/provider/Launcher/SRS result is 43 passed. The isolated
  full regression result is 1,222 passed with 80.95% branch coverage. Ruff,
  pyright over changed production modules, compileall, privacy/security scans
  and diff checks are clean.
- Frozen Core native, Launcher SRS-control, Credential Manager and exact
  Launcher-to-Core loopback smokes passed without physical audio devices,
  external SRS, DCS or live provider access. The product package contains no
  test evidence, JSONL/log data, credential material or official SRS binaries.
- The Stage 6A.2 installer is `ORION-Alpha-0.2-Setup.exe`, 71,644,218 bytes,
  SHA-256 `5ADD76234D3F66EBB0DA490B9E7A195EE6E96E9B553416597AB4A8E6355F7B56`.

## 19. IA-0 provider-neutral interaction contracts — 2026-08-26

**Status: IA-0 IMPLEMENTED; IA-1 AND STAGE 6B NOT STARTED.**

- IA-0 introduces four provider- and transport-neutral contracts:
  `CapabilityId`, `InteractionRequest`, `RouteDecision` and
  `SemanticResponse`. They are serialization-safe Core/API data shapes only;
  no production interaction flow uses them yet.
- The Core/Planner boundary remains intentionally movable. A future capability
  may use deterministic Core handling or Planner-assisted handling without
  changing provider, transport or domain contracts.
- `SemanticResponse` separates authoritative facts, deterministic derived
  results, recommendations, assumptions, unavailable inputs and warnings. Its
  `NATURALIZE` and `VERBATIM` presentation modes prepare the next approved
  tranche: IA-1 — Yandex Presentation Contract Probe.
- IA-0 adds no World Model, Tool Gateway, PlannerProvider, cloud model adapter,
  RadioContext or RadioRouter. Stage 6B has not started.

## 20. IA-1 Yandex presentation contract probe — 2026-08-26

**Status: IA-1 IMPLEMENTED AND PACKAGED; FIELD VALIDATION PENDING. IA-2 AND
STAGE 6B NOT STARTED.**

- IA-1 consumes the real IA-0 `SemanticResponse` through a bounded
  Yandex-specific adapter in the existing active Realtime WebSocket. It uses
  documented `conversation.item.create` text injection plus explicit
  `response.create` with per-response presentation instructions. IA-0 remains
  provider-neutral; no duplicate semantic schema, World Model, Tool Gateway,
  Planner, RadioContext or RadioRouter was added.
- NATURALIZE supplies already-decided authoritative/derived values,
  recommendation and unavailable status and forbids new domain reasoning.
  Automatic checking is conservative: corruption-sensitive tokens may prove a
  failure, but natural-language equivalence remains `REVIEW_REQUIRED` rather
  than an invented PASS. VERBATIM supplies only the finalized text and records
  exact plus case/punctuation/whitespace-normalized transcript matches. Yandex
  does not document a character-exact speech guarantee.
- Current Yandex documentation verifies session-level voice and SpeechKit-role
  updates inside an active WebSocket and full `session.updated` configuration.
  Per-response voice, Realtime pitch/emotion and speech-rate controls are not
  documented. The probe uses acknowledged `dasha -> alexander -> dasha` voice
  switching and one-voice `julia neutral -> strict -> neutral` style switching,
  then restores `dasha/neutral`. Acoustic identity, deployed session-ID
  stability and audible role behavior require the field test.
- Settings -> Voice contains one compact selector and RUN PRESENTATION PROBE
  action. It accepts only canned synthetic cases, requires a compatible idle
  Yandex session, rejects duplicate runs and returns to ordinary operation.
  FlightContext updates defer while the probe owns the presentation boundary;
  normal PTT, provider audio and the existing Direct/SRS endpoints remain the
  same paths.
- Existing Test Evidence now correlates probe run/case, interaction and
  SemanticResponse IDs; client/provider event IDs; expected synthetic facts;
  final transcript; voice/role request and acknowledgement; session IDs;
  response, first-audio, SRS first-TX and completion timing; interruption; and
  conservative fidelity results. `ia1-summary.json` is added only when a probe
  ran. Raw audio/PCM/Opus/Base64, credentials, provider payloads, system prompt,
  exact DCS coordinates and unrestricted history remain excluded.
- SRS protocol, RadioInfo/readiness, routing, Opus/resampler, 400 ms boundary,
  250 ms guard, 40 ms pacing, EAM and audio routing remain unchanged. The only
  SRS-boundary code change is the already-known provider response ID on the
  bounded TX-complete diagnostic for evidence correlation.
- Focused shared-boundary regression is 78 passed; isolated full regression is
  1,259 passed. Ruff, pyright, compileall, privacy/secret and diff checks are
  clean. Frozen Core native, Launcher SRS-control and exact loopback integrated
  product smokes pass with no external SRS, live provider or physical audio.
- IA-1 installer: `ORION-Alpha-0.2-Setup.exe`, 71,710,461 bytes, SHA-256
  `6773F70F90B8B7F4BF8BB4830B686F666141745921FE62D5317BAAC5F6C47E5B`.
- Presentation Architecture remains provisionally A/B pending the real
  DCS + Yandex + SRS evidence ZIP. Voice Model remains provisionally A/B/C
  pending the same evidence. Do not claim IA-1 PASS before that field test.
  After IA-1 acceptance, the next approved stage is IA-2 — World Model Query
  Facade. Do not begin it automatically.

## 21. IA-1 closure and hybrid presentation decision — 2026-08-26

**Status: IA-1 CLOSED; HYBRID PRESENTATION APPROVED.**

- Final evidence `ORION-Test-Evidence-20260826-193719.zip` completed the ten-case
  A/B probe with 20/20 SRS transmissions, semantic PASS for every arm, 20 bounded
  synthetic WAV artifacts, human acoustic review CLEAR and no duplicate SRS TX.
- A real first-attempt SpeechKit connection timeout recovered through the
  approved bounded retry. Reusable `aiohttp.ClientSession`, bounded transient
  retry, no retry for deterministic 400/401/403, no validation-probe fallback and
  fail-closed critical presentation remain the accepted transport behavior.
- Realtime-only presentation is rejected as the sole critical aviation renderer.
  Yandex Realtime is approved for conversational/noncritical speech; SpeechKit
  TTS for deterministic critical/radio speech. Both feed the unchanged SRS radio
  transport. Planner/provider reasoning remains independent and upstream.
- ADR-004 is historically closed and remains superseded by ADR-005. No normal
  runtime PresentationRouter migration was performed at this checkpoint.

## 22. IA-2 World Model Query Facade — 2026-08-26

**Status: IA-2 IMPLEMENTED AND CODE-VALIDATED; IA-3 NOT STARTED.**

- `WorldModelFacade` is a provider-neutral, read-only projection over existing
  owners. It is not a second store. LiveTelemetryStore, MissionStore, Mission
  Bridge, aircraft adapters/mappings, navigation/coalition indexes and all domain
  state machines retain authority and lifecycle ownership.
- Immutable typed facts carry explicit known/unknown/unavailable/stale/restricted
  status, source, authoritative/observed/derived class, timestamp, age,
  generation, units and typed failure reason. Confidence is limited to uncertain
  observations. Queries make no network/provider/SRS calls and perform no action.
- The minimal surface covers ownship, navigation summary, validated F/A-18C
  systems, mission/bridge identity, bounded mission-truth units, an intentionally
  restricted observed-contact query, and Core-derived range/bearing/vertical
  separation. Closure remains unavailable without reliable aligned velocities.
- Mission truth must never be relabelled as detected/AWACS knowledge. A trusted
  sensor/contact owner and policy are a P0/P1 prerequisite for exposing observed
  tactical contacts.
- Installed official DCS APIs expose independent left/right control surfaces and
  `LoGetAltitude(x,z)`, but current ORION normalization does not export general
  control-surface or terrain-query data. These are ranked gaps, not IA-2 exporter
  changes. Tacview is reference/coverage evidence only: DCS may feed ORION and
  Tacview independently; Tacview never feeds ORION.
- Durable design: `docs/ia-2-world-model-query-facade.md`. Coverage and ranked
  gaps: `docs/orion-data-coverage-matrix.md`.
- The exact next approved stage is **IA-3 Tool Gateway**. Do not begin IA-4,
  Qwen/provider adapters, Router, Stage 6B RadioContext/RadioRouter or domain
  migrations as part of IA-2.

## 23. IA-3 Tool Gateway — 2026-08-26

**Status: IA-3 IMPLEMENTED AND CODE-VALIDATED; IA-4 NOT STARTED.**

- IA-3 adds one Core-owned provider-neutral `ToolGateway` boundary. Future
  provider adapters may translate their calls into `ToolCall` and translate
  `ToolResult` outward, but providers never select policy, expand capabilities
  or call World Model/domain owners directly.
- Immutable contracts cover stable tool/version/schema identities, typed bounded
  arguments/results, `ExecutionContext`, policy, safe errors, provenance,
  lifecycle receipt, deadlines/cancellation and future confirmation/idempotency.
  No provider JSON schema, WebSocket event, MCP, SRS or provider module is
  imported by the Gateway.
- Core policy checks exact registration/version, IA-0 `CapabilityId` allowlist,
  permissions, runtime module state, mission/freshness, confirmation,
  idempotency, deadline and cancellation before a handler. Handler input and
  output are both Pydantic-validated. Exceptions are isolated into stable safe
  errors; bounded diagnostics exclude arguments, results and credentials.
- The initial catalog is read-only: ping, ownship, navigation, mission identity,
  bounded mission-truth units, relative geometry and observed contacts. Every
  world read goes through IA-2. Observed contacts remain explicitly restricted;
  MissionStore truth is never relabelled as detected information.
- `RealtimeToolService` and its Qwen/Virtual-ATC path remain unchanged as a
  legacy prototype to deprecate later. No ATC/JTAC/AAR/mission/radio action is
  migrated or exposed. The existing ConfirmationStore lacks expiry and
  actor/session/tool binding, so future write confirmation fails closed until a
  bound adapter exists.
- Durable design: `docs/ia-3-tool-gateway.md`. A user DCS field test is not
  required for IA-3; the first meaningful live AI/tool validation belongs after
  IA-4/IA-5 and the controlled IA-6 slice.
- The exact next approved stage is **IA-4 PlannerProvider Contract**. Do not
  begin IA-5 Qwen/Yandex adapter work, IA-6 Router, Stage 6B, or domain action
  exposure as part of IA-3.

## 24. IA-4 PlannerProvider Contract — 2026-08-27

**Status: IA-4 IMPLEMENTED AND CODE-VALIDATED; IA-5 NOT STARTED.**

- IA-4 adds a provider-neutral `PlannerProvider` / short-lived `PlannerRun`
  boundary and a small Core-owned task state machine. Core retains interaction
  and task identity, capability/permission policy, deadlines, cancellation,
  tool execution, receipts, replay safety, final-response acceptance and
  diagnostics. Providers receive only bounded task input and a filtered IA-3
  catalog; they never receive World Model/domain ownership or create their own
  `ExecutionContext`.
- The bounded lifecycle supports immediate IA-0 `SemanticResponse`, sequential
  tool rounds and multiple tool calls per round. Calls execute only through IA-3.
  Exact call/event replays reuse completed results without handler execution or
  another tool round; conflicting identity reuse fails closed. No write tool or
  domain action is exposed.
- Core absolute deadline and event-backed cancellation reach the provider wait
  contract and are checked before new tools/continuations. Provider retry policy
  is a future adapter bound, separate from tool retries; IA-4 implements no HTTP
  retry or provider transport.
- A final response must match the interaction/capability policy. Every claimed
  authoritative fact requires a completed cited IA-3 result with authoritative
  IA-2 provenance. Exact semantic value-to-result binding and freshness policy
  remain an explicit IA-6 seam; missing/non-authoritative provenance already
  fails closed.
- Bounded diagnostics contain only lifecycle/correlation scalars. They exclude
  prompts, user text, hidden reasoning, provider payloads, arguments/results,
  credentials and mission state. Provider/Gateway exceptions are normalized and
  redacted.
- A deterministic fake proves the complete read-only vertical path from IA-0
  request through IA-3 and IA-2 back to an accepted SemanticResponse, plus
  lifecycle, replay, deadline, cancellation, failures and privacy. A DCS/provider
  field test is not required.
- Durable design: `docs/ia-4-planner-provider-contract.md`. The exact next
  approved stage is **IA-5 Qwen3.6-35B / Yandex AI Studio Adapter**. Do not begin
  IA-6 Router, Stage 6B or domain action exposure as part of IA-4.

## 25. IA-5 Qwen3.6 / Yandex AI Studio Adapter — 2026-08-27

**Status: IA-5 IMPLEMENTED, LIVE-PROVIDER AND CODE VALIDATED; IA-6 NOT STARTED.**

- IA-5 adds a real non-streaming Yandex AI Studio Responses adapter for
  `gpt://<folder_id>/qwen3.6-35b-a3b` without changing IA-0 through IA-4. It
  uses the existing secure Yandex credential and Folder ID; Realtime Workflow
  ID never enters planner configuration or requests.
- Current official docs and live Gates 1–4 proved auth/model, ordinary response,
  strict structured output, function calling, opaque `previous_response_id`,
  usage, low reasoning and response deletion. Hidden reasoning is ignored and
  never persisted.
- Provider-safe hashed aliases translate Yandex function names back to the exact
  task-filtered IA-3 definitions. Provider JSON becomes IA-4 requests only;
  Core still owns execution context and IA-3 remains the sole executor.
- Core retains complete ToolResults. Qwen receives a bounded WorldFact projection
  preserving values/status/source/authority/freshness, and final JSON must build
  a real IA-0 SemanticResponse accepted again by unchanged IA-4 provenance rules.
- One reusable bounded `aiohttp` session serves a short planner task. Safe
  transient retries are distinct from tool execution; deterministic provider or
  semantic failures fail closed. Every obtained stored response is deleted at
  terminal cleanup.
- Real Gate 6 completed on synthetic state through Qwen -> IA-4 -> IA-3 -> IA-2
  -> ToolResult -> Qwen continuation -> IA-0. No DCS, SRS, audio, Launcher,
  IA-6 Router or Stage 6B work was performed.
- Durable decision: `docs/ia-5-qwen-yandex-ai-studio-adapter.md`. The exact next
  approved stage is **IA-6 Interaction Router + controlled Planner slice**.

## 26. PRE-IA-6 Launcher/Core lifecycle correction — 2026-08-27

**Status: IMPLEMENTED AND CODE-VALIDATED; IA-5 REMAINS COMPLETE; IA-6 IS NEXT.**

- Window close/X continues to hide Launcher to the tray and keeps its Core
  child and runtime sessions alive.
- Explicit tray Exit now gracefully stops only the Core created by that exact
  Launcher. Ownership is the live child process handle plus an unlogged,
  non-persisted random lifecycle token; PID files, executable name/path and port
  ownership are never sufficient.
- Core accepts the token-bound local shutdown request by setting Uvicorn's
  graceful exit flag. Launcher waits boundedly, verifies child exit and telemetry
  UDP release, and uses terminate/kill fallback only while the exact owned child
  handle remains authoritative.
- A compatible Core already healthy before Launcher startup is treated as
  external and is preserved on Exit.
- Validation used isolated temporary HTTP/UDP ports and did not terminate or
  replace the installed Core holding canonical UDP 45100. IA-6 and Stage 6B were
  not started.

## 27. Stage 6B.1 provider-neutral radio boundary — 2026-08-28

**Status: IMPLEMENTED AND CODE-VALIDATED AS AN UNWIRED SLICE; STAGE 6B.2 NOT
STARTED.**

- Immutable `RadioContext`, `RadioEntityRef` and finalized mono PCM16 contracts
  represent one resolved transmission without copying cockpit/World Model state
  or exposing SRS GUID, RadioInfo, radio index, UDP registration, provider
  configuration, credentials or phraseology.
- The Core-owned `RadioRouter` has one bounded priority/FIFO semantic TX queue,
  explicit/default transport selection with no fallback, typed readiness and
  capability failures, bounded correlation replay, queued cancellation,
  capability-dependent active cancellation, normalized failures, safe bounded
  diagnostics and bounded idempotent shutdown.
- The generic adapter protocol requires only TX audio/completion, frequency and
  modulation. It can represent the proven 251.000 MHz AM finalized-PCM use case
  without SRS types and does not invent a DCS Native Voice API.
- A tests-only deterministic Fake adapter proves readiness, capabilities,
  transmission, blocking, exact call count, completion/failure, cancellation
  and shutdown without network, audio hardware or an SRS process.
- Existing SRS/Yandex/Hybrid Probe production paths are not imported, wrapped or
  rewired. SRS registration, RadioInfo, Opus, pacing and PTT remain unchanged;
  production SRS migration belongs exclusively to Stage 6B.2.
- Durable design: `docs/stage-6b1-radio-router-contracts.md`. The next possible
  stage is **6B.2**, only after separate authorization. Do not begin Phraseology,
  domain migration, Launcher UX or DCS Native Voice work as part of 6B.1.

## 28. Stage 6B.2 production SRS radio transport adapter — 2026-08-28

**Status: CLOSED / FIELD VALIDATED; STAGE 6B.3 NOT STARTED.**

- `SrsRadioTransportAdapter` implements the Stage 6B.1 boundary while retaining
  the existing field-proven SRS 2.4.x connection, registration, RadioInfo,
  single-slot TX, 44.1-to-16 kHz resampling, Opus, packetization, retransmit=0,
  40 ms pacing, UDP send and exact `tx_completed` ownership.
- The first controlled production migration is the IA-1.1 Hybrid Presentation
  Probe finalized-PCM path. It now uses `RadioRouter ->
  SrsRadioTransportAdapter -> existing SRS TX worker`. Ordinary Realtime output
  temporarily enters the same worker through the legacy admission seam; no
  second SRS implementation or domain migration was created.
- The adapter advertises TX audio/completion, frequency and modulation only.
  Queued cancellation remains Router-owned; active single-transmission cancel
  is truthfully unsupported. AM/FM mapping is explicit, while the wired product
  remains the proven 251.000 MHz AM path.
- Readiness is `READY` only when the SRS state is ready and the endpoint,
  server-echoed radio registration and UDP registration are all complete.
  Missing prerequisites degrade readiness. Context, PCM format/rate and
  registered entity/frequency/modulation/coalition mismatches fail closed with
  typed provider-neutral failures. Raw SRS exceptions, credentials, GUIDs and
  audio do not cross the generic diagnostics boundary.
- One accepted request performs one existing SRS enqueue. Generic completion is
  emitted only after the matching established `tx_completed`; Router replay
  returns the prior result without another transmission and conflicting reuse
  fails closed. A bounded 35-second per-request timeout (maximum 120 seconds)
  was added to the generic request and replay identity.
- Deterministic wire equivalence proves that legacy and routed synthetic PCM use
  the same resampler, Opus encoder, frame count, frequency/modulation, packet
  constructor, unit/GUID/retransmit fields, pacer and completion semantics.
  Session packet IDs intentionally continue and need not be byte-identical.
- Validation passed: 73 focused tests, 322 extended SRS/Yandex/IA/lifecycle
  tests, 1,478 full isolated repository tests, 82% isolated branch coverage,
  Ruff, changed-production Pyright, compileall, `git diff --check`, and bounded
  secret/privacy scans.
- A fresh `release-stage6b2-20260828` Core/Launcher/product/installer build
  passed offline Core-native, Launcher-control and assembled Launcher-to-Core
  smokes without external SRS, DCS, provider access or audio devices. Core
  contains the adapter/native dependencies; Launcher excludes them. The
  installer was compiled but not automatically installed. Its size is
  73,189,488 bytes and SHA-256 is
  `CBC83918BE631A48E50D27A3F93D97091BB1DAF44AB546C2A17CA026F06F6F46`.
- The bounded official-SRS field gate completed successfully: 20/20 routed
  Hybrid Probe transmissions traversed adapter start, existing SRS TX start,
  `tx_completed` and adapter completion without loss or duplication, and were
  acoustically confirmed through the official SRS client. Stage 6B.2 remains
  **CLOSED / FIELD VALIDATED**.
- Do not begin Stage 6B.3/domain migration, Phraseology, Launcher UX or DCS
  Native Voice work without separate authorization.

## 29. Pilot Phraseology KB — 2026-08-28

**Status: PILOT PASS / ARCHITECTURE VALIDATED OFFLINE; PRODUCTION WIRING NOT
STARTED.**

- The Core-owned immutable Pilot catalog contains 25 experimental,
  non-normative semantic entries with exact `en-US` and `ru-RU` realizations.
  All 50/50 positive cases and all 12/12 intentional corruption self-tests
  passed; RU/EN semantic equivalence, fresh-resolver determinism and stable
  catalog identity also passed.
- The exact fail-closed boundary is `OperationalSemanticUnit ->
  ProtectedOperationalFragment`. Selection has no fuzzy matching, LLM phrase
  choice, arbitrary free-text parsing, heuristic fallback or automatic
  naturalization. Missing, ambiguous, invalid or wrongly-unitized input returns
  a typed failure and no protected fragment.
- The Pilot is offline and has no DCS, provider, SpeechKit, SRS, RadioRouter,
  microphone, audio-output or credential dependency. It does not implement a
  production PresentationRouter, TTS/radio wiring or migration of existing
  ATC/AAR/AWACS/JTAC/Mission Control wording.
- Catalog SHA-256:
  `7285C72541AD6773C0492A92EFA7A6D04839C7D3E8E2263D3960FFD7022E13AE`.
  Evidence ZIP SHA-256:
  `BD9C93111F74025C85FE49244B6E1F237A4EF0F7D2C54C90C84F9788C7FFE442`.
- The unrelated Setup Wizard baseline remains environment-dependent on this
  workstation: the real `Saved Games/DCS` profile is auto-detected, producing
  3 failures while 7 isolated Setup Wizard tests pass. Pilot code does not
  modify Setup Wizard behavior or tests.
- The next approved direction is incremental Phraseology KB expansion after
  Pilot PASS. It requires a separate explicit implementation task; no AAR or
  Tanker work has started.

## 30. Golden takeoff and real-Qwen Mixed Composition checkpoint — 2026-08-28

**Status: GOLDEN VERTICAL PASS; MIXED COMPOSITION PASS; LIVE GOLDEN
CONVERSATION NOT STARTED.**

- Golden Conversational Vertical #1 proves `natural-language utterance ->
  TakeoffIntent -> existing AirportTowerController -> TakeoffAtcDecision ->
  OperationalSemanticUnit -> PilotPhraseologyResolver ->
  ProtectedOperationalFragment`. Existing deterministic ATC remains the sole
  takeoff authority. Permitted, blocked, unavailable, unsupported and ambiguous
  cases passed with exact callsign/runway preservation: 18/18 positive cases and
  11/11 corruption self-tests. Golden evidence SHA-256 is
  `A75C1A497FAFED19A3654FAD60136982F6487BF37C8D35536FD97909D7BF6C92`.
- The real-Qwen Mixed Probe proves that one utterance can contain separate FREE
  conversational and OPERATIONAL semantics. Six mixed Russian utterances and
  three controls passed through the existing strict Yandex Qwen planner
  boundary: 9/9 provider cases, zero retries/failures/timeouts on the final run,
  and 14/14 corruption self-tests. Qwen identifies
  `takeoff_clearance_request` and may produce the short FREE reply, but never
  grants/denies takeoff or supplies protected values. Mixed evidence SHA-256 is
  `B296A140B22EF6EAF7BDDDDF008AEC0308663DDF45956B53D4632573D08E817D`.
- `ResponseCompositionPlan` keeps the untrusted/droppable FREE envelope separate
  from immutable Core-rendered protected fragments. Core locally orders FREE
  before PROTECTED. Once `ProtectedOperationalFragment` exists, no generative
  provider may rewrite, paraphrase or naturalize it. Qwen never receives the
  composed protected response.
- Exactly one existing Communication Profile is active at a time: `ICAO`,
  `FAA_US`, `NATO_MILITARY` or `FAP_RUSSIAN_ATC`. Profile selection is
  independent from input language and never forces the user to speak the
  profile's language. Operational phraseology follows the selected profile;
  FREE conversation remains separate. The Mixed Probe selects
  `FAP_RUSSIAN_ATC`, while its current wording remains experimental,
  non-normative and not verified against ФАП-414.
- Long-term production Phraseology KB architecture remains profile-specific,
  versioned, provenance/source-aware and independently updateable. The current
  code-seeded Pilot catalog is proof-of-architecture, not the final storage or
  update model. High-level source families are ICAO Doc 4444/9432; FAA JO
  7110.65, AIM and Pilot/Controller Glossary; NATO APP-7 plus domain military
  sources; and ФАП-414 plus applicable authoritative Russian sources. No source
  corpus was downloaded or populated in this checkpoint.
- The reviewed catalog now contains 29 experimental bilingual entries and
  passes 58 positive realizations plus the existing 12 corruption self-tests.
  Catalog SHA-256 is
  `1991EBF5924568DB81B96552CDAFA4DF013DAE92DFD523288EEB40CF4D517DDF`.
- The next milestone is **Live Golden Conversation** only: approximately 5–6
  natural Russian takeoff-clearance utterances, including `Добрый день!
  Разрешите взлёт.`, through `microphone -> Qwen mixed decomposition ->
  deterministic ATC -> selected Communication Profile -> Phraseology KB ->
  local FREE + PROTECTED composition -> Yandex SpeechKit -> RadioRouter ->
  production SRS adapter -> official SRS Server/Client -> pilot hears ORION`.
  The final sentence must not be hardcoded: it must contain genuine FREE output
  and protected KB phraseology. This live milestone is not implemented by this
  checkpoint.

## 31. Live Golden Conversation Mode A implementation ready — 2026-08-28

- Status is **IMPLEMENTATION READY FOR FIELD**, not `LIVE GOLDEN PASS`. A real
  spoken-input run and explicit official-SRS-Client acoustic review remain the
  field gate.
- The bounded path reuses the single production Yandex + SRS session as the
  speech-input owner: official SRS Client microphone/PTT -> SRS Server -> ORION
  SRS RX -> Yandex final user transcript. It creates no second microphone,
  Realtime session, SRS TX worker, packetizer, or Qwen-Realtime-to-SRS mode.
- Field evidence from the first build proved that Yandex's 400 ms server VAD
  could finalize a natural pause inside one held SRS PTT before the established
  SRS RX transmission boundary. A subsequent field build then proved that the
  deployed Yandex backend accepts `turn_detection=null` but silently ignores
  `input_audio_buffer.commit`: `response.create` starts output from prior context
  without producing `input_audio_buffer.committed` or an input transcript.
- The compatible SRS input seam therefore keeps server VAD and aggregates all
  finalized provider segments under the existing physical SRS RX transmission.
  At that boundary ORION streams 800 ms of zero PCM in paced 40 ms chunks to
  close the final provider segment. Only the joined non-empty transcript reaches
  the Live Golden consumer. Direct Audio remains unchanged.
- Provider cancellation is advisory on the current backend: cancelled responses
  may continue to generate text and PCM. While Live Golden suppression is active,
  every provider-created response ID is filtered before the Realtime endpoint and
  SRS transport, independently of cancellation completion. One Qwen3.6 Responses call
  produces only the strict FREE/OPERATIONAL decomposition and FREE reply.
- Core then runs the existing Golden Takeoff decision over an explicitly
  labelled `CONTROLLED GOLDEN ATC FIXTURE`, resolves the experimental
  `FAP_RUSSIAN_ATC` Pilot entry, composes FREE before the immutable PROTECTED
  fragment, sends that exact local text to the existing SpeechKit client and
  routes finalized PCM through the existing RadioRouter and production SRS
  adapter. The protected fragment is never returned to Qwen.
- Launcher exposes one small `LIVE GOLDEN CONVERSATION / MODE A` field control.
  It presents the six approved Russian mixed cases plus pure-operational and
  pure-conversational controls in order, and requires an explicit per-case
  `clear`, `unclear`, or `not_heard` review before advancing.
- Test Evidence now supports a bounded `live-golden-summary.json` plus optional
  finalized SpeechKit-to-SRS WAVs. It records the strongest real-input
  correlation, Qwen/ATC/phraseology/composition/SpeechKit/RadioRouter/SRS
  chain, protected integrity, stage latency, human review and build identity.
  WAV evidence is transmitter-side only, never a receiver-side recording.
- Frozen build identity is carried by a bounded marker and records exact Git
  SHA, branch and ORION version, closing the earlier `orion_build_sha=unknown`
  observability gap for the field build.
- This milestone is Mode A: DCS is not required and no live DCS runway awareness
  is claimed. Broader ATC, other communication domains and Stage 6B expansion
  remain out of scope.
