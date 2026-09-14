# ORION Project Memory — current state only

## Latest Foundation update — Step 4 safe facts, 2026-09-14

Parent `8ddc0422197a8adbe88209c0d7adc4c6301f42c4` (Steps 1/2/3 committed).
[Step 4 A–II record](history/2026-09-14-foundation-step4-fact-surface.md):
233 inventory records, 10 exposed concepts. TAS/vertical speed/AGL require
explicit direct-source quality, not fallback zeros. Fuel remains explicitly
SEMANTICS_UNCERTAIN: documented kg versus historical fractional Hornet behavior,
no trusted denominator/internal-external/module normalization. No guessed fuel.
Bounded free-text capability gaps; existing natural coordinates and bounded
summary preserved. One eight-operation Yandex semantic session PASS, no retries;
fact/summary user path750–953ms including context ACK, cold1454ms separately.
Final full regression3443 PASS/five unchanged baseline failures/one skip.
No TTS/SRS/Launcher/provider-owner change or build.
Decision A, one authorized commit/push after final scope/remote checks.
Foundation NOT FIELD PASSED. Step 5 requires separate authorization.
Older “not started/uncommitted” paragraphs below are historical checkpoint status.

## Latest Foundation update — Step 3 delivery, 2026-09-14

Steps 1/2 are committed; Step 2 checkpoint is `152a2f22c281fc31ab00daf99f4e171af88c05f9`.
[Step 3 A–T record](history/2026-09-14-foundation-step3-tts-delivery.md):
real TTS reproduced the local 1 MiB receive limit; finite 3 MiB envelope and
explicit generator cleanup repaired, lower-level causes preserved safely.
The historical partial delivery first failed at SRS RX collision/origin guard,
NOT proven TTS backpressure; sender remains unknown. SRS behavior unchanged.
3325 offline PASS, five unchanged baseline failures, one skip; three real TTS
turns pass through real PCM/paced offline sink, no live SRS/acoustic acceptance.
Decision A, one authorized Step 3 commit/push after final scope checks; no build.
TTS first PCM1.906–2.609 sec remains latency debt. Product FIELD FAIL unchanged.
Step 4 is NOT started and needs separate authorization. User data retained.
The precommit/gate-failure paragraphs below are preserved historical snapshots,
not the current commit status or renewed instructions.

## Historical Step 2 update — context application, 2026-09-14

[Context proof and bounded repair](history/2026-09-14-context-application-proof.md):
one override-only synthetic probe did not use the nonce; request-owned exact
session.update/ACK binding plus cleanup restored nonce use and RU/EN continuity
on the unchanged ten-turn gate. Same Yandex/prompt/ORION context; no provider
switch. 3306 offline PASS, five baseline failures, one skip. Uncommitted; review
before commit. No build, physical acceptance, TTS work or Step 3. Earlier failed
gate below remains historical evidence, not the latest component verdict.

## Current execution update — Foundation Step 2, 2026-09-14

Step 1 is committed at `4b5a46959c241eec6ef8391ee52de4da93f3dc0f`; the older
precommit labels below are historical. Step 2 role/context corrections are
UNCOMMITTED. [Full A–U record](history/2026-09-14-foundation-step2-conversation.md).
Offline mechanisms passed; one ten-turn current-Yandex gate had no retries and
validated controlled recovery, but RU/EN continuation QUALITY FAILED despite
available explicit context. Provider-side context application versus model
behavior remains unresolved. STOP; no provider switch, commit, build or Step 3.
TTS/SRS/facts and physical product FIELD FAIL unchanged. User data preserved.

## Current execution update — 2026-09-14 Foundation Step 1

Governance is committed at `be413a802fe4d84ac140db248219b3e450cbb8b4` on
`codex/general-natural-language-ingress-tranche1` in `ORION-level0-conversation`.
The earlier draft/commit/next-task notices below are the preserved governance
snapshot, not the current authorization. The user approved the Foundation plan
and Step 1 routing implementation ONLY. [Step 1 record](history/2026-09-14-foundation-step1-routing.md).

Step 1 is uncommitted: ownship and pure-aircraft full-turn fast paths remain;
all clean misses/partial/social/mixed input reaches one General entry intact.
Local social/mixed helpers remain in code, not production language admission.
Mixed execution, Conversation quality/context recovery, fact expansion and TTS
repair are NOT implemented by this step. Current product FIELD FAIL is unchanged.
No provider, build, install, DCS/SRS/PTT or new acoustic proof. Await user review
before commit or Step 2; do not start the next step automatically. Original user
data bytes are preserved; tests appended events (retained, not discarded).
The user profile and canonical contract are byte-identical.

Updated 2026-09-14. Governance/recovery proposal in worktree; NOT COMMITTED.
This file is an index of current truth, not a history archive.

## CURRENT PRODUCT STATUS

Latest user blind field verdict: FAIL.

- General free Conversation: FIELD FAIL / effectively not working as a reliable product.
- General natural-language DCS access: FIELD FAIL.
- Reliably user-usable DCS facts: effectively aircraft identity only at present.
- Position/heading: historical/individual technical successes, NOT a reliable
  general DCS knowledge interface.

