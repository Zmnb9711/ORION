# Foundation Step 4 — systematic safe fact surface

ORION ARCHITECTURE GUARD: OFF. Component evidence, NOT Foundation field acceptance.

## A. Contract / starting Git state

CONTRACT READ: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1` at
`docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md`.
Canonical SHA-256 remains `de59126cb79efc010996f4f8357ab80b641109b7ed3cd60ccbc7856d53c2a128`.
Worktree `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`;
branch `codex/general-natural-language-ingress-tranche1`;
parent `8ddc0422197a8adbe88209c0d7adc4c6301f42c4`;
starting tree `ba1bacd8c70a9c5d21ad1498206f05925dde1ac2`.
Index/tracked files were clean; untracked `data/` preserved, never staged.
Steps 1/2/3 are ancestors. No build, install, simulator launch, physical turn or Step 5.

Compliance: §§1–3/12–13 retain open input and one General entry; §§4–5/7 retain
Core/Gateway truth; §9 leaves the Step 2 context/wire owner unchanged; §§10–11 use
one semantic operation and one coalesced ownship read; §14 preserves actual host
reachability and frozen voice owners. §8 Mixed remains a target outside this
tranche, not implemented by implication. §15 field evidence is not substituted
by fixtures. §§17–20: scope checked, canonical contract not amended.

## B. Complete DCS data inventory

Bottom-up source review: `dcs-export/Export.lua`, `orion/models.py`,
`orion/live_telemetry_store.py`, `orion/world_model.py`,
`orion/world_model_contracts.py`, `orion/tool_gateway.py`, Hornet adapter/decoders,
`orion/mission.py`, `orion/mission_store.py`, `orion/mission_bridge_ingest.py`,
`orion/coalition_radio.py`, `orion/navigation_channels.py`, then registry/presentation.

The manifest contains **233 inventory records**, including semantic concepts,
raw leaves, derived views, quality/transport metadata and unavailable concepts.
This is NOT 233 independent measured values or 233 supported capabilities.

| Primary disposition | Records |
|---|---:|
| FOUNDATION_EXPOSED | 10 |
| AVAILABLE_BUT_NOT_CONNECTED | 112 |
| SEMANTICS_UNCERTAIN | 60 |
| RESTRICTED | 29 |
| UNAVAILABLE | 22 |

Local primary API reference:
`D:/SteamLibrary/steamapps/common/DCSWorld/Scripts/Export.lua`, lines 420–470,
596–631. SHA-256 `5bc692bd75adcd2308b3f0d12295da0a1bfe81067cabb774e649f6f262ed0ba9`.
Installed `bin/DCS.exe` file/product version `2.9.29.27468`; no running DCS was
found in the read-only process check. API comments are evidence of the documented
contract, not proof of every current module implementation.

## C. Source → Core trace

| Exposed concept | Source / packet | Core selector | Unit / presentation |
|---|---|---|---|
| aircraft.identity | LoGetSelfData.Name / aircraft_type | ownship.aircraft.aircraft_type | validated aircraft display name |
| ownship.position | LatLongAlt.Lat/Long / position | ownship.position.latitude/longitude | degrees; natural Russian DDM |
| ownship.heading | Heading + heading_valid | ownship.heading_deg | deg; preserved heading policy |
| ownship.altitude_msl | LatLongAlt.Alt | ownship.position.altitude_m | m; geometric above sea level |
| ownship.pitch | ADI return 1, rad→deg | ownship.attitude.pitch_deg | deg; pitch, not climb rate |
| ownship.bank | ADI return 2, rad→deg | ownship.attitude.bank_deg | signed deg; not heading |
| ownship.yaw | ADI return 3, rad→deg modulo360 | ownship.attitude.yaw_deg | deg; ADI yaw only |
| ownship.true_airspeed | LoGetTrueAirSpeed + direct-source quality | ownship.true_airspeed_mps | m/s; TAS, not vector magnitude |
| ownship.vertical_speed | LoGetVerticalVelocity + direct-source quality | ownship.vertical_speed_mps | m/s; signed vertical speed |
| ownship.altitude_agl | LoGetAltitudeAboveGroundLevel + unclamped quality | ownship.altitude_agl_m | m; geometric above local ground |

All ten use the existing TelemetryEnvelope → single LiveTelemetryStore →
WorldModelFacade.ownship → `orion.world.ownship.get@1.0` / `world.ownship.read`
path. GeneralSemanticCore selects only registry-owned typed leaves. The existing
single-identity borrowed mapper remains intact; generic multi-fact identity also
uses the registry. Neither path adds a provider call. No second store/owner.

Dynamic metadata remains `dcs_export` / `authoritative`, Core receive timestamp,
generation, status and five-second freshness. Provider values are never inputs.
Registry freshness/binding/source/authority are now checked as registry metadata,
not independently duplicated constants. Per-record traces and first unproven
boundaries are in the machine manifest; supplemental code evidence is below.

## D. Quality classification / fallback correction

The exporter previously substituted vector magnitude for failed TAS, vector.y
for failed vertical velocity, and zero for negative AGL. Seven added Lua lines
record three booleans BEFORE these transformations. Existing numeric fields,
callbacks, ports, protocol version and fallback calculations remain literal.
`SourceQuality` uses strict optional booleans. Old/false/missing quality means
UNKNOWN in the three WorldModel facts, not valid zero. A real direct-source zero
remains KNOWN. Non-DCS envelope source is rejected rather than relabelled DCS.

Actual Lua 5.1 exporter execution with a fake socket/API tested valid, real-zero,
missing, exception, wrong-type, fallback and negative-AGL cases. This ran Lua only,
NOT the simulator. No packet was sent. Other vector/legacy raw projections are
not made safe by these flags and remain unexposed.

## E–F. Registry and provider catalog

`orion/general_fact_registry.py`: five primary disposition values; authority and
applicability remain separate. Registry revision `orion.facts.177a3435e57b3705`.
Provider projection contains ten ID/meaning entries, **1171 UTF-8 bytes**;
base instructions **5595 bytes** before per-turn explicit context. Exact gate
request instructions, including owned context, ranged **5727–7402 bytes**.
No measurements, raw field paths, credentials or ToolResult enter the catalog.
All currently exposed definitions use a common source contract, not a promise
that every aircraft exports a valid value. No module-only definition is admitted.

## G. Fuel: concrete final decision

**SEMANTICS_UNCERTAIN**, not unavailable: raw internal/external quantities are
exported through `fuelJson` into `AircraftState.fuel`. The typed `fuel_fraction`
field is separate and is NOT populated by the current exporter. The facade's
existing optional fraction projection therefore does not establish normalization.

Installed API comments document kg for both quantities. However a firsthand
Hornet report describes fractional output instead of that documented mass:
[Bergison, 2022-12-03](https://forum.dcs.world/topic/314135-logetengineinfo-working-but-not-as-described/).
This is historical user evidence, not an ED guarantee or a current-module test.
It demonstrates why the documentation alone cannot establish a universal mapper.

First unproven boundary: actual module `LoGetEngineInfo` result → normalized fuel
meaning/unit. Unknowns are the denominator of a fraction, whether external fuel
is included, external-field semantics, and cross-aircraft consistency. No tank
capacity is inferred; neither mass nor percentage nor sum is fabricated.

The preserved primary ZIP
`C:/Users/Алексей/Documents/Codex/2026-08-24/referenced-chatgpt-conversation-this-is-an-4/outputs/ORION-DCS-Field-Evidence-20260825-180547.zip`
contains filtered ownship/radio telemetry, not the needed fuel samples. It cannot
close this question. A future bounded per-module comparison against a known fuel
state, including internal/external conditions, is needed before fuel exposure.
No such physical test was performed or inferred. This explicit uncertain
classification is permitted by Step 4; it is not claimed as fuel support.

## H–J. Altitude, speed and attitude

MSL/geometric and AGL are distinct IDs and wording; neither is claimed barometric
or radar altitude. Negative raw AGL loses admission, rather than becoming a false
valid zero. TAS and signed vertical speed now require direct-source flags.
GS remains uncertain because Export may manufacture x/z zeros; IAS and Mach API
functions exist in the DCS reference but are not emitted/typed by this pipeline.
No vector magnitude is renamed TAS. Existing pitch/bank/yaw conversion, bounds
and labels remain; yaw is not promoted to magnetic heading or ground track.
The legacy use of “курс” for the selected heading is preserved, not evidence
of magnetic variation. Signed vertical convention also exists explicitly in
`orion/flight_context.py:FlightContextService` output policy; it was not invented
from provider text.

## K–L. Configuration and propulsion

Eight mechanical components retain status/value pairs. No authoritative enum or
module-complete boolean map was established, so raw argument/status numbers are
not announced as gear down, brake applied, or engine normal. Missing stays unknown.

RPM, temperature, fuel flow and hydraulic pressure retain left/right identity.
The installed reference documents %, Celsius, kg/s and kg/cm² respectively;
that does not prove module completeness, absent-engine sentinels or which engine
temperature measurement a module returns. No count/running/afterburner/throttle
state is inferred. These eight raw engine leaves remain uncertain; “temperature”
is not automatically recast as exhaust gas temperature.

## M–N. Aircraft-specific systems and radio

Hornet raw argument mapping, calibration registry and semantic decoders exist.
`WorldModelFacade.aircraft_systems` produces OBSERVED facts, but its normalization
call supplies no `HornetArgumentMapping`; raw decoder paths consequently return
unknown even with the outer mapping flag. Optional injected normalized fields
are not evidence that the current Export actually emits them. A calibrated,
version-bound active mapping and per-leaf provenance must be proved before
admission. No bypass or speculative decoder repair is imported here.

SRS communication frequency/coalition/RadioInfo is a different owner from cockpit
COMM tuning. Generic Export marks radios not-yet-mapped and emits no radios body.
Mission presets/requested settings are not observed cockpit state. These sources
remain separately classified; SRS code, ports, EAM and lifecycle are unchanged.

## O–Q. Payload, Mission/World, restricted and unknown

Payload carries station/type tuple/count/current station, cannon and chaff/flare.
Missing station list becomes empty; missing container becomes false in the old
projection. That is not proof of an empty loadout or a universal weapon identity.
No loadout wording is invented from numeric tuples. Payload remains uncertain.

MissionStore identity/units and Bridge directories have separate owners, clocks,
generations and tools. Mission-unit alive/detected defaults and altitude/time
defaults can manufacture apparent values; Bridge heartbeats can refresh liveness
without resampling every retained value. These are not fresh ownship readings.
Read-only mission/geometry facilities remain available to their existing owners,
but no unrestricted directory/unit query or target-selection route is added to
the Foundation ownship catalog. Range/bearing preserves DERIVED two-source truth,
not radar detection. Observed contacts remain explicitly restricted.
Sensor export permission and raw EW/sensor entries do not create an approved
observed-contact owner. No ATC/AWACS/JTAC/AAR expansion or operational write.

## R. Natural coordinate presentation

KEEP current deterministic renderer: degrees and decimal minutes rounded to
0.01 minute with carry, Russian agreement and full hemisphere wording. It already
produces the approved whole-minute style when no fraction remains. No input
grammar added. Maximum rounding is 9.26 m per latitude axis, at most 13.1 m planar
at the equator; whole minutes would allow 926 m per axis and were NOT substituted.
Canonical latitude/longitude remain unchanged; display and speech stay separate.
No new high-precision input intent is claimed. Coordinate/morphology edge tests pass.

## S–T. Multi-fact and summary

One operation selects multiple IDs; one Gateway snapshot supplies compatible
generation/source time. Unknown selected leaves are marked without leaking
unselected telemetry. Generation/provenance tampering fails admission.
Summary stays exactly heading, geometric MSL, pitch, bank, in that order, with
explicit partial-summary disclaimer. It does not grow with the registry.
Final text remains bounded to 1000 characters; no silent truncation. Unknown
summary members are stated as unknown, not replaced with unrelated facts.

## U–V. Gap, Conversation and META

`CAPABILITY_GAP.need` is bounded non-empty descriptive text (160 characters),
not an execution key or literal enumeration. Invalid types/control characters
fail schema; novel descriptions parse. The description is never echoed as a fact
or used to select a tool. Registry dispositions, WorldFact statuses and Gateway
policy errors remain distinct internal evidence; user wording grants no rights.

Step 2 Dialogue role, 200-character soft target / 400 ceiling, explicit context,
ACK/reset, anti-repetition policy and delivery ownership remain unchanged.
Only gap schema/prompt metadata changed. META remains zero reads, max eight named
categories and explicit indication when that is only part of the catalog.
Live general knowledge remained DIALOGUE; META remained META. No second model.

## W–X. One live provider semantic gate / latency

Evidence directory:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step4-fde7a7fd877048e4a18a57bd6685cede/provider-once/report.json`.
One session, eight operations, **8/8 PASS**, zero retries, one connection, zero
owned tasks after shutdown. Developer-created text; no user personal facts sent.
RAW terminal, normalized candidate, parsed result and request/turn IDs retained
in bounded developer evidence. No auth headers or arbitrary provider bodies.

