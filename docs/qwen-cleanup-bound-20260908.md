# Bounded Qwen cleanup (offline-validated tranche)

Baseline: `333ca5e481c89b8294e0f491fbd2d2e6d6e87319` plus truthful STOP
`7b041d64b663fad1862c14d960c2b9c52cab0c99`. No Hybrid Aircraft integration.

## Ownership and budget

The native Responses transport still owns one dedicated asyncio loop/thread and
one aiohttp session per planner run. Production changes are confined to
`orion/yandex_qwen_planner.py`; the outer lifecycle is unchanged.

The first cleanup operation establishes one absolute monotonic deadline, 0.5 s
from cleanup entry. All phase cutoffs are derived from that same deadline:

| Phase | Absolute cutoff relative to cleanup entry |
|---|---:|
| All DELETE attempts together | 0.10 s |
| Initial provider cancellation/drain | 0.25 s |
| Session close | 0.40 s |
| Final cancellation/drain | 0.45 s |
| Thread join | 0.50 s |

Unused time is not an additional timeout window. The native close waits for
acknowledgement, not merely a successful `.cancel()` call. `asyncio.wait` bounds
drain without waiting indefinitely for cancellation-resistant tasks.

STOP compatibility is for the foreground planner-cleanup phase of the serial
voice path, before presentation. With no active presentation task, protected TTS
`aclose` introduces no timed wait. The cooperative enclosing envelope is native
close (2 s), listener join (1 s), router shutdown (2 s): 5 + 0.5 = 5.5 s, leaving
0.5 s for polling/scheduling/unwinding under the unchanged 6 s STOP.

This is not a bound on the preceding provider request or arbitrary failures in
other subsystems. The existing native task drains must cooperate; an unclean
radio shutdown's fallback is not covered by this successful-shutdown envelope.
No outer cancellation or teardown policy is changed here.

## DELETE policy and privacy tradeoff

The historical IA-5 document records stored Responses and terminal DELETE intent.
The previous transport already treated DELETE failure as best-effort. This
tranche preserves that intent, not a guarantee of server-side erasure.

DELETE is privacy/resource hygiene, not a prerequisite to interpreting an
already-returned SemanticResponse. Unique known IDs are attempted once while
the shared 0.10 s hygiene window remains. Remaining IDs are skipped once it
expires or any DELETE times out (even if a timer returns fractionally early).
Non-2xx, exceptions and incomplete attempts are classified as
`delete_incomplete`. The body is neither needed nor retained.

Transport shutdown has priority. It may succeed with a deletion warning, but
that does **not** prove provider response state was deleted. Provider retention
can therefore continue under its own policy. No persistent deletion worker,
retry policy change, credentials change or live provider verification is added.

## Terminal contract

`CleanupResult.closed` is true only after session closure, task drain, thread
termination and legal loop closure. It can coexist with `delete_incomplete`.
Other failures raise internal `YandexPlannerCleanupError` with bounded categories
only: cancellation, session close, drain, thread alive, deadline, internal error,
or concurrent cleanup in progress. No provider body or exception detail is logged.

After failure, result/error is sticky: repeated cleanup does not retry, reset
the deadline, create another owner, or optimistically mark resources closed.
The failed run retains ownership references. A live thread cannot be forcibly
killed; a stopped loop with unresolved tasks is not closed. Truthful STOP keeps
the enclosing failure as ERROR. Production does not launch deferred rescue.

Repeated successful cleanup is idempotent. Cancelling a `to_thread` await still
does not stop its underlying blocking work; this fix does not rely on that.

## Offline evidence

`test_qwen_cleanup_bound.py` exercises real transport loops with fake sessions,
controlled cancellation, slow/failed deletion and close, pending tasks, actual
blocked threads, loop-close safety, repeated cleanup and concurrent ownership.

`test_qwen_cleanup_full_voice_stop.py` exercises unchanged `_voice`, `_run` and
STOP with external dependencies replaced. It includes a real five-second
enclosing-envelope timing injection, successful and failed transport cleanup,
and exact supported/unsupported Russian utterance regressions without providers.

Truthful STOP tests, existing Qwen tests, protected/full-voice tests and golden
offline replay remain regression gates. Test harnesses release deliberately
blocked resources after observing failure; those releases are not the fix.
