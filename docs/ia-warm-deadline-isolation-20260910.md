# Warm Interpreter: separate user deadline and isolation barrier

ORION ARCHITECTURE GUARD: OFF

2026-09-10. User-authorized recovery continuation; no new stage number.
Parent: `d3245292c176d6dc51b2a9adcb71b2e238e0b234`, branch `codex/ia-aircraft-interpretation`.

## Proven defect and correction

The previous `WarmYandexAircraftInterpreter.interpret` used the same absolute
one-second limit for request, completed response, normalization/parse, both
conversation item deletes and both deletion ACKs. Last A completed its response
at approximately 869 ms, parsed correctly, then exhausted that deadline waiting
for ACKs. B was not sent. This was deadline domain mixing, not an NLU failure.

Interpretation still has a hard one-second ceiling (or the earlier request
deadline), including strict typed proposal construction. Warm Core admission
also checks the same request deadline, exact source/hash, turn/operation,
expected provider and the actual capability definition. The development Qwen
adapter remains unwired; the installed handoff cannot call Planner.

After valid proposal construction, the owner atomically enters ISOLATING and
owns one cleanup task before returning the result. No await intervenes in that
publication. Cleanup has its own **500 ms** budget, about twice the previously
observed 239 ms ACK roundtrip; it does not borrow or increase interpretation's
budget. The new live gate measured approximately 263 ms for each barrier.

Before READY: the response must be completed/validated; the exact current user
and assistant items must both be deleted and both unique, correlated ACKs must
be observed. Both ACKs are mandatory for this client's safe-reuse contract.
There is no additional reset event or speculative hidden-memory guarantee.
This proves the protocol item inventory, not access to provider internals.
Provider isolation does not prohibit future explicit ORION-owned context.

While ISOLATING, another interpretation fails immediately as unavailable,
without submitting B, queueing indefinitely, retrying or opening another session.
`wait_isolation` is a shielded optional barrier observer. STOP owns cancellation
of the real task and bounded transport close. An isolation failure does not
retroactively revoke the already valid proposal, but degrades/closes the owner
and prevents subsequent requests. Cleanup failures remain truthful errors.

## One final provider gate — PASS

Exactly one connection, A then barrier then B; no retry/third operation.
Session `2f3fdc53a478`, 2026-09-10 15:47:56 UTC / 18:47:56 Moscow.

| Operation | Exact input | Typed capability | Provider-harness user path | Separate barrier |
| --- | --- | --- | ---: | ---: |
| A | Что у нас за машина? | aircraft.identity | 523.181 ms | 263.369 ms |
| B | Где мы сейчас? | not_applicable | 377.631 ms | 263.485 ms |

High-resolution response.create → response.done: A 519.304 ms, B 374.563 ms.
Parser trace: A approximately 2.64 ms, B 1.79 ms, including bounded evidence
overhead. Provider harness excludes Core admission; do not call these end-to-end
voice/PTT latencies. Runtime's existing coarse monotonic clock reports A 531 ms,
B 375 ms, barriers 266/265 ms; do not mix those readings with perf-counter data.

Both raw terminals were bounded fenced JSON; unchanged normalization produced
the exact expected capability objects. Four exact deletion ACKs observed.
Audio deltas/payloads/tools: zero. Owner stopped, pending tasks/operations zero;
after asyncio.run, new threads zero. The known transient DNS executor is not a
leak and no thread architecture was changed.

Evidence directory:
`C:\Users\Алексей\Documents\ORION-Restoration\ia-aircraft-interpretation-20260910`.
`deadline-separated-isolation-gate.json` SHA-256:
`F323983CC820FB2C1599C8B732C3144ACC87FD2269484E4CD1CF1FF80E945F8B`.
The previous `final-warm-isolation-gate.json` is preserved unchanged, SHA-256:
`5296CBD5D5B83B8C9596B2599F6CB9EE81BABE315A10E41A65CF3F031980DC62`.

## Minimal installed-host handoff