| Case | Result | First text ms | Terminal/user path ms | Fact reads |
|---|---|---:|---:|---:|
| single | heading | 718 | 953 | 1 |
| different class | TAS | 750 | 875 | 1 |
| multi | pitch + MSL | 687 | 890 | 1 |
| summary | STATE_SUMMARY | 672 | 750 | 1 |
| unavailable engine need | CAPABILITY_GAP | 672 | 781 | 0 |
| knowledge | DIALOGUE | 687 | 1047 | 0 |
| capabilities | META_REQUEST | 687 | 828 | 0 |
| alternate geometric wording | AGL | 688 | 860 | 1 |

Cold handshake **1454 ms**, separate. Post-result isolation 250–297 ms, separate
from current response. User-path figures include Step 2 request-context ACK cost;
they are not model-only latency. Step 2 comparable semantic range was roughly
969–1141 ms; no blocking catalog regression in this small sample. Not an acoustic
latency claim, SLA proof or provider quality comparison.

The live script's coarse monotonic clock recorded local Core+render as 0 ms:
that means below clock resolution, NOT zero work. Separate 100-run offline
high-resolution medians: Gateway 0.2167 ms, deterministic render 0.0108 ms,
remaining Core/admission 0.1222 ms. No second provider gate was run for timing.

## Y–Z. Host and preservation

