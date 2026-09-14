# ORION Project Memory — current state only

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
