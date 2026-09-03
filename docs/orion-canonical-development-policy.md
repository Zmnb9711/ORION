# ORION Canonical Development Policy

Status: **CURRENT**

Strategy: `STRATEGY_A_CURRENT_RECONNECT`

Decision: `D74`

Forensic basis: `AG-20260903-173329-291b1626-f64d842-r2`

## Canonical rule

The current ORION lineage is the development baseline. It is extended by
reconnecting or adapting proven historical mechanisms, preserving stronger
current mechanisms, and retaining approved unfinished product ideas. This is
not a wholesale rollback and no single historical commit is Canonical ORION.

Every significant task must distinguish **CURRENT BEST**, **HISTORICAL BEST**,
and **RECOVERED UNIMPLEMENTED IDEA**. D71 applies in order: **RECONNECT → ADAPT
→ EXTEND → REFACTOR → REPLACE**. Current absence is not proof of historical
absence. `TRUE_GREENFIELD` is allowed only after current implementation,
historical implementation, mechanisms, disconnected paths, probes, and
recovered ideas have all been checked.

## Machine-readable model

The authoritative derived representation is the existing private Architecture
Guard SQLite index. `tools/orion_arch_guard/canonical_seed.py` defines typed,
versioned, bounded records; graph refresh writes them to `canonical_records`
and `canonical_record_capabilities` in the same database. The canonical input
signature is stored in `graph_metadata`. No second history database and no raw
private archive are introduced.

Work classifications are `CURRENT_EXTENSION`, `HISTORICAL_RECONNECT`,
`HISTORICAL_ADAPTATION`, `PARTIAL_IMPLEMENTATION_COMPLETION`,
`RECOVERED_IDEA_IMPLEMENTATION`, `TRUE_GREENFIELD`, `REFACTOR`, and
`REPLACEMENT`.

## Canonical Golden Components

| ID | Component | Protected boundary |
|---|---|---|
| GC01 | Flight Bridge | DCS flight telemetry ingress |
| GC02 | Mission Bridge | DCS mission provenance ingress |
| GC03 | FlightContextService | normalized Core flight context |
| GC04 | WorldModel/provenance | factual truth and provenance |
| GC05 | FlightContext update gate | bounded materially changed context |
| GC06 | Core fact binding | exact informational fact authority |
| GC07 | Placeholder fact validation | provider output validation |
| GC08 | ToolGateway/receipts | bounded tools, permissions and receipts |
| GC09 | InteractionRouter known-contract seam | semantic route selection |
| GC10 | OSU protected presentation | Core-owned operational wording |
| GC11 | Persistent ATC session | Core-owned multi-turn ATC state |
| GC12 | SpeechKit v3 External EOU STT | native finalization after PTT end |
| GC13 | UDP7082 true→false EOU | physical official-SRS PTT boundary |
| GC14 | SRS candidate buffering | PCM admitted after TX ownership |
| GC15 | Cadence-aware TX liveness | sender-cadence stale detection |
| GC16 | RadioRouter + canonical SRS adapter/RadioInfo | provider-neutral radio transport |
| GC17 | Streaming SpeechKit TTS | one response to one paced SRS TX |
| GC18 | Evidence/build identity/Guard | safe evidence and governance |

`HR01 Persistent Realtime Session` is separate: `HISTORICAL_GOLDEN_CANDIDATE /
RECONNECT_AND_REVALIDATE`. It remains `KEEP / NON_DEFAULT / BENCHMARK_NO_GO`
from `IPB-20260903-171624`: successful warm median 357 ms, p90 515 ms, 56/56
validator-accepted outputs, zero invalid downstream outputs, but 30% request
failure concentrated especially in Russian samples. It is not production
promoted.

`HR02 RadioEntity to VoiceProfile resolver` is a disconnected valuable
historical mechanism. Reconnect it when the product sequence reaches
multi-voice identity; it still requires persistent VoiceProfile lifecycle,
runtime binding, deterministic tests, and controlled field proof.

## DO NOT REINVENT