Actual FullVoiceService route replay covers every catalog fact, multi-fact and
summary with fake provider wire, controlled real telemetry/store/facade/Gateway,
and captured final TTS input/fake radio. One admitted response, one read, one
provider operation. Extra telemetry does not enter selected plans/output.
Synthetic add-one-fact test uses registry/binding/presentation only: no router,
input grammar or top-level semantic union edit. Synthetic fact is not shipped.

Common-fact aircraft-switch replay rereads the new generation; Hornet-only IDs
remain unexposed on the new aircraft. There are no active module-specific catalog
entries to carry over; catalog stays common. Old catalog proposal test rejects.
Physical switching is NOT proved and remains future acceptance work.

FullVoiceService, HybridAircraftCore, Interpreter, GeneralSemanticVoice, all
Step 3 TTS/radio files, Launcher and domain code are byte-for-byte unchanged.
WorldModel changes are confined to source validation and the three selected
numeric fact projections. Domain FlightContext/MissionContext users still use
unchanged packet values; no transport/lifecycle algorithm was modified.

## AA–BB. Anti-template / regression / statics

No new production question phrases, per-fact regex, synonyms, intent types,
Planner calls or provider values. Seven runtime files changed; source fingerprints
cover complete files, with separate source/behavior checks. Historical scope
assertions now compare exact old checkpoints; Step 4 changes have their own
parent-relative scope and functional gates, not a broad frozen-file exemption.

