# Recovered working checkpoint — 2026-09-07

Architecture Guard: OFF for the user-authorized historical recovery line.
Canonical pointer for this branch; not a proposal or authorization to develop.

## Frozen source and installed artifact

Branch: `codex/fallback-20260906-1800`.
Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-fallback-20260906-1800`.

| Role | Exact commit |
| --- | --- |
| Historical Launcher/Core/SRS at 2026-09-06 18:00 Moscow | `a955d7c39f20c020e15de6bc2be272755928cc98` |
| Minimal golden full-voice migration | `3f364bdfb05d4c2a0141f75708032ec7a26e768b` |
| Diagnostic-only boundary / installed working source | `333ca5e481c89b8294e0f491fbd2d2e6d6e87319` |

These are direct parent/child commits. The historical cutoff proves committed
HEAD, not unknown uncommitted state. Golden component reference remains
`57a563a067c980c3ff8057172aa6f5fefb33a5b0`.
The documentation freeze commit is a descendant of 333ca5e; it is NOT a new
installed code build and must not be substituted for the installer's source SHA.

- Version: `0.2.0-alpha` (not a unique source identifier).
- Source tree: `e712b75d867ad0efba6fdef1d41da6f8f5cdef7b`.
- Installed Launcher: `C:\Program Files\ORION\Launcher\ORION-Launcher.exe`.
- Installed Core: `C:\Program Files\ORION\Core\ORION-Core.exe`.
- Build directory: `C:\Users\Алексей\Documents\ORION-Builds\fallback-stt-boundary-333ca5e`.
- Installer: `installer\ORION-Alpha-0.2-Setup.exe`, 84,096,791 bytes.
- Installer SHA-256: `573658A725A92FF317F2C7185B348BCBF6231ECB7A0271E0B5750C105C022335`.
- Source archive SHA-256: `4E177D9C22466159DFF2C5E32BD9756C9A3EA756D6177B3DE7D5E80400E1AC07`.
- `artifact-identity.json` SHA-256: `9618A6DD122C708E5820582C8998306E9190209D9E2E355282D658B3C81F7535`.
- Freeze recheck: all 3267 manifest-listed installed files match; zero mismatches.
- Prior build validation: 59 offline tests PASS, including active-observation
  golden replay, error/cancellation preservation and exact-text privacy/export;
  installed native, control and integrated Launcher/Core smoke PASS.

The field ZIP records `orion_build_sha=unknown`. Build attribution therefore
uses the verified artifact/installation chain and the user's installed-fallback
field confirmation, not an invented embedded per-turn build attestation.

## Successful physical field turn

- Test session: `198e1e16acd24f45b27a21be3542bf6d`.
- Runtime session: `6a8b5b36962c4042a2aa71898b822c1c`.
- Turn: `d9b31e5c-9853-4c07-994a-297490ef32d3`.
- TX: `p7c-d9b31e5c98534c07994a297490ef32d3`.
- Exact finalized transcript: `какой мой текущий курс и координаты`.
- Terminal observation: `FinalizedUserUtterance`.
- Controlled radio: 251.000 AM; SRS 2.4.0.0.
- User acoustic confirmation: PASS — the user explicitly confirms that the
  ORION response was clearly heard (human evidence, not a machine measurement).

The user-approved field result is PASS for physical SRS PTT, server reception,
UDP7082/CombinedRadioState, physical START/END, native SpeechKit v3 FINAL/EOU,
STT -> Core, supported ownship semantics, protected presentation, TTS and SRS TX.
Machine evidence directly records finalized input and correlated completed TX;
intermediate stage PASS relies also on the unchanged validated path/contracts,
not on nonexistent per-stage result dumps. This proves physical capability of
the bounded full vertical, not general STT robustness or numerical audit coverage.

| Event | UTC on 2026-09-07 |
| --- | --- |
| STT final / STT-to-Core boundary | 20:26:02.097 |
| srs_adapter_tx_started (admission, not first sent frame) | 20:26:02.100 |
| srs_tx_started (first SRS frame) | 20:26:04.755 |
| tx_completed | 20:26:20.171 |
| srs_adapter_tx_completed | 20:26:20.171 in transport log; .172 in Test Evidence forwarding |

TX completed: 385 frames; adapter duration approximately 15,406 ms.
STT final -> first SRS TX = **2.658 s**. This is NOT physical PTT-release ->
audible-response latency: no correlated user release/acoustic onset measurement
is established by this package. Do not present this interval as <1 s or complete
end-to-end latency. No latency experiment was performed during the freeze.

## Earlier misrecognition — preserve without blaming Launcher

Package: `ORION-Test-Evidence-20260907-201637.zip`.
Test session: `cd60ce64794c416ea701639a98910cb9`.
Runtime: `285826c857e64b3d829a6e825a0a1a59`.
Turn: `af441df7-fa25-4913-b633-93b844583712`.
Boundary at 20:16:25.569 UTC: `FinalizedUserUtterance` with exact transcript
`какой мой текущий вкус или оригинал`.

User-confirmed interpretation: Core correctly rejected this as unsupported,
producing no response. The saved transcript and unchanged intent matcher in
`orion/interaction_router.py` support this interpretation; a separate Core-result
dump was not retained. This silent turn must not be classified as a Launcher or
full-voice integration failure. No fuzzy matching or intent expansion is approved.

## Preserved evidence and identity

Original successful package:
`C:\Users\Алексей\AppData\Local\ORION\runtime\test-evidence\ORION-Test-Evidence-20260907-202700.zip`.

Verified preservation directory (originals untouched):
`C:\Users\Алексей\Documents\ORION-Restoration\recovered-working-333ca5e-20260907`.
It contains both field ZIPs, both correlated transport logs, the installer,
source.zip, full artifact identity and the three installed smoke reports.
Every copied file was compared by SHA-256 to its source. These local artifacts
are preserved outside Git; this docs-only push carries their identities/paths,
not binaries, private field packages or unrelated runtime data.

| Preserved file | SHA-256 |
| --- | --- |
| ORION-Test-Evidence-20260907-202700.zip | `69224DC46125AB3F31E4F773E56986CD135C813FA8478FC940711A7CBFA77AAB` |
| ORION-Test-Evidence-20260907-201637.zip | `81921CBE7332C3F3A8FCF6312CE1638E5CC08F06C15A628B5B1C027A6355E8EF` |
| srs-radio-6a8b5b36962c4042a2aa71898b822c1c.jsonl | `809137F1AF46F1AD203A08161C779654961B5282D00462041E84373C38533E24` |
| srs-radio-285826c857e64b3d829a6e825a0a1a59.jsonl | `20738F6F3C93A87C8D1B5C73F3908BDF2A44FED938C589854F4FDE3D7F08144D` |

## Limitations and freeze boundary

- Physical PTT-release -> audible-response latency is not established.
- Natural Russian STT robustness remains unsolved; <1 s response target is
  not achieved/proven. Correct handling of unsupported text remains intentional.
- Exact protected response/TTS request text and the specific authoritative
  heading/latitude/longitude snapshot for this turn are absent from retained
  evidence. Numerical consistency of the spoken values is therefore **unverified**,
  not PASS or FAIL; do not reconstruct values from newer telemetry or fixtures.
- Discarded productionization is not the production baseline: do not import
  Launcher readiness redesign, coalition/radio observability gates, new stopping
  semantics, lifecycle/shutdown redesign, worker/UI redesign, Test Evidence/RX-TX
  WAV redesign, latency profiling or EAM/port changes merely because they exist.
- That work remains preserved on the separate recovery line through
  `2c9d20f4ca406ef7039e4672252e8eb370ac4dc9`, with its unrelated artifacts untouched.
- This checkpoint changes documentation only. No rebuild, provider call, new PTT,
  configuration change or new development milestone is authorized.

RECOVERED LAUNCHER + MINIMAL FULL-VOICE VERTICAL —
WORKING BASELINE FROZEN / FIELD VALIDATED.
