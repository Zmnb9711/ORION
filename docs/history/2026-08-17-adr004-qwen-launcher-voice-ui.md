# 2026-08-17 — ADR-004 Launcher Voice/Qwen UX approved

Baseline for this work: ORION Alpha Windows Build #312 is the current field-confirmed working development baseline. Build #284 remains the immutable Voice/STT recovery GOLDEN.

The user explicitly approved the Launcher UX for the first ADR-004 Cloud Realtime Voice / Qwen vertical slice.

## Approved product UX

Qwen is **not** a top-level ORION feature/button. Qwen is the first implementation of a replaceable `Cloud Realtime` Voice backend.

Configuration lives under:

`Settings -> Voice`

Approved controls:

- `Voice Backend`
  - `Cloud Realtime`
  - `Local`
- `Cloud Provider`
  - visible only when `Cloud Realtime` is selected;
  - first provider: `Qwen Realtime`;
  - control remains provider-neutral for future providers.
- `API Key`
  - secret input for the selected provider;
  - credentials must not be embedded in Core or committed to the repository.
- `Test Connection`
  - verifies provider connectivity/authentication without invoking DCS tools.
- temporary development-only `Test Tool Call`
  - proves `Launcher/Qwen -> local Core -> deterministic test tool -> result -> Qwen/Launcher`;
  - removed or hidden after the vertical-slice smoke gate passes.
- `Fallback`
  - whisper.cpp remains available and preserved by default during the experimental cloud phase.

## Main Launcher surface

The main Launcher screen shows state only, not cloud configuration.

Examples:

`VOICE  READY`
`QWEN  CONNECTED`

or fallback state:

`VOICE  READY`
`LOCAL / WHISPER  READY`

## Safety / regression rule

The existing field-confirmed Build #312 local Voice/STT behavior must not be redesigned or broken by the first Qwen slice. Cloud settings are added alongside the working local path. If the cloud experiment fails, the user must be able to remain on `Local -> whisper.cpp` with the Build #312 behavior intact.

This decision is also incorporated into ADR-004 (`docs/adr-004-cloud-realtime-voice-qwen-vertical-slice.md`).