Final complete precommit regression: **3443 PASS**, five pre-existing failures,
one existing skip (Step 4 suite109 PASS). Saved as `precommit-full.xml` beside
the provider evidence directory; elapsed84.46sec. Earlier full run3441 PASS was
followed by two additional switch/timing tests and this complete final rerun.
Pre-existing failures: IA import inventory; three setup-wizard expectations;
stale Project Memory exact product-phrase expectation. Same set recorded on
Step 3/Step 2 and parent-verified in Step 1. None was “fixed” by this tranche.
Earlier intermediate test failures were outdated fixture/count/scope assumptions;
the raw-extra-data non-leak regression retained its deliberately valid extra data.
Ruff whole-tree PASS; compileall PASS; changed runtime Pyright 0 errors;
full production Pyright199 unchanged baseline errors. No unexpected regressions.

## CC–EE. Manifests and evidence levels

`docs/general-fact-surface.json` is machine-readable; `docs/general-fact-matrix.md`
groups the same records by the five dispositions. Reproduce with
`scripts/general_fact_manifest.py --write`; no live state is consulted.
`tests/test_foundation_facts.py` plus existing registry/host tests prove exposed
binding/type/unit/source/freshness/presentation/catalog coverage, negative cases,
strict gap structure, actual Lua quality behavior and extensibility.

CODE / OFFLINE FACT PASS / HOST FACT PASS / LIVE PROVIDER SEMANTIC PASS apply only
to the named scope. New LIVE DCS FACT PASS, real TX, ACOUSTIC and USER BLIND FIELD
PASS are **NOT claimed**. The Lua interpreter and controlled telemetry are not DCS.
Non-fuel raw/module candidates require their own source proof before exposure.

## FF–II. Decision / identities / product boundary

Decision **A — COMMIT STEP 4 AS-IS**, subject to the final staged-scope check and
remote verification. Fuel uncertainty is explicit, not disguised as support;
no blocking new regression or measured semantic latency regression. One commit
and push on the existing feature branch only. Final commit/tree/remote identity
is reported by the execution receipt, not guessed inside its own commit.
Canonical contract diff0; user data/data files staged0. All external evidence stays
outside Git. No merge/rebase/main modification.

ORION CORE AI FOUNDATION remains **NOT FIELD PASSED**; prior overall product field
failure is not erased by component checks. No installer or physical test here.
Stop after commit/push. Step 5 unified blind acceptance, Mixed work and persistent
user context require separate user authorization.
