# ORION Launcher Alpha 0.1 Readiness

## Goal
Finish the canonical Windows Launcher for the first real Alpha 0.1 installation and DCS acceptance test without adding unrelated product functionality.

## Scope
- validate canonical Launcher -> external Core lifecycle and reconnect behavior
- validate DCS installation discovery and active-installation selection
- validate Saved Games profile selection and integration installation
- validate first-run/setup/recovery state transitions
- validate telemetry readiness reporting and diagnostics export
- validate restart/reopen behavior after Launcher closes while Core remains running
- validate installer and portable bundle contents from the same head
- validate upgrade/uninstall behavior where CI can exercise it
- remove stale launcher-era artifacts only when demonstrably superseded

## Non-goals
- Mission Studio implementation
- new AI/provider functionality
- new ATC, AWACS, JTAC, AAR, Mission Control or aircraft features
- another Core/Launcher architecture rewrite

## CI merge gates
1. ORION CI green on Python 3.11 and 3.12.
2. Windows smoke green.
3. Lua syntax validation green.
4. Alpha Windows Build green.
5. Installer and portable product bundle produced from the same PR head.
6. Canonical Launcher must start/attach to external Core; Launcher exit must not implicitly terminate Core.
7. Coverage gate must remain at or above the existing 80% threshold.

## Real-PC acceptance gate
The release candidate is not considered Alpha 0.1 accepted until one real Windows 11 + DCS pass completes:

`install -> launch ORION -> detect/select DCS -> select Saved Games -> install integration -> start/attach Core -> launch DCS -> receive telemetry -> close Launcher -> verify Core survives -> reopen Launcher -> verify reconnect -> export diagnostics`

Failures found in that pass belong in this readiness PR unless they require a separate architectural change.
