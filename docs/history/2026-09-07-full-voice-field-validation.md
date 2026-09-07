# First full bidirectional voice vertical — recovery checkpoint

**FIRST FULL BIDIRECTIONAL VOICE VERTICAL — CLOSED / FIELD VALIDATED.**

Recorded: 2026-09-07. Preservation only; no new implementation or physical test.

## Verified repository and commit sequence

Repository: `C:/Users/Алексей/Documents/GitHub/ORION-recovery-a955d7c`.
Branch: `recovery/a955d7c-radio-validated`.
Origin: `https://github.com/Zmnb9711/ORION.git`.
Pre-edit HEAD: `e753d0c96b5dd901df709b66fe5171d65060c005`.
Tracked and staged changes were empty. After fetching origin, the branch was
four commits ahead and zero behind, in chronological order:

1. `9362f18bd320da8e92daf6b680d68cfd08c6b8ad` — isolated Yandex Realtime STT adapter.
2. `ba627867fe92acab7d54297844c3f38339b38f61` — physical radio turn ownership and native SpeechKit v3 transport.
3. `ba43a2c52f952a43cec0adde2bce99394a6c71d1` — bounded semantic ownship vertical and protected streaming output.
4. `e753d0c96b5dd901df709b66fe5171d65060c005` — physical field closure and scalar-only input diagnostics.

The field closure includes tested diagnostics, not documentation alone. This
preservation record is added in a separate docs-only commit after it. Git is
the source of truth; the cached suggestion of only three unpushed commits was
incomplete. No merge into `dev/adr004-post-389` is authorized by this task.

## Field evidence and interpretation

The existing [field report](../full-voice-field-ready.md) supplies exact report
paths, SHA-256 fingerprints, correlation identities and user confirmations.
No report or provider transmission was regenerated for preservation.

| Scenario | Accepted evidence | Result |
| --- | --- | --- |
| First Russian PTT query: `Какой мой текущий курс и координаты?` | Nonempty finalized STT, authoritative three-fact report, exactly one completed SRS TX; user heard clear response through official SRS Client | PASS |
| Same query after heading/position change | New interaction/ToolGateway receipt, changed heading and both coordinates, exactly one completed TX; user heard clear response | PASS |
| First `Расскажи анекдот.` attempt | Silence with STT transport failure; no completed recognition/unsupported result | INCONCLUSIVE; excluded from PASS |
| Unsupported-query retry | Nonempty STT final, Core `unsupported`, zero response TX, no errors; user confirmed silence | PASS |

The retry's recognized spelling is not claimed byte-identical to the test
instruction. Nonempty recognition and unsupported routing are independently
recorded. The first failed attempt's exact transport cause remains unresolved.

Supported-turn response-start latencies are **3.266 s and 3.000 s**, measured
from physical turn end to first SRS audio frame. These are transmission-start
proxies, not acoustic-onset measurements. **The <1 s target is NOT met.**

## Preserved implementation contract

Input is `ru-RU`; protected output is currently `en-US` / `john`.
Physical SRS turn ownership feeds native SpeechKit v3 External EOU and matching
FINAL/EOU_UPDATE into an immutable finalized utterance. The bounded path uses
InteractionRouter, authoritative ToolGateway/WorldModel, strict three-fact
semantic mapping, phraseology/composition and protected streaming TTS through
RadioRouter and the existing SRS adapter/Opus/40 ms pacing path.

Qwen calls are **zero** for this bounded ownship path. Only heading, latitude
and longitude may reach the spoken report. The existing semantic regression
proves that additional telemetry cannot leak into semantic output, rendered
text, composed text or the TTS request. This does not establish general free
conversation, broader intent coverage, long-running reliability or a Launcher
migration. The previously validated Stage 7C output remains the baseline.

Existing field-closure checks: **57 tests PASS**, scoped Ruff/Pyright and diff
checks PASS. Earlier broad suite: **1768 PASS / 3 unrelated Saved Games baseline
failures**. These are historical results, not a claim of a new full-suite run.
Raw reports remain external to Git in their original Temp locations; their
fingerprints are preserved in the field report, but Temp is not a durable archive.

Preservation verification: the offline `tests/test_ownship_semantic_middle.py`
regression passed **29 tests**, with one existing Starlette deprecation warning.
Coverage writing and pytest cache updates were disabled. Documentation whitespace,
local link targets and checkpoint consistency were checked. SHA-256 comparison
confirmed all 11 original untracked files were unchanged.

## Preservation and next checkpoint

Only project memory, this history entry and the field report are changed.
Unrelated untracked artifacts present at entry are preserved: four `.coverage*`
files, `data/fa18c_value_profiles.json`, the Yandex pacing-probe document,
`orion/full_voice_qwen.py`, and four Qwen/provider/pacing test or probe files.
No cleanup, physical/provider transmission, latency optimization, runtime
change, DCS/SRS lifecycle action or dev merge is part of this task.

The authorized destination is origin's `recovery/a955d7c-radio-validated` branch,
using a normal push of the four existing commits plus this docs-only commit.
The final handoff records the resulting commit ID and verified remote divergence;
this record does not predict a successful push before it occurs.

**Exact next checkpoint:** the pushed docs-only preservation commit on this
recovery branch, with clean tracked/staged status and preserved untracked work.
On resumption verify Git, then read [project memory section 30](../ORION_PROJECT_MEMORY.md#30-first-full-bidirectional-voice-vertical--2026-09-07)
and the field report. The milestone remains CLOSED / FIELD VALIDATED. The next
proposed task is separately authorized latency profiling by stage against the
3.266/3.000 s baseline; no optimization or further development starts here.
