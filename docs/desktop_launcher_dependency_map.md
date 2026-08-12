# Desktop / Launcher dependency map (#65.5)

This inventory prevents deletion-by-guessing while the desktop stack is consolidated after the Core/Launcher process split.

## Canonical production path

`orion.desktop_launcher` -> `orion.desktop_product_launcher.WindowsOrionProductLauncher`

`WindowsOrionProductLauncher` now inherits directly from `WindowsOrionDesktopLauncher` and mixes in the product visual shell through `WindowsProductVisualMixin`. Production no longer imports or inherits from `WindowsOrionDesktopLauncherV2`.

The product launcher owns the current polished DCS setup flow and remains the only production desktop runner.

## Current layers

### `orion/desktop_app.py`
Shared cross-platform launcher state/actions and legacy desktop implementation. It is not allowed to embed ORION Core in production. Core lifecycle for production is provided by `CoreProcessManager`.

### `orion/desktop_app_windows.py`
Canonical Windows behavior layer. It supplies tray lifecycle, icon handling, settings persistence/autostart, diagnostics export and other Windows-specific behavior required by the product launcher. It is **not dead code**.

### `orion/desktop_product_visual.py`
Product visual mixin extracted from the former V2 shell. It owns the polished navigation, status strip and product pages without introducing another production launcher identity.

### `orion/desktop_app_windows_v2.py`
Compatibility shim only. It is no longer part of the production import/inheritance path. Retain it only while compatibility references exist; deletion is safe once repository/test/package searches prove nothing supported imports it.

### `orion/desktop_product_launcher.py`
Canonical production Windows shell. It directly inherits from `WindowsOrionDesktopLauncher`, adds `WindowsProductVisualMixin`, owns the five-step DCS integration flow and launches external Core through `CoreProcessManager`.

### `orion/core_process.py`
Canonical Launcher -> external Core process boundary. Closing Launcher detaches from Core; it must not implicitly terminate Core.

## Consolidation status

Completed production chain reduction:

`WindowsOrionProductLauncher -> WindowsOrionDesktopLauncher -> OrionDesktopLauncher`

with visual behavior supplied by `WindowsProductVisualMixin` rather than an intermediate launcher class.

Validation on head `529c9e7`:

- ORION CI #902: green.
- Alpha Windows Build #90: green.
- Canonical launcher boundary test enforces direct `WindowsOrionDesktopLauncher` inheritance and forbids V2 production dependency.

## Deletion criteria

A desktop module/class may be removed only when all of the following are true:

1. Code search shows no supported production import.
2. `desktop_launcher` and packaging import the canonical replacement.
3. Windows smoke tests pass.
4. Alpha Windows build passes standalone Core and Launcher -> external Core checks.
5. Installer payload remains complete.
6. No supported compatibility surface still imports the removed symbol.

## Broad-catch classification

- Background worker callbacks that catch arbitrary backend errors and marshal a user-facing error back to Tk are **boundary isolation** and may remain broad when documented.
- Tk lifecycle probes (`winfo_exists`, focus/theme operations) use `TclError` rather than `Exception` when the expected failure is a destroyed/unavailable Tk object.
- `windows_audio_worker_cli.WindowsAudioWorkerProcess._play` intentionally catches arbitrary backend exceptions only to restore worker state, then re-raises the original failure.
- `windows_audio_worker_cli.run_stdio` intentionally catches arbitrary command/backend failures at the long-lived stdio protocol boundary so one malformed request cannot terminate the worker.
- Current `launch_api`, `jtac_api` and canonical `app.py` paths reviewed in this tranche already use explicit `KeyError`/`ValueError` handling where translation to HTTP status is required.
- Any broad catch that simply `pass`es without a boundary rationale remains a cleanup candidate.

## Next implementation tranche

1. Search remaining compatibility references to `WindowsOrionDesktopLauncherV2`; delete the shim only when none are supported.
2. Continue broad-catch classification in canonical runtime/API modules, prioritizing catches that swallow failures rather than boundary catches that re-raise or report them.
3. Extend Pyright to the next critical runtime boundary only in a green increment.
4. Keep the 80% coverage, Windows smoke, Lua and Alpha Windows Build gates unchanged.
