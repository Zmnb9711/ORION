# Level-0 final control point — offline PASS, one provider gate FAIL

ORION ARCHITECTURE GUARD: OFF

## Recovery / completed scope reconciliation

Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`.
Branch: `codex/level0-yandex-event-contract`.
Unchanged HEAD: `9ccab967dfe018f29302fb87e8105a4bb11a89de`.
Canonical DT403405/recovery docs: `d0f58b5693e4a5f7467e32566be88674e24d4001`.
Previous stop receipts are historical records, superseded by this outcome.

The three historical scope guards now use `tests/level0_scope_guard.py`:

1. Verify exactly the four approved production additions in the immutable
   preservation commit 9ccab967 (compared with its parent).
2. Apply each original historical scope budget to history ending at that SHA,
   excluding only those four committed additions.
3. Independently compare the CURRENT tree against 9ccab967: only
   `orion/yandex_realtime_text_conversation.py` may differ; untracked production
   additions are rejected. In particular, the three other conversational
   modules are NOT added to the current allowed scope.
4. Keep existing historical AST/symbol/Planner transport checks unchanged.

Two focused tests prove the baseline exception does not permit current changes
to frozen modules or arbitrary historical/untracked production additions.
No production changes in this scope-reconciliation turn.

## Complete offline/static control point

**1265 passed, 4 skipped, 31 warnings in 42.13s.** No new failure occurred.
All three reconciled guards pass, including their later symbol/transport
assertions. Prior fixture/correlation/admission, negative event mutations,
ownship, Hybrid, Planner/Qwen cleanup, truthful STOP, presentation, RadioRouter
and authority regressions are included. Skips are existing Hybrid-host cases.

Machine evidence:
`C:\Users\Алексей\Documents\ORION-Builds\level0-event-contract-20260909\final-offline-regression.xml`

SHA-256 `E99444C6A71DECAB6E191CF746B1F638176C2DB7751B3E36B7A4EEBBB767026B`.

- Pyright: 0 errors / 0 warnings (four conversational runtime modules + scope helper).
- Ruff correctness: PASS (four runtime modules + nine test/fixture files).
- compileall for the same scope: PASS.
- git diff --check: PASS.
- AST equality of provider INSTRUCTIONS versus 9ccab967: PASS.
- Explicit import budget / current production scope / no staged artifacts: PASS.
- Existing frozen-subsystem byte identity and source invariance tests: PASS.

The runtime diff remains one experimental adapter: capability/payload
distinction, correlated bounded event parser, exact terminal text, terminal
cancellation checks and timing observations. The most recent runtime repair
was the two-line response-ID guard; this turn does not modify it.

All unchanged: Launcher, FullVoiceService, InteractionRouter, SpeechKit STT/TTS,
SRS protocol/transport, RadioRouter, ToolGateway, WorldModel, Hybrid Aircraft,
ownship, Qwen Planner/cleanup, truthful STOP, DCS integration and packaging.
No provider admission/schema relaxation, timeout increase or voice integration.

## One real provider gate — authorization consumed

Time: `2026-09-09T15:56:53.704691+00:00` (18:56:53 Moscow).
Input, preserved exactly: `Что-то сегодня полёт тяжело идёт.`
Model: `speech-realtime-260528`.
Endpoint: `wss://ai.api.cloud.yandex.net/v1/realtime`.
Used the actual `TextConversationProvider`, unchanged structured INSTRUCTIONS
and `ConversationalCore`; normal saved credentials/configuration mechanism.
One connection, one user-item request, one response.create, zero retries.
Both outbound modality requests were exactly `["text"]`.

Turn: `48e2e4be-14e2-4af0-a19a-370379fd5acc`.
Session: `8c1250d364c2`.
Observed provider response: `resp_d0b1a7426bc344a5826f3d428e312808`.
Adapter SHA-256 at call:
`e7f9e61606974461f0a31c72e1fdfed963f16eb6c51ab577910a31e0e644ca5e`.
Source identity remained unchanged during the call.

