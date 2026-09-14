# ORION history index

Latest supplement: [Step 2 context application proof](2026-09-14-context-application-proof.md).
Exact session-context ACK/clear correction; nonce and unchanged RU/EN gate
continuity demonstrated. Same provider/prompt; uncommitted, no field/build/Step 3.

Latest: [Foundation Step 2](2026-09-14-foundation-step2-conversation.md), parent
`4b5a469` (committed Step 1). Uncommitted role/context correction; offline PASS,
one Yandex gate QUALITY FAIL in RU/EN continuity. No commit/build/Step 3.
Earlier Step 1 precommit notices below are preserved historical status.

Current update: governance committed at `be413a802fe4d84ac140db248219b3e450cbb8b4`.
[Foundation Step 1](2026-09-14-foundation-step1-routing.md) is a separately
authorized, uncommitted routing-only change. Offline real-host/fake-I/O proof;
no provider or field acceptance. Commit and Step 2 require user review.
The draft labels below describe the preserved earlier governance snapshot.

Updated 2026-09-14. Proposed documentation only; NOT COMMITTED.
[Current state](../ORION_PROJECT_MEMORY.md) ·
[Audit and sources](2026-09-14-foundation-recovery-audit.md) ·
[Field evidence](FIELD_EVIDENCE_INDEX.md) ·
[Contradictions](ORION_CONTRADICTIONS.md)

Dates are Moscow where exact timestamps are known. Historical branches diverge:
chronological adjacency does not establish Git ancestry. E0–E6 are this audit's
evidence labels; older IA stage labels and L-levels retain their original meanings.

