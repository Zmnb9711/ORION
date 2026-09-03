# ORION Development Console — Phase 2

## Canonical Recall and checkpoint candidates

FULL RECALL carries bounded D74 strategy, Golden Components, historical
reconnect candidates, recovered ideas, retirement state, current canonical
stage, and next step. TASK RECALL includes capability-linked canonical records
and its work classification. Checkpoint candidates include the canonical input
signature and register IDs with `READY_FOR_USER_SAVE`; preview does not save,
and explicit user confirmation remains mandatory.

Phase 2 adds private, bounded development memory to the separate Development
Console. It does not add a Launcher mode, start the ORION product runtime, or
change any file under `orion/**`.

## Authority and truth domains

The Console keeps three domains separate:

- historical truth comes from Architecture Guard, decisions, provenance and
  bounded Evidence metadata;
- current development state comes from Git, the applicable Guard result and an
  explicitly saved development checkpoint;
- current machine state comes only from a fresh or cached Phase 1 `OV-...`
  verification report.

A checkpoint retains an `OV-...` identifier and bounded observation metadata as
historical provenance. Reopening an old checkpoint never marks the current
machine VERIFIED.

## Private immutable records

Checkpoint records use the typed `DevelopmentCheckpoint` model and are stored
below `%LOCALAPPDATA%\ORION\development\console\checkpoints\`. Prompt records
use the typed `PromptRecord` model and are stored below
`%LOCALAPPDATA%\ORION\development\console\prompts\`.

Both stores publish create-once JSON records through a same-directory temporary
file followed by exclusive final creation. They validate a canonical content
fingerprint when reading, reject overwrite, and maintain a rebuildable derived
index. Record bodies stay private and are not committed automatically. Complete
L0 conversation bodies, secrets, provider reasoning and audio are excluded.

## Checkpoint workflow

`ЗАПИСАТЬ ИСТОРИЮ` requests an explicit current development stage and approved
next step, builds a full structured preview, and saves only after the user
selects `SAVE CHECKPOINT` and confirms immutable creation. A missing stage is a
hard validation error. A missing approved next step is recorded visibly and
blocks `ПРОДОЛЖИТЬ РАЗРАБОТКУ`; the Console does not invent one.

History keeps every checkpoint accessible with its time, ID, HEAD, Guard ID,
stage, next step and proof summary. It supports open, comparison with current,
comparison with another checkpoint, checkpoint-recovery prompt generation and
prompt copy. Comparisons emphasize decisions, implementations, proof-state
transitions, Evidence, Previous Best, risks/problems and development position;
a HEAD-only change is deliberately low-noise.

## Recall and prompt workflow

`ВСПОМНИТЬ ВСЁ` composes a bounded visible FULL RECALL prompt from the applicable
Guard, Git, decision state, project documents, latest checkpoint, current
verification, Evidence and Previous Best records. `TASK RECALL` invokes the
actual Guard capability/history chain before composing focused context and
requires clarification when capability resolution is ambiguous.

`ПРОДОЛЖИТЬ РАЗРАБОТКУ` requires the latest explicitly saved checkpoint and its
approved next step, then adds fresh Git, current Guard, current verification and
a semantic checkpoint comparison. Every generated prompt receives a new
immutable `PromptRecord`; regeneration never overwrites an older record.

The entire prompt is shown before external use. `COPY PROMPT` is the supported
transfer path, and `SAVE PROMPT` exports an explicit private text copy. Direct
ChatGPT/Codex send remains disabled and unsupported because no approved Console
integration contract exists.

## ORION-family interface

The dev-only theme adapter reuses the Launcher visual language without importing
Launcher lifecycle or Core classes: clam-based ttk, dark navy surfaces, cyan
accent, Segoe UI, approved `orion.ico`, sidebar navigation, cards, status strip,
button states and scrolling. Persistent identity is `ORION / DEVELOPMENT
CONSOLE`, so the tool belongs to the product family without being confused with
the normal Launcher.

Views are `OVERVIEW`, future-only `ROADMAP · PHASE 3`, `HISTORY`, `GUARD`,
`EVIDENCE`, and `SYSTEM`. Phase 1 `ПРОВЕРИТЬ ВСЁ` and its Git/History/Logs/
Evidence/Installed ORION/Local Data/DCS/SRS presentation remain available.
Graphical roadmap implementation is intentionally excluded from Phase 2.

## Next boundary

The exact next scope is `DEVELOPMENT CONSOLE PHASE 3 — GRAPHICAL LIVE ROADMAP`,
using Guard graph, checkpoints, Git, Evidence, proof states and the explicitly
recorded development stage/next step. Phase 2 contains no graphical roadmap.
