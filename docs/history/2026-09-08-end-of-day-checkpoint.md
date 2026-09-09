# ORION end-of-day recovery checkpoint — 2026-09-08

ORION ARCHITECTURE GUARD: OFF

## Recovery status supersession — 2026-09-09

The [full Yandex Support reply and recovery update](2026-09-09-yandex-support-DT403405.md)
supersedes the waiting status below. **ORION_EOD_20260908_AWAIT_DT403405 is
CLOSED AS A BLOCKER**; question 2 is escalated and remains **non-blocking pending
clarification**, not a closed ticket. Text-only generation is confirmed despite
the multimodal session envelope; audio chunks arrive only through
`response.output_audio.delta`. Its absence reliably indicates no audio payload.
Use `response.output_text.done` as authoritative final text; terminal output
may retain an audio-shaped wrapper/transcript with `audio: null`.

Current recovery / next-step marker:
**ORION_20260909_LEVEL0_CONVERSATIONAL_HANDSHAKE_EVENT_CONTRACT_CORRECTION**.
Next step: **Level-0 Conversational Handshake/Event Contract Correction** in a
separate bounded task. Runtime and Level-0 code remain unchanged; no provider,
DCS/SRS/PTT, build/install or production merge is performed by this update.
Approved authoritative source labels remain silent by default.

The original checkpoint below is preserved as the state at end of 2026-09-08.
Its waiting language and protocol uncertainty are historical, not the current
blocker or next-step instruction. Original checkpoint commit:
`8dc2f215e8680f81d76c5bb192d22ed18179ae5c`, also the verified parent of this
docs-only support update on `codex/eod-20260908-checkpoint`.

## Historical EOD record — 2026-09-08

**THEN STOPPED — AWAITING PROVIDER CLARIFICATION.** This is a preservation/history
checkpoint, not a production release or Level-0 integration. The session may
finish after midnight; the workday recorded here is 2026-09-08 Moscow.

## Exact recovery anchors

| Role | Branch / commit |
|---|---|
| Field-validated Hybrid local routing runtime | `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4` |
| Local-routing offline/package documentation | `8f8009c5e7e00eb3c59eb0247156b005dd932729` |
| Successful Hybrid field documentation freeze | `dca668d530dc6cbc4de05064400b22c2216ada3f` |
| This docs/evidence recovery branch | `codex/eod-20260908-checkpoint`, parent `dca668d530dc6cbc4de05064400b22c2216ada3f` |
| Preserved unwired Level-0 experiment | `codex/level0-conversational-voice`, `9ccab967dfe018f29302fb87e8105a4bb11a89de` |
| Earlier Hybrid build checkpoint on a side branch | `codex/hybrid-aircraft-identity-after-cleanup`, `260434f20e5cb962e558a78bcd181efcfaa7b9ac` |
| Separately preserved latency history | `codex/latency-profile-20260908`, `92a019f31a57d4758d1133aeaf0ba872f4b64508` |
| Broader historical canonical docs | `dev/adr004-post-389`, `42520a57b01cd314978bcb51bdf4bbc75b38c156` |
| Early accepted Qwen Realtime conversation | Build #402, `4e8b49afff0b8f5d1ec1a008f09f79ae08e1a546` |
| Historical Yandex text presenter / selector | `9ed45bbd820e60784d83c357a248d3b95dae765a` / `8182e892a951afe7f239f3f7f5a2231415c6d57d` |

The commit containing this file is the documentation checkpoint SHA; resolve it
with `git log -1 --format=%H -- docs/history/2026-09-08-end-of-day-checkpoint.md`.
Exact final branch HEADs and push verification are also delivered in the local
recovery receipt. No production/main merge is authorized or performed.

## Sources, precedence and preservation

Repository contents, exact commits, canonical documents and saved evidence are
the source of truth. The complete early-conversation audit was recovered from
the saved Codex final response at 2026-09-08T19:37:25.486Z (27,833 characters),
not the truncated ChatGPT preview. The protocol and submitted-support reports
come from messages `4c35cb04-4262-40ed-9f37-28522ad20ce6` and
`adbf61b2-6555-4c64-85e3-c2a55e149f84` of conversation
`6aa004f2-ba20-83eb-b399-889bfe57ea89`. The audio-envelope audit is the saved
`Pasted text.txt` attachment. They are historical records, not fresh execution
instructions; their old next-step/status statements are superseded by this file.

Original reports and evidence are in [2026-09-08](2026-09-08/README.md).
`evidence-manifest.json` records original paths, sizes and SHA-256. Archive-scoped
Git attributes disable newline conversion so saved evidence remains byte-exact.
The original artifacts remain in place. No reset, stash, clean, rebase, deletion
or overwrite of existing work was used.

