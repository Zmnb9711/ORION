# Hybrid Aircraft successful field freeze — 2026-09-08

ORION ARCHITECTURE GUARD: OFF (historical recovery exemption).

Runtime source: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`.
Documentation-only parent: `8f8009c5e7e00eb3c59eb0247156b005dd932729`.
This freeze changes documentation only; the same runtime remains the baseline.

Evidence: `C:\Users\Алексей\AppData\Local\ORION\runtime\test-evidence\ORION-Test-Evidence-20260908-173035.zip`.
SHA-256: `8E85904B00D198D5556D11027653A58CDB36B0305618682A85CF689EA0D25272`.
Test session: `110867ca9e7b4cc990b326bf54035dee`.
Runtime session: `b3bafadb7bf346a380193a356cebfef0`.

Mixed turn: `ebf02d5c-d396-494c-945a-3c2eb00a771b`.
Exact FINAL: `добрый день в каком самолете я нахожусь`.
LOCAL decomposition: GREETING [0,11), AIRCRAFT_IDENTITY_QUERY [12,39).
Validation accepted; Core route FREE_PLUS_AIRCRAFT_IDENTITY; provider count 0.
One completed `orion.world.ownship.get` receipt; aircraft `FA-18C_hornet`,
source `dcs_export`, authority `authoritative`, generation 4019, status known.
Finalized text and exact TTS input:
`Добрый день! По данным DCS, вы находитесь в F/A-18C Hornet.`
SRS TX completed, 143 frames; response_terminal completed, no failure.
The user explicitly confirmed hearing the correct mixed response.

Frozen ownship regression: turn `6827c2d1-6d58-4a4d-b007-4a93eec2267f`.
Exact FINAL: `какой мой текущий курс и координаты`.
Route FROZEN_OWNSHIP; provider count 0; SRS TX completed, 385 frames.
The user reports the same-session frozen regression passed. This ZIP does not
contain an exact ownship source-value/TTS transcript pair; no additional
numerical reconstruction is inferred from it.

Identity limitation: the ZIP explicitly says `orion_build_sha=unknown`.
Later inspection found installed Core and Launcher SHA-256 equal to the
artifacts built from f0c9e364. That corroborates the user's source attribution
but does NOT insert identity evidence into the earlier physical session.
Original evidence is preserved unchanged. No new PTT/provider test was run to
create this record.

Status: HYBRID AIRCRAFT LOCAL ROUTING — FIELD VALIDATED, with the above explicit
artifact-identity limitation. Frozen ownship regression PASS. No conversation,
Planner, memory or mixed generated-fact capability is implied by this freeze.