| Date | Commit / branch | Milestone and actual change | Evidence level | Field status / later evolution |
|---|---|---|---|---|
| Aug 4–5 | S2: Подключение к DCS World / Разработка ORION-000 | AI copilot/controller; bilingual natural and free conversation; ATC and mission goals. | E0, primary user decisions | Product intent, not implementation; preserved in V1. |
| Aug 6 | c247477; 3aef774/c8f1ee4 | Export prototype; bilingual keyword dialogue API and small talk. | E1/E2 | Not generative AI; later provider paths are distinct. |
| Aug 7 | 6a9594b/da4d950/d8350b2/bad5033 | Hornet cockpit raw data, mappings and diagnostics. | E1/E2 | Module-specific validation required; not general aircraft knowledge. |
| Aug 8–10 | c81320f; hardening 65/65.5 branches | Core/domain expansion and runtime hardening. | E1/E2 | No blanket ATC/JTAC/AAR field certification. |
| Aug 12–13 | fedc75f/32e1d6f/3e0edc4 | Telemetry heartbeat, last-known state and history diagnostics. | E1/E2; historical packet evidence | Earlier report records 12224 packets. Null identity after DCS exit is not proof of an identity defect. |
| Aug 13 | 7b1657c/c004345/b03bd66 | Telemetry v0.3 generic domains and safe optional export. | E1/E2 | Expanded source inventory does not imply natural-language access. |
| Aug 13–17 | native Whisper / PR104; 302d363 (#284); 135bb04 (#312) | Voice worker, Whisper/Core/SAPI and controlled shutdown. | E1/E2 plus Aug 17 user confirmation | “Все работает нормально” concerns the tested audio/STT/lifecycle scope, not proven generative conversation. |
| Aug 17–19 | 816efb0 (#389); 1963c60 (ADR005) | Qwen Realtime; removal of old Whisper/ORION-Voice fallback. | E1/E2; mixed physical results | #395 rejected; #396 choppy; #398 crashed. Not all Qwen builds passed. |
| Aug 20 | 4e8b49a (#402) | Reference-aligned Qwen FIFO playback and natural voice. | E5, scoped user confirmation | Best defensible early voice reference; exact knowledge/follow-up coverage unknown. |
| Aug 23–24 | ADR006; 1a06a09 → fae96a9 | Provider independence; initial SRS RadioInfo registration correction. | E1/E2/E5 | Tester produced two heard answers without DCS; not the current production baseline. |
| Aug 24–25 | e2bdb4a, Stage 5.1 | Settings, credentials and shared AI session lifecycle. | E1/E2; historical field reports | Controlled no-DCS proof followed by cockpit radio proof. |
| Aug 25 | f5c5d47, Stage 6A | Live FlightContext from existing Core telemetry. | S9: 16315 packets; user reports | Aircraft data existed; provider context and semantic quality still had gaps. |
| Aug 25, 18:39 | S2 user 4ba36188… | 251 → 252 silent → 251 response. | E5 | Official human cockpit-radio channel isolation; not a universal human-EAM requirement. |
| Aug 25–26 | 5896c4d; a39b289 | Stage 6A.1 semantic/context/latency work; 6A.2 transcript evidence. | E1/E2; field quality failures | Separate from the remembered MODEL C telemetry-dump incident. |
| Aug 26 | 2d90e4f, IA-0 | Neutral request, route and semantic contracts. | E1/E2 | No universal natural-language runtime wiring. |
| Aug 26 | e1dc5a6; bfa5443; 293b627, IA-1/1.1 | Presentation fidelity and hybrid SpeechKit probe. | E2/E3/E5 | 20/20 synthetic radio outputs reviewed clear; not DCS query acceptance. |
| Aug 26, 23:42 | 63448ed, IA-2 | Typed WorldModel read facade. | E1/E2 | No independent new voice field acceptance. |
| Aug 27, 00:20 | 913b8b8, IA-3 | Permissioned ToolGateway. | E1/E2 | Read-only tools, not universal language handling. |
| Aug 27, 01:00 | 7f37b4d, IA-4 | PlannerProvider contract and Core-owned tool loop. | E1/E2 | Fake-provider vertical. |
| Aug 27 | a4f9942, IA-5 | Qwen through Yandex AI Studio Responses. | E3 with synthetic state | Not a DCS/SRS field test. |
| Aug 27, 18:04–18:33 | f1a3e08 → 5c5c831, IA-6 | Controlled router and exact fact binding; provider prompt correction. | E1/E2/E3 | Health and heading/position scope; unknown requests unsupported. |
| Aug 28 | 49f083d → a955d7c | 6B.1 RadioRouter and 6B.2 SrsRadioTransportAdapter. | E1/E2/E5 | 20/20 routed synthetic TX. Older pending notices became stale. |
| Aug 28–Sep 4, historical dev | 918ee58 and later Model C/presentation branches | Mixed interaction, live golden and ATC experiments. | Mixed code/provider/field evidence | Do not import whole historical SRS/lifecycle branches; each claim needs its own proof. |
| Sep 6, recovery | aac3693 / 052fb122 / 72625dc | 7A phraseology, 7B composer, 7C protected TTS. | E2/E3/E5 | Six protected phrases heard; output proof, not open language input. |
| Sep 6–7, recovery | 9362f18 → ba627867 → ba43a2c → e753d0c → 57a563a | Realtime STT prerequisite, native External EOU, bounded Core voice. | E5, dedicated host | Two supported ownship turns and unsupported gate; not normal Launcher/general chat. |
| Sep 7, fallback | 3f364bdf → 333ca5e → 05c8327 | Old Launcher plus golden runtime; terminal observation and freeze. | E2/E4/E5, narrow scope | Preserve this working foundation, not later lifecycle redesigns. |
| Sep 8 | 18a3a79 → 92a019f | Installed latency measurement, no optimization. | E5, two turns | First TX at 3.389/3.039 s; sub-second target unmet. |
| Sep 8 | 7b041d6 / 474d11b | Truthful STOP and bounded Qwen cleanup. | E1/E2 | Lifecycle evidence, not conversational quality acceptance. |
| Sep 8 | 4ca5eff / 013a36a / f0c9e36 / dca668d | Hybrid decomposition and local aircraft routing. | E1/E2/E5, scoped | Bounded local wording, not universal language. |
| Sep 8–9 | 9ccab96 / f346e13 / 51ad57f | Level-0 text protocol, structural envelopes and social admission. | E2/E3 | Provider PASS is not voice PASS; historical support case DT403405. |
| Sep 9–10 | c444860 → d324529 | Installed bounded Conversation and STT variation handling. | E5, one admitted social turn | Other wordings remained silent; EOD e562c64 does not establish general PASS. |
| Sep 10 | 2c58b37 | Warm AI aircraft Interpreter. | E5, user heard Hornet answer | Aircraft language slice passed; general conversation failed on the same build. |
| Sep 10 | 7d0b548 | Natural-Language First V1 and recovery root AGENTS. | E0, approved documentation | Contract does not claim complete implementation. |
| Sep 10 | 7b6981a | General Semantic ingress, three fact selectors and explicit context. | E2/E3/E4 | Blind 20-turn failure; one later position TX completed. |
| Sep 11 | 5c9ab244 | Gate A length/recovery; Gate B inventory of 134 entries, seven exposed selectors; META separation. | E2/E3/E4 | Latest 20-turn physical FAIL: 12 completed, eight failed transmissions. |
| Sep 14 | Uncommitted documentation draft on 5c9ab244 | Source hierarchy, governance and foundation audit. | Documentation only | Runtime unchanged; review required before commit or code. |

## Primary-source pointers

Full paths, hashes and review limits are in audit section A; exact field sessions
are in the field index. IA documents run from
docs/ia-1-1-hybrid-presentation-probe.md through docs/ia-6-interaction-router.md.
The current implementation report is
[General stabilization / fact surface](../general-stabilization-fact-surface-20260911.md).

The entire previous Memory is retained at immutable Git reference
5c9ab244:docs/ORION_PROJECT_MEMORY.md and in audit Appendix 2. Old instructions
remain historical evidence, not current authorization. Published recovery/EOD/
contract branches and all local branch identities are listed in audit Appendix 1.

No new DCS changelog watch was run. The conversation title does not prove that
every DCS release was audited. Current DCS version/API support needs a separately
authorized check before any related implementation.