| IDs | Rule |
|---|---|
| DNR01–DNR03 | no second WorldModel, ToolGateway, or RadioRouter |
| DNR04–DNR06 | no new PTT-end heuristic, packet-gap EOU, or fixed liveness |
| DNR07 | protected operational wording remains Core-owned |
| DNR08 | no parallel persistent ATC owner |
| DNR09 | no second Communication Profile store |
| DNR10 | reuse the canonical SRS transport |
| DNR11 | reuse/adapt existing Realtime protocol/session mechanisms |
| DNR12 | no permanent Whisper restoration by default |
| DNR13 | no four hard language modes |
| DNR14 | 20–30 is a Pilot test corpus, not production KB scope |
| DNR15 | current absence does not establish historical absence |

Exceptions require an explicit FULL Guard differential and user decision.

## Retirement register

`RC01` packet-gap EOU, `RC02` fixed-timeout liveness, `RC03` provider/VAD PTT
ownership, `RC04` four hard language modes, `RC05` permanent Whisper,
`RC06` SAPI as primary presentation, `RC07` universal mandatory-Qwen
operational routing, and `RC08` Pilot 20–30 as production KB are **DO NOT
RESTORE TO PRODUCTION BY DEFAULT**. Retirement preserves historical code,
tests, reports, and evidence; it does not delete them.

## Recovered idea register

| ID | Recovered direction | State |
|---|---|---|
| U01 | Unified MODEL C domain migration | RECOVERED |
| U02 | Full Airport ATC lifecycle | USER_VALUED_UNIMPLEMENTED |
| U03 | Carrier ATC runtime | RECOVERED |
| U04 | AWACS/GCI conversational route | USER_VALUED_UNIMPLEMENTED |
| U05 | Full AAR voice lifecycle | USER_VALUED_UNIMPLEMENTED |
| U06 | JTAC laser/smoke coordination | USER_VALUED_UNIMPLEMENTED |
| U07 | Mission Control unified voice route | USER_VALUED_UNIMPLEMENTED |
| U08 | Verified normative phraseology packs | RECOVERED |
| U09 | Broad deterministic recognition | RECOVERED |
| U10 | RadioEntity→VoiceProfile resolver | USER_VALUED_UNIMPLEMENTED |
| U11 | Busy-channel/collision/preemption scheduler | RECOVERED |
| U12 | Trusted third-party radio identity correlation | RECOVERED |
| U13 | All-aircraft/rotorcraft knowledge adapters | USER_VALUED_UNIMPLEMENTED |
| U14 | Runtime Modules UI/enforcement | RECOVERED |
| U15 | Modular aircraft/component installer | RECOVERED |
| U16 | Selective uninstall/data retention UX | RECOVERED |
| U17 | Privacy-aware post-flight debrief | USER_VALUED_UNIMPLEMENTED |
| U18 | Current information/news connector | USER_VALUED_UNIMPLEMENTED |
| U19 | Mission Editor assistant | RECOVERED |
| U20 | Native VR status overlay | RECOVERED |

Recovered ideas are neither completed nor automatically approved for immediate
implementation. Allowed explicit transitions are `RECOVERED → DESIGNED →
APPROVED_IMPLEMENTATION → IMPLEMENTING → AUTOMATED_PROVEN → FIELD_PROVEN →
PRODUCTIZED`, or `DEFERRED`, `REJECTED`, or `OBSOLETE`.

Ten user-value markers retain the full Virtual ATC lifecycle, AWACS/GCI, AAR,
JTAC laser/smoke, Mission Control, persistent voices per RadioEntity,
all-aircraft/rotorcraft support, casual/random conversation, news/current
information, and post-flight debrief. They stay visible until explicitly
reclassified; they are not all immediate priorities.

## Canonical roadmap

- C0 historical source recovery — complete;
- C1 Architecture Guard foundation — complete;
- C2 capability graph and Previous Best gate — complete;
- C3 **CANONICAL ORION BASELINE ESTABLISHED** — current;
- C4 **REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION** — next;
- C5 isolated Realtime benchmark and promotion decision;
- C6 bounded presenter selector, conditional on PASS;
- C7 controlled DCS/SRS field test, conditional on preceding gates.

The canonicalization and product-expansion tracks remain distinct.

## Development Console workflow

Use **ПРОВЕРИТЬ ВСЁ**, **ВСПОМНИТЬ ВСЁ**, **TASK RECALL**, **ROADMAP**,
**CANONICAL CONTEXT**, and **ЗАПИСАТЬ ИСТОРИЮ**. Prompt transfer remains manual
copy. A preview is not a save: review the canonical state and checkpoint
preview, then explicitly confirm **SAVE CHECKPOINT**.
