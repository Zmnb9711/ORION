# 2026-09-10 — mandatory Natural-Language contract and Astra STOP policy

Current governance/recovery entry. Explicit user request: create and commit a
permanent architecture contract after repeated drift from the approved IA /
Natural-Language product toward bounded recognizers/templates.

**Mandatory source of truth:**
[ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1](../architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md).
Read and cite it before future changes; sections 17–19 define pre-flight, STOP
and user-only change control. This documents the user's approved architecture,
not an implementation or an Architecture Guard execution result.

## Recovered state and preservation

- Actual runtime worktree: `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`.
- Actual branch: `codex/ia-aircraft-interpretation`.
- Runtime HEAD / this docs commit's parent: `2c58b3752ad79a639db6e406e2eeb1927b21086d`.
- Runtime tracked files clean; untracked `data/fa18c_value_profiles.json` retained.
  SHA-256 before work: `4975E243EE95FDF997CCC5ECC4537EAFF87947265C1C9A7F876ECF3CCEE15C1F`.
- Isolated clean docs worktree: `C:/Users/Алексей/Documents/GitHub/ORION-nl-contract-20260910`.
- Docs branch: `codex/natural-language-architecture-contract-20260910`.
- Origin: `https://github.com/Zmnb9711/ORION.git`.
- Main historical checkout remains `dev/adr004-post-389` at
  `42520a57b01cd314978bcb51bdf4bbc75b38c156` with generated/untracked artifacts.
  It is not the current recovery runtime. No reset/stash/clean or production merge.
- Earlier EOD docs branch is at `e562c648a5ee76b349c68f081e987f1cdb4d74b2`,
  based on d3245292, a sibling of the later Interpreter commit. Read its
  [checkpoint](https://github.com/Zmnb9711/ORION/blob/e562c648a5ee76b349c68f081e987f1cdb4d74b2/docs/history/2026-09-10-end-of-day-checkpoint.md)
  as history, not as the latest runtime state. No unrelated branch was merged.

The recovered line has no root AGENTS.md or CONTRIBUTING file; root AGENTS.md
is added as the mandatory startup reference. Existing Project Memory is retained
with a current precedence notice. Older bounded/no-fallback and pending-field
statements remain historical, not approved final product restrictions.

## Evidence and correction

Aircraft Natural-Language Interpreter **FIELD PASS** on 2c58b375:
archive `ORION-Test-Evidence-20260910-161956.zip`, session
`6fdc19215e7744feb10ccaf446879b18`, turn
`1d594c58-0f9f-4141-b82c-863b3057dbe9`. Unrecognized «что у нас за машина»
reached AI interpretation, typed aircraft.identity and Core authoritative
`orion.world.ownship.get`; `FA-18C_hornet`, dcs_export, fact age 0.011 s.
Finalized text/TTS: «Вы находитесь в F/A-18C Hornet.», 91 completed SRS frames.
Interpreter user path ~602.224 ms, independent isolation ~266 ms; TTS TTFA
~2110 ms and monotonic PTT END→first TX ~3125 ms. User confirmed hearing it.

General conversation **FIELD FAIL**:
`ORION-Test-Evidence-20260910-163257.zip`, SHA-256
`90A06DCB9ACF99F46DF84EE161B0A58C94166BDFF82135F886005BED9EE89A10`,
session `852052d544bf4635b153091625c792d5`, 195 events, zero dropped, six turns.
Four conversational utterances reached aircraft-only Interpreter then
not_applicable/UNSUPPORTED and silence. «как дела» produced a Local Hybrid
FREE_ONLY constant (58 frames); the aircraft question separately succeeded
(91 frames). Conversation=0, Interpreter=5, Planner=0, reconstructed from trace
and commit code. “Only how are you answered” applies to conversational turns,
not all six turns. The root cause is narrow local Conversation admission, not
provider/voice transport failure. No claim that Interpreter shadowed an already
eligible Conversation turn is supported; eligibility was narrow before it.

Earlier d324 bounded generated Conversation PASS remains valid for its one
admitted class. It cannot establish general free dialogue, and the local
«как дела» response cannot establish a Conversation provider call. The target
ORION remains incomplete. This distinction is why the permanent policy exists.

## Recovery sources consulted

- Repository Project Memory and IA-3 ToolGateway / IA-6 Router documentation;
  [warm Interpreter implementation record](../ia-warm-deadline-isolation-20260910.md).
  Its pre-field status reflects the implementation turn, superseded by later
  aircraft field evidence, not rewritten as a different implementation.
- Local IA recovery report:
  `C:/Users/Алексей/Documents/ORION-Restoration/ia-architecture-recovery-20260910/IA_RECOVERY_A-QQ.md`.
  IA-6's bounded initial slice was never the final product vocabulary. Tools,
  WorldModel and Planner exist; general normal-host semantic ingress was missing.
- Local implementation recovery report:
  `C:/Users/Алексей/Documents/ORION-Restoration/ia-aircraft-interpretation-20260910/DEADLINE_ISOLATION_FINAL_A-FF.md`.
- Full six-turn source-correlated audit:
  `C:/Users/Алексей/Documents/Codex/2026-09-10/referenced-chatgpt-conversation-this-is-an-4/outputs/ORION-all-turns-audit.md`.
- Current user request and recovered conversation
  `6aa004f2-ba20-83eb-b399-889bfe57ea89`, including aircraft audibility confirmation
  and the later six-turn correction. Prior assistant interpretations are not
  authority over the explicit current user decision.
- Earlier [product-direction record](https://github.com/Zmnb9711/ORION/blob/e562c648a5ee76b349c68f081e987f1cdb4d74b2/docs/natural-language-core-product-direction-20260910.md)
  and linked EOD preservation history. This contract makes the current decision
  mandatory; earlier “design deferred” is not a competing future direction.

Evidence limits: archive summaries attest build identity without a separate
binary hash. ZIPs contain no listener audio; SRS completion and user audibility
confirmation are distinct. This docs task reuses the source-correlated reports
and current history; it does not claim a new field run or fresh full raw-event audit.

## Scope and publication

Docs/governance only: canonical contract, root startup reference, Project Memory
notice and this history entry. No production/runtime code, provider configuration,
tests, build system, installer or DCS/SRS/STT/TTS changes. No runtime/provider/test
execution, build/install, release tag or workflow dispatch. Verification is limited
to docs completeness, links, whitespace, allowed-file diff and unchanged runtime
tree/source artifact. This policy is an agent obligation, not an implemented CI gate.

Publish the isolated documentation branch to origin without force or merging
production branches, as explicitly requested in this task. The earlier
implementation report's no-push restriction was scoped to that implementation
turn. Use a docs-only `[skip ci]` commit. The parent was not observed as a named
remote Interpreter branch; pushing this branch also makes its existing ancestry
reachable, but the new commit changes documentation only. Commit/tree SHA,
canonical file checksum, remote verification and final clean/dirty status belong
in the final receipt; obtain authoritative identities from Git, not placeholders
or a self-referential commit SHA inside this entry.
