# Desktop / Launcher dependency map (#65.5)

This inventory exists to prevent deletion-by-guessing while the desktop stack is consolidated after the Core/Launcher process split.

## Canonical production path

`orion.desktop_launcher` -> `orion.desktop_product_launcher.WindowsOrionProductLauncher`

`WindowsOrionProductLauncher` currently inherits from `WindowsOrionDesktopLauncherV2`, which in turn inherits from `WindowsOrionDesktopLauncher`.

The product launcher owns the current polished DCS setup flow and therefore remains the production shell.

## Current layers

### `orion/desktop_app.py`
Shared cross-platform launcher state/actions and legacy desktop implementation. It is not allowed to embed ORION Core in production. Core lifecycle for production is provided by `CoreProcessManager`.

### `orion/desktop_app_windows.py`
Windows behavior layer. It currently supplies tray lifecycle, icon handling, settings persistence/autostart, diagnostics export and other Windows-specific behavior used by the subclasses. It is therefore **not dead code** yet.

### `orion/desktop_app_windows_v2.py`
Visual shell layered on `WindowsOrionDesktopLauncher`. Direct repository references are limited to its own definition and the product launcher (plus static-analysis/config references). It is therefore a **candidate for consolidation**, not an independently supported production entry point.

### `orion/desktop_product_launcher.py`
Canonical production Windows shell. It owns the current five-step DCS integration flow and must remain behaviorally unchanged during consolidation.

### `orion/core_process.py`
Canonical Launcher -> external Core process boundary. Any desktop cleanup must preserve this boundary. Closing the Launcher must not implicitly terminate Core.

## Consolidation target

Reduce the production inheritance chain from:

`WindowsOrionProductLauncher -> WindowsOrionDesktopLauncherV2 -> WindowsOrionDesktopLauncher -> OrionDesktopLauncher`

to a structure with one canonical Windows product shell plus one clearly named shared behavior base/mixin where needed. The intermediate V2 identity should disappear once its visual methods are absorbed by the canonical product shell or canonical Windows base.

## Deletion criteria

A desktop module/class may be removed only when all of the following are true:

1. Code search shows no supported production import.
2. `desktop_launcher` and packaging import the canonical replacement.
3. Windows smoke tests pass.
4. Alpha Windows build passes both standalone Core and Launcher -> external Core checks.
5. Installer payload remains complete.
6. No test relies on the removed class as a supported compatibility surface, or an explicit compatibility shim is retained.

## Broad-catch classification in this stack

- Background worker callbacks that catch arbitrary backend errors and marshal a user-facing error back to Tk are process/UI boundary isolation and may remain broad if documented.
- Tk lifecycle probes (`winfo_exists`, focus/theme operations) should prefer `TclError` rather than `Exception` when the only expected failure is a destroyed/unavailable Tk object.
- File/OS operations should keep explicit `OSError`-family catches.
- Any broad catch that simply `pass`es without a boundary rationale is a cleanup candidate.

## Next implementation tranche

1. Narrow Tk-only broad catches to `TclError` where behavior is unchanged.
2. Add/import tests around the canonical product shell and CoreProcessManager boundary.
3. Move shared Windows behavior behind a canonical base name.
4. Absorb the V2 visual shell into the canonical production class/base.
5. Delete the V2 module only after full Windows build validation.
