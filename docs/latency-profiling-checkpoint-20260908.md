# Latency profiling checkpoint — 2026-09-08

ORION ARCHITECTURE GUARD: OFF

Documentation/checkpoint only. The user closed measurement and explicitly
deferred optimization; this records that direction, not a new design decision.

## Separate immutable identities

| Role | Exact identity |
|---|---|
| Canonical production branch | `codex/fallback-20260906-1800` |
| Frozen production documentation | `05c832762a73ed38f98984942227dbdee1e89ef3` |
| Field-validated production source | `333ca5e481c89b8294e0f491fbd2d2e6d6e87319` |
| Historical Launcher/Core/SRS | `a955d7c39f20c020e15de6bc2be272755928cc98` |
| Minimum full-voice migration | `3f364bdfb05d4c2a0141f75708032ec7a26e768b` |
| Profiling-only source | `18a3a79917292a15792b7c9b412c638e77fd03f1` |
| Profiling/history branch | `codex/latency-profile-20260908` |

At checkpoint entry, remote production branch still resolved to 05c8327. The
local recovery worktree was clean at 18a3a79, one commit ahead. A separate
profiling branch was created there; only that branch is published. The existing
local fallback ref at 18a3a79 is not a production promotion and was not rewritten.
Use the exact frozen SHA or verified remote production ref, not an assumed local
branch HEAD. No merge, reset, forced push or production-branch update is performed.

333ca5e is the source of the earlier installed, field-validated production build.
The last verified installation used for measurement is 18a3a79. This task does
not reinstall 333ca5e, rebuild anything or redefine production based on installed
measurement binaries. The [original freeze](recovered-working-checkpoint.md)
remains unchanged as a historical record of its own installation verification.

## Recorded field result

Both FINAL transcripts: `какой мой текущий курс и координаты`.
Both answers explicitly confirmed clearly audible; 385 SRS frames and completed
TX per response; no dropped profiling events.

| Measured interval, ms | Turn 1 | Turn 2 |
|---|---:|---:|
| T0 -> T2, TX-end observation to FINAL/EOU | 420.698 | 425.914 |
| T2 -> T4, finalized utterance to protected response | 62.389 | 68.665 |
| T5 -> T7, protected text to first PCM | 2898.734 | 2538.003 |
| T7 -> T9, first PCM to first SRS frame | 6.385 | 6.167 |
| T0 -> T9, machine-observed response start | **3389.100** | **3039.413** |
| T3 -> T4, Core itself | 2.406 | 1.524 |

Dominant measured contributor: TTS time-to-first-PCM, approximately 2.54–2.90 s.
STT/EOU is approximately 0.42 s; Core processing is small relative to TTS.
The <1 s target is not achieved. No latency optimization was performed.

## Boundary definitions and limitations

| Boundary | Exact observation |
|---|---|
| T0 | ORION accepts official UDP7082 user sending falling edge, before drain |
| T1 | Native adapter accepts STT FINAL |
| T2 | Matching FINAL/External-EOU barrier future completed |
| T3 | Core processing starts, before InteractionRouter |
| T4 | Core protected response composition completed |
| T5 | Finalized protected text about to enter TTS stream |
| T6 | Actual client TTS RPC method about to be invoked |
| T7 | First validated nonempty TTS PCM yielded |
| T8 | SRS adapter streaming entry accepted under stream lock, before prebuffer/physical guard |
| T9 | First local SRS send_voice returns successfully |
| T10 | Response TX pacing and final-frame duration completed |

T0 is not sample-exact physical button release. T9 is not headphone sound onset.
T2 precedes the later host handoff. T6 is not server receipt. T8 is not the
earlier Router submission or first-frame permission and precedes T7 in both
turns; T8-T7 is negative and T9-T8 overlaps TTS wait. Do not sum overlapping
intervals as independent radio overhead. T10-T9 is response duration, not startup.

Durations use one QPC domain, not UTC subtraction or mixed clocks. Previously
existing coarse timers were left untouched. Instrumentation has nonzero
observation overhead; offline tests prove functional equivalence, not zero
timing perturbation. Two successful samples are not p95 or a general benchmark.
STT/SRS sessions were reused; TTS channel/RPC was fresh per response. No deliberate
warm-up. DNS/TLS/provider setup versus generation contribution is unobservable.
Exact numerical source facts/TTS output were not newly captured; acoustic PASS
does not establish a separate field-by-field numerical audit.

## Preserved evidence

Original ZIP directory:
`C:\Users\Алексей\AppData\Local\ORION\runtime\test-evidence`.
Original report:
`C:\Users\Алексей\Documents\ORION-Builds\frozen-latency-18a3a79\latency-profile.md`.

All three originals remain untouched, with SHA-256-verified copies in:
`C:\Users\Алексей\Documents\ORION-Restoration\latency-profile-18a3a79-20260908`.

| File in preservation directory | SHA-256 |
|---|---|
| ORION-Test-Evidence-20260908-123259.zip | `8F592BC26D3FB31E1A2F15FDF1347BDB170E8C6B0C8CE1269A44297794E657A8` |
| ORION-Test-Evidence-20260908-123800.zip | `3E5433F45CDC85540F7A5A60136FDC292ED3A11CD2A41CB74FDD26089B9D3AAD` |
| latency-profile.md | `179A1AF376EA084786A3910D8C2D5E8F62C111087C04116BDD5B78D3E721C4E0` |

The full text report is also retained in
[dated history](history/2026-09-08-full-voice-latency-report.md), with original
measurement-time status statements preserved as historical statements. This
checkpoint supersedes its pre-documentation-push status, not its measurements.
Raw ZIPs remain local, outside Git. Their existing metadata says build SHA
unknown; artifact attribution uses the independently verified installation chain.

## Deferred backlog — no implementation authorization

Optimization is deliberately deferred: later complex responses, LLM/tool
execution, response generation and longer TTS flows require broader end-to-end
assessment rather than optimizing this bounded ownship slice in isolation.

- Measure TTS channel/RPC setup contribution separately from provider generation.
- Evaluate connection/channel reuse where appropriate; no reuse design approved.
- Evaluate streaming response -> streaming TTS for complex generated responses.
- Measure LLM/tool/TTS overlap for complex interaction.
- Retain the goal of <1 s to first useful audible response where technically
  achievable; future measurements must distinguish local send from audibility.
- Natural Russian STT robustness remains separately unresolved; no STT options
  or intent matching changes are authorized here.
- A `provider_transport_failure` was observed after the second completed TX
  around shutdown. Both responses had already succeeded. Exact cause is not
  established; it is not classified as the cause of either latency measurement.
  Record as follow-up if recurrent, without investigating it in this task.

No new runtime feature, code change, rebuild, DCS/SRS run, provider call, PTT,
latency optimization or next implementation milestone in this checkpoint task.

FULL-VOICE LATENCY PROFILE —
MEASURED / DOCUMENTED / OPTIMIZATION DEFERRED.
