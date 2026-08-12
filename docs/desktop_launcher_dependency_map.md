# Desktop / Launcher dependency map (#65.5)

This inventory records the final desktop consolidation state after the Core/Launcher process split.

## Canonical production path

`orion.desktop_launcher` -> `orion.desktop_product_launcher.WindowsOrionProductLauncher`

`WindowsOrionProductLauncher` inherits directly from `WindowsOrionDesktopLauncher` and mixes in the product visual shell through `WindowsProductVisualMixin`.

The product launcher owns the polished DCS setup flow and is the only production desktop runner.

## Current layers

### `orion/desktop_app.py`
Shared cross-platform launcher state/actions and legacy desktop implementation. It is not allowed to embed ORION Core in production. Core lifecycle for production is provided by `CoreProcessManager`.

### `orion/desktop_app_windows.py`
Canonical Windows behavior layer. It supplies tray lifecycle, icon handling, settings persistence/autostart, diagnostics export and other Windows-specific behavior required by the product launcher. It is **not dead code**.

### `orion/desktop_product_visual.py`
Product visual mixin extracted from the former V2 shell. It owns the polished navigation, status strip and product pages without introducing another production launcher identity.

### `orion/desktop_product_launcher.py`
Canonical production Windows shell. It directly inherits from `WindowsOrionDesktopLauncher`, adds `WindowsProductVisualMixin`, owns the five-step DCS integration flow and launches external Core through `CoreProcessManager`.

### `orion/core_process.py`
Canonical Launcher -> external Core process boundary. Closing Launcher detaches from Core; it must not implicitly terminate Core.

## Removed legacy layer

`orion/desktop_app_windows_v2.py` and `WindowsOrionDesktopLauncherV2` have been removed. Repository tests enforce that the legacy module does not return and that production continues to inherit directly from `WindowsOrionDesktopLauncher`.

## Consolidation status

Final production chain:

`WindowsOrionProductLauncher -> WindowsOrionDesktopLauncher -> OrionDesktopLauncher`

with visual behavior supplied by `WindowsProductVisualMixin` rather than an intermediate launcher class.

Validated during #65.5 with green ORION CI and Alpha Windows Build runs after the production-chain consolidation; the final post-deletion gates remain the merge requirement for the PR head.

## Broad-catch classification

- Background worker callbacks that catch arbitrary backend errors and marshal a user-facing error back to Tk are **boundary isolation** and may remain broad when documented.
- Tk lifecycle probes (`winfo_exists`, focus/theme operations) use `TclError` rather than `Exception` when the expected failure is a destroyed/unavailable Tk object.
- `windows_audio_worker_cli.WindowsAudioWorkerProcess._play` intentionally catches arbitrary backend exceptions only to restore worker state, then re-raises the original failure.
- `windows_audio_worker_cli.run_stdio` intentionally catches arbitrary command/backend failures at the long-lived stdio protocol boundary so one malformed request cannot terminate the worker.
- Current `launch_api`, `jtac_api` and canonical `app.py` paths reviewed in this tranche already use explicit `KeyError`/`ValueError` handling where translation to HTTP status is required.
- Any broad catch that simply `pass`es without a boundary rationale remains a cleanup candidate.

## Remaining #65.5 merge checks

1. Final ORION CI green on Python 3.11/3.12, including Windows smoke and Lua validation.
2. Final Alpha Windows Build green on the same PR head.
3. Keep the 80% coverage gate unchanged.
4. No new product functionality in this PR.
