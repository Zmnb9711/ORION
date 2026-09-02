# ORION Master Decision Register — 2026-09-01

Status: **AUTHORITATIVE APPENDIX TO THE FULL-PRODUCT MASTER CHECKPOINT**

This register is an inseparable part of
`docs/orion-master-architecture-checkpoint-2026-09-01.md`. It records the 70
grouped decisions recovered from 26 ORION conversations and 6,602 inspected
messages, then cross-checked against Git, ADRs, current code, tests and field
evidence. Stable decisions made after that reconstruction continue from D71;
the historical D01-D70 identifiers and reconstruction counts are never
renumbered.

Counts preserved from the complete historical reconstruction:

- recovered grouped decisions: **70**;
- explicit user-approved decisions: **56**;
- rejected decisions: **12**;
- superseded decisions: **9**;
- deferred decisions: **11**;
- implemented decisions: **46**;
- field-proven decisions: **18**.

The status groups overlap. For example, a decision may be implemented and
field-proven, or historically approved and later superseded. `VERY_HIGH`
requires direct user approval or implementation plus evidence. Assistant
proposals remain proposals unless explicitly accepted or clearly adopted.

## Decision register

| ID | Date/time | Area | Decision | Proposed by | User approval | Historical implementation | Current implementation | Status | Superseded by | Evidence | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D01 | 2026-08-04 | Product | ORION is a DCS AI copilot/dispatcher, not a voice-command utility | User | Explicit | ORION-000 | Core/Launcher product | IMPLEMENTED | — | Recovered archive, Git | VERY_HIGH |
| D02 | 2026-08-05 | Scope | Target all supported fixed-wing aircraft and helicopters | User | Explicit | Generic schemas/adapters | Generic core plus bounded adapters | PARTIAL | — | Archive, code | VERY_HIGH |
| D03 | 2026-08-05 | ATC | Virtual ATC with Russian and English interaction | User | Explicit | Airport ATC services | Partial MODEL C migration | IMPLEMENTED / PARTIAL | — | Archive, Git | VERY_HIGH |
| D04 | 2026-08-05 | Mission Control | Mission awareness, coordination and bounded actions | User | Explicit | Mission Control services | Services retained; routing partial | IMPLEMENTED / PARTIAL | — | Archive, code | VERY_HIGH |
| D05 | 2026-08-05 | AWACS/GCI | Picture, Bogey Dope, BRAA, Declare and tactical support | User | Explicit | AWACS services | Services retained; routing partial | IMPLEMENTED / PARTIAL | — | Archive, code | VERY_HIGH |
| D06 | 2026-08-05 | JTAC/FAC | Talk-on, laser/code, smoke and supported JTAC workflow | User | Explicit | JTAC runtime/assets | Services retained; routing partial | IMPLEMENTED / PARTIAL | — | Archive, code | VERY_HIGH |
| D07 | 2026-08-05 | AAR | Tanker discovery, radio/TACAN and refuelling lifecycle | User | Explicit | Rich AAR service set | Services retained; routing partial | IMPLEMENTED / PARTIAL | — | Archive, code | VERY_HIGH |
| D08 | 2026-08-05/06 | Aircraft Knowledge | Manuals, procedures and full aircraft functionality, not only radios | User | Explicit | F/A-18-first knowledge work | Broad target partially implemented | PARTIAL | — | Archive, code | VERY_HIGH |
| D09 | 2026-08-05 | Debrief | Post-flight events, errors and recommendations | User | Explicit | Telemetry foundations | No complete product debrief | NOT_YET_IMPLEMENTED | — | Archive, current HEAD | VERY_HIGH |
| D10 | 2026-08-05 | Conversation | Natural casual/free conversation | User | Explicit | Qwen voice paths | Qwen/Yandex paths retained | IMPLEMENTED | — | Archive, Git | VERY_HIGH |
| D11 | 2026-08-05 | Current information | Discuss current/world news when an authorized source exists | User | Explicit | No current source | No current-information connector | NOT_YET_IMPLEMENTED | — | Archive, current HEAD | HIGH |
| D12 | 2026-08-05 onward | Safety | No silent broad autonomous control of the aircraft | User/Core | Accepted | Confirmation/allowlist boundaries | ToolGateway and domain policies | PRESERVED | — | Archive, code | VERY_HIGH |
| D13 | 2026-08-05/06 | DCS data | Keep Flight Bridge and Mission Bridge responsibilities distinct | User/assistant | Accepted | Separate bridges | WorldModel preserves provenance | IMPROVED | — | Archive, Git | VERY_HIGH |
| D14 | 2026-08-06 | Callsign | Obtain callsign from DCS/mission truth rather than duplicate manual input | User | Explicit correction | DCS context | Preserved target | APPROVED / PARTIAL | — | Archive | VERY_HIGH |
| D15 | 2026-08-06 | Settings | ORION must not manage or audit general VR tuning | User | Explicit rejection | Launcher scope corrected | ORION-only settings | REJECTED ALTERNATIVE | — | Archive | VERY_HIGH |
| D16 | 2026-08-06 | Launcher | One main user-facing Launcher; avoid extra normal-product windows | User | Explicit | Desktop Launcher | Current Launcher | IMPLEMENTED | — | Archive, code | VERY_HIGH |
| D17 | 2026-08-06 | Installer | Base product with optional modular components | User | Explicit | Partial packaging | Canonical installer; modularity incomplete | PARTIAL | — | Archive, installer history | VERY_HIGH |
| D18 | 2026-08-06 onward | Modules | Aircraft/module selection, with available selections enabled by default | User | Explicit | Partial installer/runtime modules | Incomplete UI and enforcement | PARTIAL / DEFERRED | — | Archive, current HEAD | VERY_HIGH |
| D19 | 2026-08-08/12 | Uninstall | Full and selective uninstall with explicit data policy | User | Explicit | Basic uninstaller | Selective UX incomplete | PARTIAL | — | Archive, installer | VERY_HIGH |
| D20 | 2026-08-06/14 | Audio | Select and test available input/output devices | User | Explicit | Launcher audio controls | Current audio controls | IMPLEMENTED | — | Archive, code | VERY_HIGH |
| D21 | 2026-08-08/10 | Airport ATC | Startup through taxi, tower, departure, arrival, landing and go-around | User | Explicit | Airport state machines/services | Pure takeoff migrated; remainder partial | IMPLEMENTED / PARTIAL | — | Archive, Git | VERY_HIGH |
| D22 | 2026-08-08/10 | Carrier ATC | Separate carrier lifecycle/agencies and radio identities | User | Explicit | Designs and bounded components | No complete production runtime | NOT_YET_IMPLEMENTED / PARTIAL | — | Archive, docs, HEAD | HIGH |
| D23 | 2026-08-08/10 | Emergency | Core-owned urgency, preemption and conflict handling | User/assistant | Accepted | Legacy priority rules | Modern unified scheduler incomplete | PARTIAL | — | Archive, code | HIGH |
| D24 | 2026-08-10 | Mission editor | Conversational Mission Editor assistance | User | Explicit | No complete service | Missing | NOT_YET_IMPLEMENTED | — | Archive, HEAD | VERY_HIGH |
| D25 | 2026-08-10 | Navigation | TACAN/RSBN/ADF knowledge; do not invent generic RNAV | User | Explicit | Aircraft knowledge/navigation work | Partial aircraft coverage | PARTIAL | — | Archive, code | VERY_HIGH |
| D26 | 2026-08-13 | Telemetry | Normalized aircraft/mission telemetry with explicit provenance | User | Explicit | Telemetry schemas | FlightContext and WorldModel | IMPROVED | — | Archive, Git | VERY_HIGH |
| D27 | 2026-08-13 | Evidence | Flight/runtime history and reproducible evidence | User | Explicit | Logs/recorders | Bounded Test Evidence ZIP | IMPROVED / FIELD_PROVEN | — | Archive, Git, evidence | VERY_HIGH |
| D28 | 2026-08-14/16 | STT | Separate local Whisper worker | User/assistant | Accepted, then removed | ORION-Voice/Whisper | Removed | SUPERSEDED | D34/D65 | Archive, Git | VERY_HIGH |
| D29 | 2026-08-14/16 | TTS | Windows SAPI voice output | User/assistant | Accepted prototype | SAPI output | Replaced by provider TTS | SUPERSEDED | D44/D67 | Archive, Git | VERY_HIGH |
| D30 | 2026-08-16 | Voice boundary | During Whisper era Core receives text rather than owning microphone/STT | User | Explicit | Worker/Core separation | Historical only | SUPERSEDED_CORRECTLY | D65 | Archive | VERY_HIGH |
| D31 | 2026-08-17 | Lifecycle | Window close keeps runtime in tray; explicit Exit stops owned processes | User | Explicit | Voice/Core shutdown sequence | Exact Launcher-owned Core lifecycle | IMPROVED / FIELD_PROVEN | — | Archive, Git | VERY_HIGH |
| D32 | 2026-08-17 | Qwen | Qwen is a replaceable cloud provider; Core and DCS stay local | User | Explicit | ADR-004 | Provider-neutral IA contracts | PRESERVED | — | Archive, ADR, Git | VERY_HIGH |
| D33 | 2026-08-17 | Qwen rollout | Tool smoke first, voice second, domain tools later | User | Explicit | Qwen vertical slices | Completed historical rollout | IMPLEMENTED | — | Archive, Git | VERY_HIGH |
| D34 | 2026-08-19 | Whisper | Remove permanent Whisper fallback after Qwen proof | User | Explicit | Commit `1963c60` | Whisper stack absent | IMPLEMENTED / SUPERSEDES | D28 | Archive, Git | VERY_HIGH |
| D35 | 2026-08-19 | Session | Explicit Start/Stop provider session; not always-on | User | Explicit | Qwen controls | Current session controls | PRESERVED | — | Archive, code | VERY_HIGH |
| D36 | 2026-08-19/24 | Boundary | AI provider and radio transport are independent axes | User/assistant | Explicitly adopted | ADR/SRS design | RadioRouter/provider contracts | IMPROVED | — | Archive, Git | VERY_HIGH |
| D37 | 2026-08-24 | Radio roles | Direct Audio for suitable local interaction; SRS for operational radio roles | User | Explicit | SRS architecture | Current product split | IMPLEMENTED | — | Archive, Git | VERY_HIGH |
| D38 | 2026-08-24 | SRS | Initial SRS `SYNC` must contain canonical non-null RadioInfo | Proven root cause | Approved corrective task | Commit `1a06a09` | Current SRS transport | IMPLEMENTED / FIELD_PROVEN | Null-RadioInfo SYNC | Logs, Git, field evidence | VERY_HIGH |
| D39 | 2026-08-24/25 | SRS | Production SRS adapter, Opus, pacing and lifecycle | User | Explicit | `d5408ef`, `a858c2` | Current transport/adapter | FIELD_PROVEN | — | Git, evidence | VERY_HIGH |
| D40 | 2026-08-25 | Context | Core-owned FlightContext with provenance to AI | User | Explicit | `f5c5d47`, `5896c4d` | Current | FIELD_PROVEN | — | Git, evidence | VERY_HIGH |
| D41 | 2026-08-25 | Privacy | Evidence must be bounded, redacted and credential-safe | User | Explicit | `a39b289` | Current recorder/exporter | IMPLEMENTED | — | Git, tests | VERY_HIGH |
| D42 | 2026-08-26 | IA-0 | Provider-neutral interaction contracts | User | Explicit | `2d90e4f` | Current | IMPLEMENTED | — | Git | VERY_HIGH |
| D43 | 2026-08-26 | IA-1 | Presentation contract probe | User | Explicit | `e1dc5a6` | Retained probe | PROBE_PASS | — | Git, probe evidence | VERY_HIGH |
| D44 | 2026-08-26 | IA-1.1 | Realtime versus SpeechKit presentation through SRS | User | Explicit | `bfa5443`, `08ca767` | Evidence/probe retained | FIELD_PROVEN | — | Git, evidence | VERY_HIGH |
| D45 | 2026-08-26 | IA-2 | WorldModel facade over authoritative sources | User | Explicit | `63448ed` | Current | IMPLEMENTED | — | Git, code | VERY_HIGH |
| D46 | 2026-08-27 | IA-3 | Core-governed typed ToolGateway | User | Explicit | `913b8b8` | Current | IMPLEMENTED | — | Git, code | VERY_HIGH |
| D47 | 2026-08-27 | IA-4 | Provider-neutral PlannerProvider contract | User | Explicit | `7f37b4d` | Current | IMPLEMENTED | — | Git, code | VERY_HIGH |
| D48 | 2026-08-27 | IA-5 | Yandex Qwen planner adapter | User | Explicit | `a4f9942` | Current | IMPLEMENTED / PROVIDER_PROVEN | — | Git, provider probe | VERY_HIGH |
| D49 | 2026-08-27 | IA-6 | Narrow InteractionRouter vertical, not full phraseology/Stage 6B | User | Explicit scope | `f1a3e08`, `5c5c831` | Current | IMPLEMENTED | — | Archive, Git | VERY_HIGH |
| D50 | 2026-08-27 08:59 | Language | Four hard FREE_RU/FREE_EN/AVIATION_RU/AVIATION_EN modes | Assistant | Initially accepted | Discussion only | Not canonical | SUPERSEDED | D51/D52 | Archive | VERY_HIGH |
| D51 | 2026-08-27 12:04–12:17 | Language | Any supported input; casual follows user; operational output follows profile | User | Explicit correction | Communication contracts | Partial runtime | APPROVED TARGET | D50 | Archive | VERY_HIGH |
| D52 | 2026-08-27 | Profiles | Final profiles: ICAO, FAA_US, NATO_MILITARY, FAP_RUSSIAN_ATC | User | Explicit | Contracts/planning | IDs, packs and UI implemented | IMPLEMENTED INFRASTRUCTURE | Old language menu | Archive, Git | VERY_HIGH |
| D53 | 2026-08-27 | Profiles | Profile affects wording/procedure presentation, not truth/provider/permissions | User/assistant | Explicitly retained | Contracts/tests | Current isolation | PRESERVED | — | Archive, tests | VERY_HIGH |
| D54 | 2026-08-27 | Phraseology | Hybrid D mechanism with fail-closed Hybrid B boundary | User/assistant | Explicit | IA seams/Golden contracts | MODEL C target | APPROVED / PARTIAL | — | Archive, Master | VERY_HIGH |
| D55 | 2026-08-27 | Phraseology | Protected operational fragment never returns to Qwen | User/assistant | Explicit | Golden/Mixed contracts | Current invariant | PRESERVED | — | Archive, tests | VERY_HIGH |
| D56 | 2026-08-27 | Packs | Versioned local active/candidate/previous-known-good pack lifecycle | Assistant | Clearly adopted | Later implementation | Current pack store/lifecycle | IMPLEMENTED INFRASTRUCTURE | — | Archive, Git | HIGH |
| D57 | 2026-08-27 | Sources | Source-aware ICAO/FAA/NATO/FAP profile families | User/assistant | Accepted | Source planning | Current source registry; content absent | PARTIAL | — | Archive, registry | HIGH |
| D58 | 2026-08-26/27 | RadioEntity | Persistent recognizable voice per radio role/entity | User | Explicit broad request | Role voice probes | Not production wired | DISCONNECTED TARGET | — | Archive, code | VERY_HIGH |
| D59 | 2026-08-26/27 | Voice model | Provider-neutral VoiceProfile/SpeechStyle schema | Assistant | Tacit acceptance | Probe models | Partial/default-oriented path | PROPOSED / PARTIALLY_ADOPTED | — | Archive, code | HIGH |
| D60 | 2026-08-28 | Radio | Provider-neutral RadioRouter contracts | User | Explicit | `49f083d` | Current | IMPLEMENTED | — | Git | VERY_HIGH |
| D61 | 2026-08-28 | SRS | Stage 6B.2 production SRS adapter | User | Explicit | `a955d7c` | Current | FIELD_PROVEN | — | Git, field evidence | VERY_HIGH |
| D62 | 2026-08-28 | Pilot KB | 20–30 means bounded test corpus, not production KB size | User | Explicit | `a85ab98` | Experimental probe | PROBE_PASS | Product-size misreading | Archive, Git | VERY_HIGH |
| D63 | 2026-08-28 | Golden | Deterministic domain truth precedes protected wording | User | Explicit | `9f38d44` | Basis of MODEL C | IMPLEMENTED / PROBE_PASS | — | Git, tests | VERY_HIGH |
| D64 | 2026-08-28/30 | Live Golden | Physical mixed-conversation experiment | User | Explicit experiment | `918ee58` lineage | Retained bounded path | EXPERIMENTAL | Universal mandatory-Qwen route | Field evidence | VERY_HIGH |
| D65 | 2026-08-30/31 | STT | SpeechKit v3 RecognizeStreaming with explicit External EOU | User | Explicit | `255f200` lineage | Current production STT option | FIELD_PROVEN | Realtime/manual-commit finalization | Git, evidence | VERY_HIGH |
| D66 | 2026-08-31 | PTT | Official SRS UDP 7082 `IsSending true→false` owns local TX end | User/evidence | Explicit corrective task | `55e70f8` | Current | FIELD_PROVEN | Packet-gap EOU | Git, evidence | VERY_HIGH |
| D67 | 2026-08-31 | TTS | SpeechKit StreamSynthesis streams into one bounded SRS TX | User | Explicit experiment/promotion | `0902710` | Current production mode | FIELD_PROVEN | Full-buffer-only primary | Git, evidence | VERY_HIGH |
| D68 | 2026-09-01 | MODEL C | Safely recognized pure operational request bypasses Qwen | User/recovery | Explicit | `6f6f2f1` | Pure takeoff route | FIELD_PROVEN | Mandatory-Qwen experiment | Git, field evidence | VERY_HIGH |
| D69 | 2026-09-01 | Profile UI | Four-profile selection, persistence, details/update/rollback | User | Explicit historical intent | `01a499e` | Current Launcher and API | IMPLEMENTED INFRASTRUCTURE | Old free-language menu | Git, code | VERY_HIGH |
| D70 | Future | VR | Native/OpenXR status overlay must degrade gracefully | User/assistant | Deferred | No production overlay | Missing/deferred | DEFERRED | — | Archive | HIGH |
| D71 | 2026-09-02 | Development process | Previous Best Solution Gate: before architecture implementation search prior approved decisions, implementations, field-proven solutions and reusable mechanisms; a disconnected historical implementation is not automatically missing | User | Explicit | AG-0 source discovery foundation | Current development policy | APPROVED / AG-0 IMPLEMENTED | Current-HEAD-only design | User task, Guard design, Git | VERY_HIGH |
| D72 | 2026-09-02 | Informational UX | Normal informational responses remain naturally AI-formulated; canned/template phrases are not the normal informational UX, while protected operational wording remains Core-owned | User | Explicit | Architecture Guard hard constraint | Current architecture policy | APPROVED | Canned informational default | User task, Master boundary | VERY_HIGH |
| D73 | 2026-09-02 | Development process | Every assistant response about ORION must begin with a visible first-line Architecture Guard status; only `ON`, `REQUIRED`, and `OFF` are allowed, with the mandatory semantics and report-ID enforcement defined below | User | Explicit | User-approved working convention | Mandatory ChatGPT/Codex workflow | APPROVED / EFFECTIVE IMMEDIATELY | Unlabelled or falsely labelled ORION responses | User task, AG-3 preflight `AG-20260902-185339-f70f7a7f-8c406fe-r1`, Git | VERY_HIGH |

