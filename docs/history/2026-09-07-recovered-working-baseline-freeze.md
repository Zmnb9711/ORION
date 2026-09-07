# 2026-09-07 — recovered working baseline freeze

Architecture Guard: OFF. Documentation/checkpoint only; no development stage.

Branch: `codex/fallback-20260906-1800`.
Verified direct ancestry:

1. `a955d7c39f20c020e15de6bc2be272755928cc98`: historical Launcher/Core/SRS,
   committed state at 2026-09-06 18:00 Moscow (not proof of uncommitted files).
2. `3f364bdfb05d4c2a0141f75708032ec7a26e768b`: minimum golden full-voice migration.
3. `333ca5e481c89b8294e0f491fbd2d2e6d6e87319`: observation-only STT/Core boundary;
   59 offline tests passed and one artifact was built/installed in that prior task.

The user subsequently validated one real ownship request with physical SRS PTT
and clearly heard the response. FINAL was exactly
`какой мой текущий курс и координаты`; turn
`d9b31e5c-9853-4c07-994a-297490ef32d3`. The existing evidence links this turn to
SRS TX ID `p7c-d9b31e5c98534c07994a297490ef32d3`, 385 completed frames.
Boundary/admission/first-TX/completion timestamps (UTC) are respectively
20:26:02.097 / 20:26:02.100 / 20:26:04.755 / 20:26:20.171.
STT final -> first radio TX is 2.658 s; this is not end-to-end acoustic latency.

The earlier silent request was recognized as
`какой мой текущий вкус или оригинал` (turn
`af441df7-fa25-4913-b633-93b844583712`). Its unsupported silence is correct for
the unchanged bounded intent contract, not a Launcher or full-voice failure.
The successful and preceding packages are preserved without modification.

Freeze verification found all 3267 installed product files matching the
333ca5e artifact manifest; source archive and installer hashes also matched.
Original evidence and build files remain in place, with verified copies under
`C:\Users\Алексей\Documents\ORION-Restoration\recovered-working-333ca5e-20260907`.
See [canonical checkpoint](../recovered-working-checkpoint.md) for exact hashes,
evidence attribution and the install/source distinction from this docs-only commit.

Limits remain explicit: no established physical PTT-release -> audible-response
latency; natural Russian STT robustness unsolved; <1 s not achieved/proven;
the exact TTS response and authoritative per-turn numeric source snapshot were
not retained, so this turn's heading/latitude/longitude agreement is unverified.
No discarded productionization gates, lifecycle redesign, evidence redesign,
automatic RX/TX WAV or latency features are adopted by this freeze.

This task changes documentation/checkpoint records only, with no rebuild,
provider request, PTT, SRS configuration or production code modification.
Stop after the documentation commit and recovered-branch push; no new work is
authorized by this history entry.

RECOVERED LAUNCHER + MINIMAL FULL-VOICE VERTICAL —
WORKING BASELINE FROZEN / FIELD VALIDATED.
