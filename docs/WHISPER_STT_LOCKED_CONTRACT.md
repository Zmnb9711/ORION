# ORION Whisper STT — Locked Alpha 0.2 Contract

Status: **product invariant**. Do not replace or remove this STT path as part of unrelated Launcher, Voice, lifecycle, installer, or UI work.

## Baseline

- whisper.cpp: **v1.8.6**
- model: **Whisper Medium / ggml-medium.bin**
- execution: **CPU-only** (`--no-gpu`)
- Windows portable fallback: pinned generic **ggml-cpu.dll** with optimized-backend disable/retry after supported Windows backend crash statuses
- STT installation is **explicitly user-controlled** from Launcher via **DOWNLOAD & INSTALL STT**
- `LAUNCH DCS` and `START AUDIO TEST` must never silently download or replace STT

## Physical process boundary

The installed Windows product has three distinct executable processes:

- `Voice\ORION-Voice.exe` — owns the live Voice worker and Whisper STT execution/control channel.
- `Core\ORION-Core.exe` — owns the ORION Core/API service only. It must not host a `--voice-worker` mode and must not be used as the executable container for Whisper.
- `Launcher\ORION-Launcher.exe` — owns the UI/tray and supervises product lifecycle.

The Voice executable may be a console-subsystem binary internally so stdin/stdout remain available for the worker JSON protocol, but it is launched with `CREATE_NO_WINDOW`; no additional console window should appear to the user.

Speech recognition belongs to Voice/Whisper. Core may request/consume Voice results through the Voice runtime boundary, but Core must not perform STT itself.

## Installation state

Launcher must visibly distinguish at least:

- NOT INSTALLED
- DOWNLOADING / INSTALLING
- READY
- ERROR

Voice/Whisper may only report READY when the required runtime and Medium model are present and the installed runtime version is the locked v1.8.6 baseline.

## Resumable downloads

Runtime and model downloads use persistent `.part` files under the ORION STT runtime directory. Partial bytes survive Launcher exit, ORION restart, Windows restart, and ordinary network failure.

On retry, ORION requests `Range: bytes=<existing-size>-`. If a server does not return a valid HTTP 206 response with a matching `Content-Range`, ORION must preserve the `.part` file and report an explicit error. It must not silently truncate the partial file and restart from zero.

Completed payloads are checksum-verified before promotion. Promotion from `.part` to a completed payload is atomic. A valid already-installed Medium model must not be downloaded again during an ORION update or normal Voice startup.

## Voice lifecycle integration

The STT implementation is wrapped by, not replaced by, the Voice lifecycle:

1. `DOWNLOAD & INSTALL STT` -> Whisper READY.
2. `LAUNCH DCS` -> ensure the already-installed `ORION-Voice.exe` / Whisper worker is READY -> launch DCS.
3. `START AUDIO TEST` -> use the already-live Voice worker -> Voice remains READY afterwards.
4. Closing the Launcher window -> tray; Voice/Whisper and Core continue.
5. Tray `Exit` -> Voice/Whisper -> Core -> Launcher; no orphan processes.

Any future change that alters the Whisper version, model, CPU-only policy, explicit install UX, resumability, physical Voice/Core process boundary, or lifecycle semantics requires an explicit product decision rather than an incidental refactor.