The recovery lineage has an older Project Memory than the broader development
branch. Preserve both: this branch's pre-checkpoint memory remains at `dca668d5`;
the `42520a57` memory, master architecture checkpoint, decision register,
development policy and IA/radio history are copied unchanged under
`canonical-snapshots/dev-42520a57/`. Their C3/C4 position is historical and must
not replace today's explicitly field-validated recovery baseline. D71–D75 and
the full-product intent remain visible; no wholesale runtime merge was made.

## Today's development history

1. Truthful voice STOP (`7b041d64b663fad1862c14d960c2b9c52cab0c99`) and bounded
   Qwen Planner cleanup (`474d11bc349ce70986524faf9b53ed7968e25c24`) precede the
   Hybrid line. They remain in checkpoint ancestry; no further lifecycle change.
2. Hybrid aircraft work progressed through `4ca5eff`, Core-derived route
   correction `013a36a956cb67565290c506c0e7bda0a89fdf24`, and local routing
   `f0c9e364`. Earlier decomposition/provider attempts are not substitutes for
   the later field success. All six saved field ZIPs from today are retained.
3. Local Hybrid field success and frozen ownship regression were documented at
   `dca668d5`. Installed runtime was not changed by this checkpoint.
4. Level-0 contracts, bounded social-support admission, turn-scoped transport,
   isolated presentation and offline tests were drafted but never wired into
   the host. First live prerequisite attempt stopped before text input.
5. Historical recovery confirmed actual early free generative voice conversation
   through Qwen Realtime and later Yandex, rather than treating earlier fixed
   Core small-talk phrases as generative conversation.
6. One separate Yandex text protocol probe generated text; its unexpected audio
   envelope left the required contract unresolved. The later read-only audit
   found documentation/observed-protocol conflicts and evidence-projection gaps.
7. Support ticket DT403405 was submitted. No provider engineering clarification
   is present in the saved record. End-of-day work preserves that stopping point.

The separate latency profile records response-start intervals 3389.0998 and
3039.4132 ms, dominated by TTS RPC-to-first-PCM intervals 2898.5331 and 2537.8177 ms.
These historical measurements do not authorize optimization or prove <1 s
physical end-to-end voice latency. The profile branch is already on GitHub.

## Hybrid field proof and identity limitation

Successful ZIP: `ORION-Test-Evidence-20260908-173035.zip`.
SHA-256: `8E85904B00D198D5556D11027653A58CDB36B0305618682A85CF689EA0D25272`.
Test session `110867ca9e7b4cc990b326bf54035dee`; runtime session
`b3bafadb7bf346a380193a356cebfef0`.

Mixed turn `ebf02d5c-d396-494c-945a-3c2eb00a771b`: FINAL
`добрый день в каком самолете я нахожусь`; local decomposition and Core route
`FREE_PLUS_AIRCRAFT_IDENTITY`; zero provider calls; one completed
`orion.world.ownship.get` authoritative receipt for `FA-18C_hornet`.
Finalized/TTS text: `Добрый день! По данным DCS, вы находитесь в F/A-18C Hornet.`
TX completed, 143 frames; explicit user acoustic confirmation is preserved.
Frozen ownship turn `6827c2d1-6d58-4a4d-b007-4a93eec2267f` completed with
385 frames, zero provider calls; no missing numeric text pair is reconstructed.

The ZIP says `orion_build_sha=unknown`. Later installed/artifact hash matching
corroborated source attribution to `f0c9e364`; it does not repair the original
session's missing identity. Keep this limitation with every field-proof claim.

## Confirmed early free-conversation history

Build #402 / `4e8b49a` was explicitly accepted as a Qwen Realtime voice baseline
on 20 August. Earlier #389 already had audible generative output and later a
short dialogue, with latency/stuttering/crash limitations. Exact first full
question/answer pairs are not available. Fixed Core dialogue from early August
is not evidence of free generation. Qwen Realtime speech-to-speech is distinct
from the later Qwen Planner through Yandex AI Studio.

The 24 August YandexRealtimeTester diagnostic preserves STT `привет как дела`
and generated ` Привет! У меня всё хорошо, спасибо. А как ваши дела?`, plus
`расскажи что ты умеешь` and a generated capabilities response. It records
completed response `resp_30b47cc397f24ade9fc8bb3f42884c5e` and 418,420 decoded
audio bytes for the first example. This is tester/provider and playback evidence,
not an assertion that every later production constraint was already satisfied.
The full report preserves Data Export provenance, message IDs, hashes and limits.
Historical success neither authorizes rollback to Qwen nor proves the current
Level-0 protocol/admission/lifecycle contract.

## Level-0 prerequisite status

**PARTIALLY VALIDATED / NOT INTEGRATED / NOT BUILT / NOT FIELD READY.**
The four modules, two tests and original stop report are preserved unchanged in
commit `9ccab967dfe018f29302fb87e8105a4bb11a89de`, plus an explicit archival-status
document. `level0-original-files.json` lists every original file and its hash;
all seven match the protocol probe's prior source snapshot.