- TTS delivery: FIELD FAIL / unstable.
- Semantic owner recovery: observed successful after validation failure.
- ATC/AWACS/JTAC/AAR expansion and persistent user context/Gate C: deferred
  until the base AI-to-DCS foundation is field-passed.

Twelve completed transmissions in the latest test do not make twelve correct
answers or a product PASS. See [field evidence](history/FIELD_EVIDENCE_INDEX.md).

## CURRENT CANONICAL ARCHITECTURE

[ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1](architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md)
is unchanged. Natural input; one lightweight semantic hop for simple facts;
Core/WorldModel/ToolGateway truth and permissions; explicit ORION-owned context;
protected output does not impose input grammar. No raw telemetry-to-speech path.
The contract describes approved intent, not all currently implemented behavior.

## CURRENT DEVELOPMENT FREEZE

Documentation/governance only under the 2026-09-14 user request.
No runtime, configuration, tests, provider/runtime prompts, mappings, TTS/SRS,
packaging or workflow changes. No live providers, DCS/SRS/PTT, build or install.
No commit/push before explicit review. The Foundation plan is a proposal, not
implementation authorization.

## CURRENT KNOWN FIELD FAILURES

Latest session:

- Seven TTS gRPC RESOURCE_EXHAUSTED failures before any PCM; zero TX frames.
  Server quota/billing versus client receive-message limit is NOT established.

- One partial response: 860438 PCM bytes produced, 89 frames sent, RuntimeError;
  exact exception message/cause absent from the saved ZIP.

- CAPABILITY_GAP.need=weapons violates the closed schema; literal_error.
- Request for another joke received the exact same provider-generated joke.
- META identity selection differed between two similar aircraft questions.
- Mixed/reasoning/domain semantic variants remain declared but not implemented.
See [contradictions](history/ORION_CONTRADICTIONS.md) and
[foundation audit](history/2026-09-14-foundation-recovery-audit.md).

## CURRENT FIELD-PROVEN FUNCTIONS

Effectively aircraft identity is the only currently reliably user-usable DCS fact.
Its AI interpretation → authoritative Core ownship → TTS/SRS proof was
user-confirmed at 2c58b37; this does not certify general DCS access or TTS reliability.

Historical ownship, social and radio successes remain in the
[Field Evidence Index](history/FIELD_EVIDENCE_INDEX.md), not in the current
product-capability list.

## CURRENT RECOMMENDED NEXT TASK

User review of these governance corrections. Before any runtime recovery work,
present a one-page minimal architecture for explicit user approval: one general
semantic entry, ORION-owned context and one response owner for dialogue and/or
authoritative Core facts, including mixed turns. Foundation is a prerequisite,
not full V1 completion; its safe fact surface is not limited by today's seven
selectors. No runtime task starts automatically.
See [audit sections R–Y](history/2026-09-14-foundation-recovery-audit.md#r-foundation-call-graph--minimal-target).

## CURRENT BASELINE / BRANCH / HEAD

Authoritative audited feature line:

- Worktree: C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation
- Branch: codex/general-natural-language-ingress-tranche1
- HEAD: 5c9ab2440cc8bf9dfb2ea422b88ef5c498e53314
- Tree: 72707938febee57e181320d98bbac375f0809c76
- Before preparation of the governance draft, tracked files and index were clean;
  untracked data/ already existed. The current uncommitted governance/history
  draft is preserved; the index remains empty and data/ is unchanged.
- Runtime baseline unchanged by this documentation draft.
- GitHub main is a7757a3, not this feature line. Current HEAD and parent 7b6981a
  are not reachable from advertised origin branch tips checked 2026-09-14.
  Do not call them publicly published; this audit did not fetch or push.

- Ambient desktop checkout ORION is dev/adr004-post-389 at 42520a5;
  it is historical context, not the latest physical build source.

## LATEST PHYSICAL EVIDENCE

C:/Users/Алексей/AppData/Local/ORION/runtime/test-evidence/ORION-Test-Evidence-20260910-213600.zip

SHA-256: 7e8971fbc4a1e53b196aa0321d3d765666f7f16950c86a445dda411d268aa2c7
Session: b09b2c3176734601991bfc67000266e0.
Summary build: 5c9ab2440cc8bf9dfb2ea422b88ef5c498e53314.
Actual time: 2026-09-11 00:31:01–00:36:00 Moscow (filename uses an earlier date).
841 events; dropped=0; 20 STT finals; 12 completed / 8 failed transmissions.
ZIP identity is reported runtime identity, not independent EXE attestation.
No RX/TX WAV; exact response/TTS texts exist in slice events despite the separate
assistant transcript counter being zero. User verdict: «это опять провал».

## RECOVERY LINKS / HISTORICAL PRESERVATION

- [Chronological history and source pointers](history/ORION_HISTORY_INDEX.md)
- [Field evidence, with scope and unknowns](history/FIELD_EVIDENCE_INDEX.md)
- [Unresolved contradictions](history/ORION_CONTRADICTIONS.md)
- [Complete audit A–BB and preserved previous Project Memory](history/2026-09-14-foundation-recovery-audit.md)

The previous 84661-byte Project Memory is retained at immutable Git object
5c9ab244:docs/ORION_PROJECT_MEMORY.md and reproduced as historical text in the
audit appendix. Its old main-first rules, pending-field notices and proposed
next stages are NOT current instructions. Nothing in that history is erased.