Observed events, in order:

1. session.created, `["text","audio"]`, accepted.
2. session.updated, same session and capabilities, accepted.
3. conversation.item.created, user, exact submitted text confirmed by parser.
4. response.created, status in_progress, same multimodal capabilities;
   rejected by `_no_audio_payload` at `/response/audio` before response-ID
   assignment in the parser.

## Actual live failure and classification

Normalized adapter failure: **`audio_payload`**.
The evidence wrapper recorded **`FAIL_FORBIDDEN_OUTPUT`** because its heuristic
counter also classifies every nonempty `audio` field outside session config as
payload. This label is the raw machine outcome, NOT proof of generated audio.

What the saved projection establishes for `/response/audio`:

- present;
- Python/JSON object (`dict`);
- one member;
- nonempty;
- contents/member names NOT retained by the bounded projection.

**Actual audio generation is NOT established.** The object could be response
configuration rather than PCM/base64 payload. Its type and location alone do
not prove either interpretation. No raw audio was decoded, played or saved.
`audio_payload_fields=1` in the raw report means one field triggered the
key/emptiness heuristic; it must NOT be reported as one proven audio chunk.

Classification: **F — UNKNOWN**, specifically the semantic role of the
response-level audio object. The exact executed failure boundary is proven;
whether this is a legitimate provider configuration rejected too broadly or an
actual prohibited payload cannot be decided from the saved projection.
No corresponding frozen-runtime regression was observed.

The single missing observation is the bounded structural contents of
`response.created.response.audio` (its member names/types and whether a payload
leaf exists), not another generic conversation/voice investigation. It was not
preserved and must not be reconstructed from memory. No second request or
automatic parser correction is authorized/executed by this outcome.

## Output / cleanup / timing

- Text delta count observed before abort: **0**.
- output_text.done / structured candidate: **not reached**.
- Admission: **not reached**, report flag false.
- Audio delta count observed before abort: **0**.
- Actual audio payload: **unproven**, as explained above.
- Tool/function markers observed: **0**.
- Planner, ToolGateway, DCS, SRS, SpeechKit/TTS calls: **0**.
- Outbound response.cancel was not sent: rejection occurred before parser
  response-ID assignment. The request-scoped transport was closed.
- Transport closed: true; owned tasks 0; busy false; remaining async tasks 0;
  new threads remaining 0.

Offsets from operation start (ms):

| Boundary | Offset |
|---|---:|
| connect complete | 1359 |
| session.created | 1437 |
| session.updated / response.create | 1641 |
| user-item acknowledgement | 1906 |
| rejected response.created / cleanup start | 1937 |
| cleanup complete | 2234 |

response.create to rejection: 296 ms; cleanup: 297 ms within existing 300 ms
close budget. No generated-text completion or physical response latency exists.

## Evidence preservation / stop

Unmodified machine report:
`C:\Users\Алексей\Documents\ORION-Builds\level0-event-contract-20260909\structured-provider-result.json`

SHA-256 `17DC876913337185C1430E4E3DC82BF889B69FF8D150FD05574D385F999EF81B`.
One-attempt latch `structured-attempt.json` and standalone harness
`structured_gate.py` are beside it, outside the repository. No credentials,
auth headers, raw provider bodies or raw audio were retained in the report.
The raw report is preserved despite its overbroad payload label; this document
provides the evidence-based interpretation without rewriting that record.

No changes to production/tests after live failure. This receipt only records
the outcome. No retry, fallback, new live investigation, build/install,
commit/push, successful checkpoint or voice-host integration.

The next decision must use this real provider-boundary evidence. Do not claim
PROTOCOL + PROVIDER CONTRACT VALIDATED. Host integration remains pending and
must not begin from this failed provider gate.

LEVEL-0 TYPE GATE CORRECTED — PROVIDER GATE FAILED
