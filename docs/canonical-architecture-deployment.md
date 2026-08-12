# ORION canonical architecture and deployment

## Product boundary

ORION is the application. The launcher is only a user interface and lifecycle controller for an installed ORION runtime.

The canonical runtime chain is:

```text
DCS World
  -> Saved Games/DCS*/Scripts/Export.lua
  -> UDP telemetry / Mission Bridge
  -> ORION Core
     -> validated aircraft state
     -> F/A-18C aircraft knowledge / cockpit mapping / live validation
     -> Mission Context
     -> Voice Core / grounded dialogue
     -> Virtual ATC
     -> Mission Control / AWACS
     -> AAR
     -> JTAC / CAS 9-line
     -> other aircraft modules
  -> local Core API / runtime state
  -> ORION Launcher (client)
```

No launcher-specific state may replace a canonical Core domain model. In particular, DCS installation selection, telemetry state, aircraft identity, mission state and AI/voice readiness belong to ORION Core/runtime services and are read by the launcher.

## Process boundary

A production Windows installation must contain at least two independently launchable executables/process roles:

1. `ORION-Core.exe`
   - owns `orion.app:app` and application lifecycle;
   - starts and owns the DCS telemetry bridge and application runtimes;
   - remains the source of truth for readiness and live state;
   - does not create the desktop UI.

2. `ORION-Launcher.exe`
   - does not embed or impersonate ORION Core;
   - discovers the installed Core executable;
   - starts/stops Core as a separate process;
   - waits for the Core health/readiness API;
   - displays live state reported by Core;
   - can request DCS setup/repair through canonical Core/runtime services;
   - can launch DCS through the canonical selected-installation service;
   - never owns aircraft, mission, ATC, AI or telemetry state.

The existing single `ORION.exe --desktop` bundle is a compatibility/prototype path and is not the target deployment architecture.

## Installed payload

The Windows installer must deploy the complete ORION product, not only the launcher shell:

```text
ORION/
  Core/
    ORION-Core.exe
    runtime dependencies
  Launcher/
    ORION-Launcher.exe
    UI resources / branding
  Integration/
    dcs-export/Export.lua
    mission bridge / mission pack resources
  Aircraft/
    F-A-18C knowledge, mapping and validation resources
    additional aircraft modules as they are production-ready
  Runtime/
    config/
    logs/
    diagnostics/
    state/
  Updater/
```

Exact physical layout may change during packaging implementation, but the process and ownership boundaries above are mandatory.

## Existing ORION capabilities that belong to Core

The following existing work is part of ORION and must remain reachable from the production Core flow instead of being reimplemented in the launcher:

- DCS Export/UDP telemetry bridge and live telemetry handshake;
- unified preflight and DCS connection diagnostics;
- F/A-18C aircraft knowledge, cockpit mapping, calibration, live validation and cockpit voice queries;
- Mission Context and tactical situation services;
- Voice Core, Windows audio runtime and grounded dialogue;
- Mission Control / AWACS tactical runtime;
- AAR rendezvous and DCS-backed event runtime;
- JTAC/designation and CAS 9-line workflows;
- Virtual ATC Core, fixed-airfield Ground/Tower/Departure orchestration;
- Mission Bridge / Mission Pack integrations;
- diagnostics, settings and updater services.

## F/A-18C first real-flight acceptance path

F/A-18C is the first aircraft-specific end-to-end acceptance path. The production system must support this sequence without launcher-local substitutes:

```text
Install ORION
-> start ORION Launcher
-> Launcher starts ORION-Core.exe
-> Core health becomes ready
-> detect/select installed DCS
-> install/repair DCS integration
-> start DCS
-> receive live telemetry
-> Core identifies F/A-18C
-> bootstrap Hornet aircraft pack
-> cockpit mapping/live validation state is available
-> grounded voice/AI query can read live F/A-18C state
-> ATC/Mission Assistant services consume the same live Core state
```

A build is not considered end-to-end functional unless this chain reaches the real Core services.

## Deployment rules

1. Launcher and Core are built as separate entry points and separate executables.
2. The launcher may never instantiate the Core application server in-process in production mode.
3. Installer smoke tests must prove both executables exist after packaging.
4. Core smoke tests launch `ORION-Core.exe` directly and require `/health` success.
5. Launcher smoke tests launch `ORION-Launcher.exe`, verify it starts a separate Core process, and verify the Core health endpoint belongs to that child process.
6. DCS setup must persist one canonical selected installation used by readiness, repair and DCS launch. Parallel launch-profile state is not permitted unless it is derived from that canonical installation.
7. Production readiness displayed in the launcher must come from Core API/runtime state, not UI-local booleans.
8. Aircraft-specific status, including F/A-18C, comes from live Core telemetry/aircraft services.
9. No component is called READY solely because it imports, builds, or has a mocked unit test.

## Migration order

1. Establish a standalone Core entry point without desktop/UI dispatch.
2. Inventory current Core routers/runtimes and classify launcher-only duplicate state.
3. Make DCS selected installation the canonical launch/readiness source.
4. Replace embedded `CoreServer` launcher ownership with external Core process management.
5. Build separate Core and Launcher executables.
6. Rebuild the installer around the complete installed payload.
7. Add process-boundary and installed-layout regression tests.
8. Only then replace/polish the launcher UI against the approved visual design.

Until steps 1-7 are complete, UI polish is not a release blocker and must not drive Core architecture.