Saved prior offline report: 957 passed, 4 skipped; later prerequisite-file run
179 passed includes supplementary tests and is not 179 additional unique cases.
These runs were not repeated for the preservation commit. Closed-language
social-support admission is not general free conversation or an arbitrary-prose
safety proof. Live SocialDraft generation/variation and installed lifecycle
remain unproved. The later plain-text probe does not close those gates.

First probe at 19:01:02.236089 UTC, interaction
`4ef75b7d-6774-459d-b535-fd0360e567a1`: `nontext_session` after session events;
zero user items, zero response.create, 1594 ms including cleanup. Exact rejected
modality value was not saved. Keep the unchanged strict predicate for comparison.

## Yandex protocol, audit and support blocker

Evidence: `provider-protocol-result.json`, SHA-256
`C45012C772FBB45D5B5B1C0B30135401548046D08A5127980B7A90A1088E6DAD`.
Some earlier prompt copies omitted one `5B` in the hash; this full value was
recomputed from the original file and is authoritative.

Model `speech-realtime-260528`; endpoint `wss://ai.api.cloud.yandex.net/v1/realtime`;
session `4a11ff2e5d7a`; response `resp_3d259f4f9f4d4806b03c0792a9b64fbb`.
One text input `Что-то сегодня полёт тяжело идёт.`; explicit session and response
`output_modalities=["text"]`. The server returned `["text","audio"]` in session
and response acknowledgements. Raw generated text retains its leading space:
` Понимаю, бывает такое. Надеюсь, дальше будет полегче!`.

Text delta/done completed (297 ms first text, 500 ms text complete from
response.create). Audio part/terminal/transcript events occurred; zero
`response.output_audio.delta` events. Harness verdict `FAIL_UNEXPECTED_OUTPUT`;
overall protocol conclusion remains inconclusive for the required no-audio
contract. Client WebSocket/session closed, zero remaining owned tasks/new
threads; remote session destruction is not observable from the client.

Audit verdict: **YANDEX DOCUMENTATION / OBSERVED PROTOCOL CONFLICT — PROVIDER
CLARIFICATION REQUIRED**. Audio terminal markers do not by themselves prove
audio bytes. The saved projection omitted possible `part.audio` and item-content
audio/transcript values, so absence of bytes everywhere cannot be reconstructed.
Do not relabel the broad session ACK as only capability advertising: the saved
documentation audit describes it as effective configuration. Text-terminal
versus audio-shaped `response.done.output`, repeated assistant items and event
reference support-label contradictions remain unresolved. The official sources
and their 2026-09-08 access date are preserved in the audit, not re-audited here.

[DT403405](https://center.yandex.cloud/support/tickets/DT403405): **awaiting
provider clarification**. Saved status Open; automatic creation acknowledgement
is not an engineering answer. Submission click: 2026-09-08 23:22:43.647 Moscow;
server card showed 23:22 only. Category Yandex AI Studio / Question; no attachments.
Full submitted message and evidence limitations are saved. Ticket state has
not been polled again during this checkpoint.

## Approved presentation policy

**Authoritative source labels silent by default; provenance remains internal
unless explicitly requested.** Internal source, authority, freshness and exact
value binding remain mandatory. The historical spoken `По данным DCS` is kept
verbatim as evidence. Its presence is an implementation gap relative to the
approved presentation policy, not a reversal of that policy. No presentation
runtime change is made in this documentation/preservation task.

## Preservation validation and tomorrow

No provider calls, DCS/SRS/PTT/audio operations, build/install or production merge.
No existing runtime/Launcher/SRS/STT/TTS/ToolGateway/Planner edits. Only original
experimental additions are committed on their separate branch. The EOD branch
adds docs, archived probe source/results and evidence outside runtime.

Validation is bounded to Git diffs, original-byte/hash comparisons, ZIP integrity,
JSON/XML parsing, Python syntax without importing/executing probe code, archive
secret-pattern inspection and branch/remote verification. Prior test results are
historical evidence, not fresh tests. No workflow dispatch or release tag is used;
push targets are outside the saved production/build workflow branch filters.

Historical recovery marker (closed as a blocker on 2026-09-09):
**ORION_EOD_20260908_AWAIT_DT403405**. The instructions below are the original
EOD stop instructions, superseded by the dated recovery update at the top.
Read this file and Project Memory on `codex/eod-20260908-checkpoint`; inspect
actual worktree state before resuming. Obtain the full provider answer when it
arrives and compare it with the saved session/response. Without clarification,
remain stopped. Any proposed parser change requires a separately bounded task;
do not loosen predicates, integrate Level-0, switch backend or rerun probes
automatically. Preserve silent source labels and all frozen production boundaries.
