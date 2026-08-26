# ORION Data Coverage Matrix

Checkpoint: IA-2, 2026-08-26. `A/O/D` means authoritative, observed or
Core-derived. Validation is `FIELD`, `CODE`, `REQUIRED`, or `GAP`. “Restricted”
means multiplayer/export policy may hide the fact. Owners remain authoritative;
the World Model is only a read/query projection.

| Domain | Fact/query | Current source / owner | Available | Class | Freshness | Aircraft-specific | Restriction risk | Confidence | Current gap / recommended future source | Validation |
|---|---|---|---|---|---|---|---|---|---|---|
| Own aircraft | identity/callsign | DCS Export / LiveTelemetryStore | yes | A | 5 s | low | ownship permission | no | typed `ownship()` | FIELD+CODE |
| Own aircraft | lat/lon/MSL position | DCS Export / LiveTelemetryStore | yes | A | 5 s | no | ownship permission | no | typed position fact | FIELD+CODE |
| Own aircraft | heading | DCS Export / LiveTelemetryStore | yes | A | 5 s | no | ownship permission | no | typed heading | FIELD+CODE |
| Own aircraft | attitude | DCS Export / LiveTelemetryStore | partial | A | 5 s | low | ownship permission | no | unknown when omitted | CODE |
| Own aircraft | TAS | DCS Export / LiveTelemetryStore | yes | A | 5 s | no | ownship permission | no | typed TAS | FIELD+CODE |
| Own aircraft | groundspeed | velocity x/z / World Model | yes | D | 5 s | no | ownship permission | no | validate coordinate convention per exporter | CODE |
| Own aircraft | vertical speed | DCS Export / LiveTelemetryStore | yes | A | 5 s | no | ownship permission | no | typed vertical speed | FIELD+CODE |
| Own aircraft | AGL | DCS ownship AGL / LiveTelemetryStore | partial | A | 5 s | no | ownship permission | no | absent outside supported state | FIELD+CODE |
| Own aircraft | fuel fraction | DCS normalized telemetry / LiveTelemetryStore | partial | A | 5 s | medium | module semantics | no | normalize module fuel structures | CODE/P2 |
| Own aircraft | engine state | DCS propulsion / LiveTelemetryStore | raw partial | O | 5 s | high | module semantics | no | typed per-module normalization | REQUIRED/P2 |
| Own aircraft | gear/flaps | LoGetMechInfo / LiveTelemetryStore | raw partial | O | 5 s | medium | module semantics | no | normalized typed facts | REQUIRED/P2 |
| Own aircraft | aileron/elevator/rudder | DCS `controlsurfaces` | not exported | O | n/a | medium | module semantics | no | export independent L/R values; preserve API `eleron` spelling at boundary | GAP/P2 |
| Own aircraft | payload/weapons | DCS payload / LiveTelemetryStore | raw partial | O | 5 s | high | export settings | no | typed normalized payload | REQUIRED/P2 |
| Own aircraft | warnings | DCS module data / LiveTelemetryStore | raw partial | O | 5 s | high | module semantics | no | validated warnings adapter | REQUIRED/P2 |
| Own aircraft | navigation state | DCS nav / LiveTelemetryStore | raw partial | O | 5 s | high | module semantics | no | aircraft adapter/query | REQUIRED/P2 |
| Own aircraft | COMM radios | DCS radios + F/A-18 adapter | partial | O | 5 s | high | module/export | no | future RadioContext owns selected state | REQUIRED/Stage 6B |
| Own aircraft | TACAN | validated F/A-18 adapter | partial | O | 5 s | high | mapping validation | no | World Model systems query | CODE; field mapping required |
| Own aircraft | cockpit state | F/A-18 adapter/mapping registry | partial | O | 5 s | high | raw arguments sensitive | only uncertain obs | expose validated subset only | CODE/P2 |
| Own aircraft | sensors/RWR | DCS raw telemetry | raw partial | O | 5 s | high | sensor-export restrictions | yes | trusted contact/observation owner | GAP/P1 |
| Mission world | units | MissionSnapshot / MissionStore | yes | A mission truth | 30 s | no | omniscience risk | no | bounded mission-units query | CODE |
| Mission world | groups | no canonical grouped projection | no | A | n/a | no | omniscience risk | no | MissionStore group index | GAP/P1 |
| Mission world | coalition | MissionUnit / MissionStore | yes | A mission truth | 30 s | no | omniscience risk | no | bounded unit fact | CODE |
| Mission world | unit position | MissionUnit / MissionStore | yes | A mission truth | 30 s | no | export/multiplayer | no | never expose as detected automatically | CODE |
| Mission world | unit velocity | scalar speed only | partial | A mission truth | 30 s | no | export/multiplayer | no | vector/course semantics required for closure | GAP/P1 |
| Mission world | alive/dead | MissionUnit / MissionStore | yes | A mission truth | 30 s | no | omniscience risk | no | bounded alive filter | CODE |
| Mission world | airbases | DCS world/airport domain | partial fragmented | A | source-specific | no | export rules | no | canonical airbase owner/query | GAP/P1 |
| Mission world | weapons/events | no canonical bounded history | no | A/O | n/a | no | high-volume/export | maybe observed | event owner with retention | GAP/P1/P3 |
| Mission world | player identity | Mission Bridge session | partial | A | 10 s owner rule | no | low | no | bridge fact separate from mission | CODE |
| Mission world | mission identity/time | MissionSnapshot / MissionStore | yes | A | 30 s | no | low | no | mission identity query | CODE |
| Mission world | phase/session lifecycle | Mission Bridge + domain state | partial | A | 10/30 s | no | low | no | canonical phase owner | GAP/P1 |
| ATC | airport | airport/runway domain stores | partial | A | domain-owned | no | low | no | future Tool Gateway calls owner | REQUIRED/P1 |
| ATC | runway metadata | runway/surface stores | partial | A | domain-owned | no | low | no | bounded runway query | REQUIRED/P1 |
| ATC | traffic | fragmented mission/ATC state | partial | mixed | tactical | no | visibility risk | observed confidence possible | dedicated ATC traffic view | GAP/P1 |
| ATC | clearance state | ATC authority/session stores | yes domain-local | A | domain-owned | no | authorization | no | do not move to World Model | CODE/domain |
| ATC | procedural state | ATC runtime/session | yes domain-local | A | domain-owned | no | authorization | no | read projection later | CODE/domain |
| ATC | weather | no canonical live owner | no | A/O | n/a | no | availability | no | DCS/weather owner | GAP/P1 |
| ATC | runway occupancy | no trusted canonical view | no | O/D | tactical | no | visibility | yes if observed | traffic+surface geometry | GAP/P1 |
| AWACS/GCI | observed contacts | no trusted owner | no/restricted | O | tactical | sensor-dependent | high | yes | sensor/contact store + policy | GAP/P0/P1 |
| AWACS/GCI | mission-truth units | MissionStore | yes but restricted for contact use | A mission truth | 30 s | no | omniscience | no | keep distinct from observations | CODE |
| AWACS/GCI | identity/coalition | mission truth only | partial | A/O varies | tactical | no | detection/classification | yes when observed | contact classification facts | GAP/P1 |
| AWACS/GCI | range/bearing/altitude | positions / World Model | range/bearing yes for mission truth | D | max input age | no | input visibility | no | derive only after visibility policy | CODE/GAP |
| AWACS/GCI | closure | insufficient vector pair | no | D | max input age | no | input visibility | no | aligned velocity vectors | GAP/P1 |
| AWACS/GCI | threat prioritization | no IA-2 policy | no | D | task-specific | domain-specific | high | confidence may be input only | future deterministic domain policy | GAP/later |
| JTAC/FAC | target | JTAC sessions + MissionStore | domain-local | A | domain-owned | no | mission visibility | no | owner remains JTAC service | CODE/domain |
| JTAC/FAC | friendly designator capability | aircraft/unit capability data | partial | A/O | domain-owned | platform-specific | export | maybe | typed capability owner | GAP/P1 |
| JTAC/FAC | laser code | JTAC session/runtime | domain-local | A | domain-owned | no | authorization | no | future read query | CODE/domain |
| JTAC/FAC | smoke availability/state | JTAC domain | partial | A | domain-owned | no | authorization | no | explicit inventory/state owner | GAP/P1 |
| JTAC/FAC | designation state | JTAC domain | partial | A/O | domain-owned | no | visibility | maybe observed | explicit state projection | GAP/P1 |
| AAR/tanker | identity/callsign | coalition radio/mission units | partial | A mission data | 10/30 s | no | mission truth | no | unified tanker read query | REQUIRED/P1 |
| AAR/tanker | frequency/TACAN | CoalitionRadioDirectory | yes when mission supplies | A | bridge-owned | no | mission truth | no | preserve directory ownership | CODE/domain |
| AAR/tanker | position | MissionStore/coalition unit | partial | A | 30 s | no | mission truth | no | bounded owner query | REQUIRED/P1 |
| AAR/tanker | availability | coalition radio + AAR services | partial | A | owner-specific | no | mission truth | no | unify projection, not storage | GAP/P1 |
| AAR/tanker | rendezvous/refueling state | AAR services/sessions | domain-local | A | domain-owned | aircraft-specific | authorization | no | future Tool Gateway domain read | CODE/domain |
| Navigation | coordinate formatting | ownship position / World Model | yes | D | 5 s | no | coordinates sensitive | no | deterministic formatter | CODE |
| Navigation | airfield/nearest airfield | no general resolver | no | A/D | n/a | no | low | no | canonical airfield geospatial index | GAP/P1 |
| Navigation | route/waypoints | raw nav only | no reliable generic query | O/A | 5 s | high | module/export | no | normalized route owner | GAP/P1/P2 |
| Navigation | terrain/elevation | DCS `LoGetAltitude(x,z)` available, not exported | no general query | A | n/a | no | export environment | no | Core-owned terrain query/cache | GAP/P1 |
| Navigation | LOS | no terrain source | no | D | tactical | no | visibility | no | terrain + endpoints + policy | GAP/P1 |
| Navigation | range/bearing geometry | authoritative positions / World Model | yes | D | max input age | no | visibility | no | current geometry query | CODE |
| Aircraft knowledge | exact procedures | aircraft knowledge registry | partial | A curated | versioned | high | low | no | keep separate from live state | CODE/domain |
| Aircraft knowledge | switch/control mappings | F/A-18 mapping registry | partial | A curated | mapping version | high | low | no | validate per module/build | FIELD REQUIRED/P2 |
| Aircraft knowledge | observed cockpit state | cockpit adapter | partial | O | 5 s | high | mapping/export | yes if uncertain | validated subset only | CODE |
| Aircraft knowledge | capability knowledge | aircraft registry/capabilities | partial | A curated | versioned | high | low | no | expand per aircraft | GAP/P2 |
| Radio | current COMM state | telemetry/cockpit/SRS fragmented | partial | O | source-specific | high | privacy/export | no | Stage 6B RadioContext owner | NOT IA-2 |
| Radio | selected radio | no canonical owner | no | A/O | tactical | high | low | no | Stage 6B | GAP/Stage 6B |
| Radio | frequency/modulation | telemetry + mission + SRS fragmented | partial | mixed | source-specific | high | low | no | Stage 6B normalization | GAP/Stage 6B |
| Radio | PTT | SRS runtime transport | runtime only | A transport | real-time | no | privacy | no | Stage 6B read abstraction | GAP/Stage 6B |
| Radio | SRS identity/readiness | SRS runtime | yes transport-local | A transport | real-time | no | session identity | no | future existing Core-owned abstraction | FIELD; not exposed |

## Architectural interpretation

- `MissionStore` answers “what exists in mission truth”; it does not answer
  “what has the player/AWACS detected.”
- Confidence belongs only to uncertain observations/classification, never to
  deterministic telemetry or geometry.
- Current exporter permission functions and multiplayer server settings can make
  some apparently supported DCS facts unavailable. Unavailable/restricted is a
  valid result, not permission to infer.
- Tacview is coverage reference only. It is neither source nor owner.
- Radio rows are design inventory for Stage 6B and are deliberately not
  implemented by IA-2.
