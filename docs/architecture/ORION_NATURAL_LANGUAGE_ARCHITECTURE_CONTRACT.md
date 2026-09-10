# MANDATORY ARCHITECTURE CONTRACT — READ BEFORE ORION CHANGES

**Stable marker: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1`**

Approved by explicit user instruction on 2026-09-10 (Europe/Moscow).
Canonical path: `docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md`.
Status: mandatory product architecture and Astra/Codex governance; **not a claim
that the target architecture is already implemented**.

MUST, MUST NOT and STOP are binding. This is the single canonical contract.
Project Memory, recovery records and agent instructions reference it; they may
not silently supersede it. Historical bounded slices describe implementation
and evidence, not the final language interface. Explicit user approval is the
only authority to change this contract (section 19).

## 1. Product identity

ORION is an AI copilot / conversational assistant inside DCS, NOT a voice-command
utility or a library of mandatory phrases. Users MUST be able to speak naturally
without memorizing command syntax, intents, capability IDs or phraseology,
unless explicitly choosing structured radio phraseology mode. Natural Russian
and English remain product requirements; current language coverage must be
reported honestly rather than confused with the target.

## 2. Natural-language first

User language is open and natural. Deterministic recognizers, regex and phrase
tables are permitted only as latency/reliability FAST PATHS. They MUST NOT define
the set of language ORION understands. A fast-path miss MUST NOT by itself mean
final UNSUPPORTED. Protected output wording does not impose input grammar.

## 3. Semantic ingress

After protected/obvious fast paths, unresolved user language MUST reach the AI
Natural-Language interpretation layer. AI determines the meaning and needed
internal role/capability; Core retains admission and execution policy. A growing
local social/aircraft/ownship whitelist MUST NOT gate this semantic route.
An aircraft-only Interpreter's `not_applicable` means that slice cannot handle
the request; it MUST NOT terminate general semantic handling or conversation.
True ambiguity, unsupported capability, policy denial and provider unavailability
must remain distinguishable; none authorizes fabricated facts or actions.

## 4. Role separation

| Role | Responsibility |
| --- | --- |
| Conversation | Natural dialogue and non-authoritative discussion. |
| Interpreter | Semantic understanding and capability selection/proposal. |
| Core + WorldModel + ToolGateway | Authoritative DCS facts, permissions, freshness/provenance and action authority. Core admits; WorldModel represents owned facts; Gateway enforces permitted access/execution. |
| Planner | Complex reasoning, multi-step tasks and tool orchestration; not mandatory for simple facts. |
| Deterministic fast paths | Optional latency/reliability optimization, never the language boundary. |

Roles do not require separate serial model calls. Sharing a provider/model does
not merge authority or turn interpretation into a Planner run. Preserve the
approved domain, interaction, presentation and voice transport owners.

## 5. AI understands; Core knows/executes

AI may determine WHAT facts/actions/capabilities are needed, but MUST NOT invent
authoritative simulator values, grant permissions or bypass Core admission.
Semantic needs such as `ownship.position`, `ownship.heading`, `aircraft.identity`
and `fuel.state` must resolve through the actual Core catalog and authoritative
WorldModel/ToolGateway results. These examples are not assertions that identically
named tools are already registered or exposed. Core owns name/schema mapping,
availability, actor/session permissions, freshness, provenance and fact binding.
Unknown, stale, restricted and unavailable data MUST NOT become guessed current
facts. Actions and ATC authority remain domain/Core-owned, with applicable
confirmation and lifecycle controls. Natural wording cannot certify a value.

## 6. General conversation

Pure conversation MUST NOT require predefined local templates. «поговори со мной»,
«как настроение», «что думаешь о сегодняшнем полёте», «как тебя зовут» are
conceptually valid free dialogue. They are illustrative acceptance cases, NEVER
required production grammar entries. Discussion of a flight must not imply
access to unobserved flight facts; factual claims still follow section 5.
A local social constant is not evidence of a Conversation provider invocation.

## 7. DCS-aware natural language

Natural DCS questions MUST work semantically, independent of exact wording:
«где мы?», «какие у меня координаты?», «куда смотрит нос?», «как у нас с топливом?»,
«на чём мы сегодня?». AI selects the required meaning/capability; Core returns
truth. Ambiguous meanings require clarification rather than guessed location,
heading or availability. Adding these examples to recognizers does not meet
this requirement. Expose only supported facts; label implementation gaps.

## 8. Mixed turns

The target MUST support dialogue plus DCS facts in one turn, for example
«Как дела? И где мы сейчас?». Internal routing MUST NOT force users to split
the request. Compose the admitted conversational and authoritative components
under the approved response ownership and fact boundaries, without competing
responses or conversational invention of simulator values.

## 9. Context

ORION MUST own explicit Interaction/Conversation Context across turns, including
referential follow-ups such as «Где мы?» → answer → «А курс?».
Provider hidden session history is NOT the authoritative memory owner.
Context can resolve references and intent; current simulator facts MUST still
be refreshed from Core under freshness policy. Provider item isolation/cleanup
is compatible with explicit ORION-owned context and is not permission to remove
conversation continuity or reuse stale simulator values.

## 10. Multi-capability and reasoning

A natural turn may require several Core capabilities. Multiple simple facts do
not automatically require Planner. Use Planner when actual reasoning or
multi-step orchestration is needed, with scoped tools and Core authority.
Do not create unnecessary LLM-hop chains or repeat the same authoritative read
solely because several selected facts can come from one valid snapshot.

## 11. Latency as architecture

Long-term response-start target is ideally **<1 second**, measured toward audible
response/first voice transmission, not merely first model token. For simple
factual turns after fast-path miss, allow **at most one lightweight AI
interpretation hop**. No routine classifier → full Planner → formulation → judge
chain or other avoidable multi-second AI path for simple facts is acceptable.
Keep fast paths for low latency. Current Interpreter measurements demonstrate
sub-second feasibility; TTS latency is a separate debt, not justification to
narrow language or claim the end-to-end target has already been reached.

## 12. No template drift

Do NOT expand natural-language coverage primarily through regex, synonyms or
phrase whitelist entries. Such additions are allowed only as measured fast-path
optimizations **after the semantic route already works**. If phrase-list
expansion is proposed as the main NLU solution, Astra/Codex MUST STOP before code.
Renaming a recognizer a semantic validator does not exempt it from this rule.

## 13. No capability-by-capability voice-command product

The internal typed capability catalog may expand while user language stays open.
Do NOT turn each capability into its own mandatory voice intent grammar. Bounded
typed outputs and permissioned tools are compatible with open natural input.
An incremental capability implementation MUST NOT redefine the whole product
as its current bounded slice.

## 14. Preservation

New work MUST NOT make previously accepted/field-validated capabilities
unreachable, shadowed or silently unsupported. Source-code invariance is
insufficient: production-host reachability matters. Preserve approved
Conversation, Interpreter, Core, Planner, ATC, Hybrid, ownship and voice transport
roles. Keep evidence levels separate: historical field proof, current host
reachability, offline/provider checks and future coverage expectations.
Do not promote historical fixture-backed ATC behavior to live action authority.
Any proposed removal or shadowing triggers section 18; language gaps must not
be misreported as proven regressions or as accepted final product restrictions.

## 15. Field acceptance

Natural-language acceptance MUST use held-out phrases NOT encoded in production
grammar. If a field test passes only after adding the test utterance or synonym
to local grammar, the Natural-Language test is **FAIL**. Preserve input/evidence
and inspect actual routing, role calls, Core admission/facts and voice completion;
an answer alone does not prove the semantic or Conversation route.

Required test families for target acceptance:

- pure conversation;
- one DCS fact;
- alternate wording of the same fact;
- multiple facts;
- mixed conversation plus fact;
- contextual follow-up;
- reasoning;
- operational request with domain/Core authority;
- true unsupported and clarification cases.

Record latency and preservation through the real production host. Offline mocks,
provider gates, completed SRS transmission and user-confirmed audibility are
different evidence levels. This contract creates no new executable test gate
and does not claim these families currently pass.

## 16. Current verified state — 2026-09-10

Build `2c58b3752ad79a639db6e406e2eeb1927b21086d` physically proved:
Natural Language → AI Interpreter → typed `aircraft.identity` → Core authoritative
DCS fact → TTS → SRS. User confirmed hearing «Вы находитесь в F/A-18C Hornet.».
Evidence for «что у нас за машина» shows Interpreter user path including Core
admission **602.224 ms**, separate isolation **~266 ms**, authoritative
`orion.world.ownship.get` with `FA-18C_hornet` from `dcs_export`, and 91 completed
frames. TTS first PCM was ~2110 ms; PTT END → first TX ~3125 ms. Isolation is
separate from the current response's critical path; do not add it to 602 ms.

**GENERAL FREE CONVERSATION FIELD FAIL:** the later six-turn, 195-event session
had **Conversation=0, Interpreter=5, Planner=0**. Among its five conversational
turns only «как дела» answered, with Local Hybrid FREE_ONLY constant
«Всё нормально, я на связи.» (58 frames), not Conversation provider generation.
«поговори со мной», «как настроение», «что думаешь о сегодняшнем полете»,
«как тебя зовут» went Interpreter → `not_applicable` → final UNSUPPORTED and
silence. The sixth turn, «что у нас за машина», separately succeeded through
Interpreter → Core (91 frames). Thus two answers total, not one in six.
Root cause: template-gated routing / narrow Conversation eligibility, not
Yandex availability, TTS or SRS. The Conversation provider was never reached.

Earlier bounded Conversation FIELD PASS remains valid for its admitted class;
it does not establish general dialogue. The old pre-field Interpreter report
is superseded only in field status by this later evidence. **Current ORION is
NOT yet the target product despite the successful aircraft Interpreter proof.**
See the [recovery/history record](../history/2026-09-10-natural-language-architecture-contract.md)
for sources, identities, evidence limits and historical links. ZIP build identity
comes from its summary, not an independent installed-binary hash; audibility
confirmation comes from the user, not a listener recording in the ZIP.

## 17. Astra/Codex mandatory pre-flight check

Before editing in EVERY future task affecting architecture, routing,
Conversation, Interpreter, Planner, capability exposure, Core/ToolGateway or
voice-host integration, Astra/Codex MUST:

1. Recover actual branch/HEAD/worktree state and read this canonical contract,
   Project Memory and the latest relevant development/recovery evidence.
2. Cite the exact canonical path and `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1`.
3. State explicitly how the proposed change complies with EACH relevant
   numbered invariant, including authority, semantic ingress, context, latency
   and preservation where affected. A generic “compliant” assertion is inadequate.
4. Identify potential conflicts; say explicitly when none were found. Describe
   preservation/acceptance evidence needed without claiming unperformed checks.
5. If any conflict exists, or the task would narrow natural behavior into
   templates/mandatory syntax, **STOP before code** and follow sections 18–19.

Task-start instructions and recovery handoffs MUST point to this file. Missing
contract access is not permission to substitute remembered wording: recover the
canonical file before editing. Prior task-specific Guard OFF statements do not
disable this pre-flight or authorize deviations from this contract.

## 18. Hard STOP policy

Astra/Codex MUST STOP, without implementation, if proposed work would do any of
the following without explicit user authorization for the architecture deviation:

- make predefined phrases the primary language interface;
- treat a fast-path miss as final UNSUPPORTED before required AI semantic handling;
- block general conversation behind a narrow phrase whitelist;
- let AI invent authoritative DCS facts or execute without Core admission;
- route all simple questions through full Planner/multiple LLM hops with avoidable latency;
- make provider hidden history the owner of ORION context;
- remove or shadow an accepted capability;
- rebuild SRS/STT/TTS/Launcher to solve a routing/NLU issue;
- materially change approved role separation;
- contradict this contract in any way.

STOP report: cite the invariant, describe the proposed conflicting behavior and
user-visible impact, and request an explicit architecture decision. Do not code
around the conflict, relabel the deviation an optimization, or treat silence,
an old slice restriction or a generic feature request as approval to weaken it.

## 19. Change control

This architecture contract may change ONLY with explicit user approval.
Astra/Codex MUST NOT reinterpret, weaken or silently supersede it through another
document, task prompt, implementation or agent instruction. Apparent conflicts
require an explicit architecture decision before implementation. Record approved
changes with the decision, affected invariants and history reference; retain
prior versions in Git. A proposed amendment is not effective before approval.
This user-approved V1 records the current decision; it does not authorize runtime
implementation, new provider configuration, builds, installers or transport work.

## 20. Header, integrity and recovery

Keep the banner, canonical path and stable marker at the top. Use Git commit/tree
identity plus a SHA-256 of the canonical file for recovery verification; record
the digest in the commit receipt, not as a self-referential hash inside this file.
The marker identifies the policy and is not itself a checksum.
Maintain mandatory references in root `AGENTS.md` and `docs/ORION_PROJECT_MEMORY.md`,
and link the current development/recovery history. Keep one canonical contract,
not duplicated divergent policy copies. Before working from an older branch,
recover this policy explicitly; its absence there does not authorize bypass.