### D73 — mandatory visible Architecture Guard status

Every assistant response about ORION must begin on its first visible line with
one of these statuses:

- `ORION ARCHITECTURE GUARD: ON` — the response or task is grounded in an
  applicable, actual Architecture Guard result. For architecture-changing work,
  once AG-3 report generation exists, the line must include the concrete report
  ID as `ORION ARCHITECTURE GUARD: ON — AG-...`.
- `ORION ARCHITECTURE GUARD: REQUIRED` — the discussion has reached an
  architecture decision or change. The Guard must run before the assistant may
  recommend, approve, or implement that architecture.
- `ORION ARCHITECTURE GUARD: OFF` — the Guard was not applied. This is allowed
  for non-architectural ORION explanation, status, or chitchat, but the
  assistant must not recommend, approve, or assert a new ORION architecture
  decision while the status is `OFF`.

The status line is mandatory even when the answer is brief. Omitting it is a
process violation. The convention is effective immediately. AG-3 report
generation exists as of this decision, so the concrete `AG-...` report-ID
requirement is already operational for architecture-changing `ON` responses.

## Durable negative register

These are not future “new ideas” unless a later explicit user decision reopens
them:

- ORION-managed VR tuning/settings — **REJECTED**;
- duplicate manual callsign — **REJECTED**;
- Free Russian/Free English as Communication Profiles — **SUPERSEDED**;
- four hard language modes — **SUPERSEDED**;
- immediate Russian Military fifth profile — **DEFERRED**;
- permanent Whisper fallback — **SUPERSEDED**;
- always-on Qwen session — **REJECTED**;
- Qwen embedded in Core or owning domain truth — **REJECTED**;
- Qwen-owned protected phraseology — **NO-GO**;
- Hybrid C as the only protection boundary — **NO-GO**;
- critical output through Realtime only — **SUPERSEDED**;
- provider/VAD-owned physical radio turn — **SUPERSEDED**;
- packet-gap EOU — **SUPERSEDED**;
- universal mandatory-Qwen operational route — **SUPERSEDED EXPERIMENTAL DRIFT**;
- 20–30 as production KB size — **REJECTED INTERPRETATION**;
- test-only GUI/probe as production field proof — **REJECTED**;
- DCS audio ducking as a requirement — **REJECTED/NOT REQUIRED**;
- full Launcher cleanup before architecture/radio gates — **DEFERRED**.

## Update rule

Changing a row requires either a later explicit user decision or direct new
implementation/field evidence. A current implementation difference must be
recorded as a difference; it must not silently rewrite historical intent.
