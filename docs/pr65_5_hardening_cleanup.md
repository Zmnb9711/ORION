# PR #65.5 — Hardening and Cleanup

## Goal
Reduce latent defect risk after the canonical Core/Launcher deployment reconstruction without mixing in new product functionality or cosmetic rewrites.

## Baseline already satisfied on main
- Canonical dependencies live in `pyproject.toml`; `requirements.txt` delegates to it.
- Coverage gate is 80%.
- Ruff correctness/bug-risk checks are active.
- Pyright has an initial critical-module gate.
- Windows smoke and Lua syntax validation are CI gates.
- Native WASAPI playback validates and applies volume scaling.
- Canonical deployment separates ORION Core and Launcher processes.

## Remaining #65.5 work

### 1. Broad exception inventory
Every `except Exception` in production code must be classified as one of:
- **boundary isolation** — deliberate last-resort containment at an observer/plugin/UI/process boundary; must log enough context and have a test proving one failure does not corrupt the parent operation;
- **narrowable** — replace with explicit expected exception classes;
- **bug masking** — remove the catch and allow the defect to fail visibly.

No new broad catch may be added without an inline boundary rationale.

### 2. Legacy/dead-code inventory
Classify duplicate desktop/launcher implementations after #80 as:
- canonical production path;
- compatibility shim still imported by supported entry points/tests;
- obsolete implementation safe to delete.

Deletion is allowed only after repository references, packaging imports, Windows build imports and tests prove the path is unused.

### 3. Static-analysis expansion
Expand Pyright from the initial hand-picked modules toward critical runtime boundaries in small green increments. Expand Ruff only with correctness/bug-risk rules; avoid repository-wide formatting/style churn.

### 4. Runtime invariants
Preserve these invariants while cleaning:
- storing a mission snapshot is not rolled back by an optional observer failure;
- optional observer failures are visible in logs;
- Launcher never embeds Core in-process;
- Core remains independently runnable;
- Windows installer continues to package the complete canonical runtime and DCS integration resources.

## First tranche
1. Document this baseline.
2. Audit broad catches in canonical Core/runtime paths before touching compatibility UI code.
3. Add focused regression tests before narrowing/removing catches where behavior can change.
4. Inventory desktop/launcher module references and delete only demonstrably dead implementations.
5. Extend static-analysis gates only after the preceding cleanup is green.

## Merge gates
- ORION CI green on Python 3.11/3.12.
- Windows smoke green.
- Lua syntax validation green.
- Alpha Windows build green when packaging/deployment paths are touched.
- No reduction of the 80% coverage gate.
- No new product features in this PR.