Only after live PASS: the normal FullVoiceService starts optional warm-up on a
separate Interpreter connection, without a readiness gate. Golden ownship,
local aircraft/hybrid/social and eligible Conversation retain precedence.
Only a clean unresolved whole-source turn enters `interpret_aircraft_warm`.
Core issues a source-bound single-use grant; `HybridAircraftCore.run_interpreted`
consumes it before entering the existing authoritative ToolGateway aircraft
projection and informational presentation. No synthetic recognized phrase,
grammar extension, telemetry-to-speech conversion or provider-supplied fact.

The same turn proceeds without awaiting history cleanup. Existing transport,
PTT/STT, semantics, phraseology, protected TTS, RadioRouter, DCS WorldModel owner,
Launcher START/STOP, SRS configuration and general Planner remain unchanged.
The new owner is closed in a finally block around existing cleanup, including
when an old owner's shutdown fails. No second WorldModel or SRS owner exists.
A type-only cast documents the pre-existing closed social-act union; it does
not change the recognizer's values or runtime validation.

Existing Test Session scalar projection records separate route_source values
`INTERPRETER_INTERPRETATION_COMPLETE`, `INTERPRETER_CORE_ADMISSION_COMPLETE`,
`INTERPRETER_ISOLATION_READY` with completion_ms. No recorder, raw-body logger
or audio capture feature was added. Normal privacy behavior is unchanged.

## Offline and preservation evidence

Deadline/lifecycle focused set: 510 PASS before live. Final IA/host/scope subset:
87 PASS. Exact fake-clock replay at 741/869 ms succeeds and permits delayed ACKs
at 1041/1169 ms, while no B is sent before READY. >1000 ms interpretation still
fails. No ACK, one ACK, wrong ACK, STOP, token cancellation, cancelled observer,
close failure and cleanup task ownership have negative tests. An initial
wall-clock fixture was corrected for Windows' coarse timer; production timers
were not changed.

Actual Core fast paths and separate Conversation transport remain available
while Interpreter isolation is stalled. Normal host replay proves natural A,
negative B, existing pure/hybrid/ownship routes, ambiguity and excluded commands.
Malicious provider/source/operation, cancellation, late and extra-field proposals
are rejected. Injected extra telemetry never enters the typed plan/final text;
the actual host replay reaches the existing protected TTS request builder.

Historical freeze tests are not blanket-disabled: `ia_handoff_hunks.json` records
only literal reviewed edits in three production files; reversing those hunks
must reproduce the entire d324 source byte-for-byte. Mutation tests prove both
in-hunk and outside-hunk changes fail. Old historical comparisons then still run.
Old fake START request now supplies the already-required folder_id. Generic host
replays disable only the new external provider boundary; IA tests explicitly use
the real warm owner with a fake wire.

Full current regression: **3004 PASS, 4 pre-existing FAIL, 4 SKIP**, 34 warnings,
65.27 seconds. **Zero unexpected failures. Not an all-green suite.**
The same four failures were reproduced on a separate immutable d324 archive:
one stale IA-contract-consumer allowlist and three setup-wizard tests affected
by local Saved Games auto-discovery. The new development adapter is explicitly
listed; the pre-existing four extra consumers remain the same baseline failure.
No unrelated production fix or xfail was introduced.

Reports: `deadline-host-regression-final.xml`, `baseline-existing-failures.xml`.
Ruff orion/tests PASS; compileall orion/tests PASS; selected changed production
and new-test Pyright PASS, zero errors/warnings; git diff --check PASS.

## Release boundary

Provider instructions SHA-256 unchanged:
`4d4551408acc580b75e9046a8e14ce0156ab3c5ecf4d063b9eb1519a87431115`.
Parser, envelope normalization, capability schema and aircraft forms unchanged.
Build exactly once from the coherent commit after these gates. Keep the generated
`data/fa18c_value_profiles.json` and prior evidence; do not package untracked data.
Do not install, merge/push, start DCS/SRS or request PTT in this implementation turn.
The natural-language capability is OFFLINE + PROVIDER proven, **not FIELD proven**.
