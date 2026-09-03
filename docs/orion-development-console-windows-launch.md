# ORION Development Console Windows launch entry

## Scope and guard

This is a repository-only development convenience for the existing Console in
`tools/orion_development_console`. It does not package or install a second
Console and it does not participate in the production ORION lifecycle.

The approved FULL preflight is
`AG-20260902-214845-6986cd50-e8e13e6-r2` (`COMPLETE`, `PASS`, zero conflicts
and zero ownership drift). FULL post-implementation report
`AG-20260902-220225-8f54461a-e8e13e6-r2` is also `COMPLETE` / `PASS`, with
zero conflicts, zero ownership drift and no user decision required.

## Launch architecture

The Desktop shortcut targets the checkout's existing
`.venv\Scripts\pythonw.exe` and passes the absolute repository-local
`tools\orion_development_console\windows_entry.py` plus the explicit checkout
root. Its working directory is also the checkout root and its icon is
`branding/orion.ico`.

This is the smallest reliable option for a development tool:

- `pythonw` opens the existing Tk/ttk Console without a terminal;
- the absolute paths do not depend on `PATH`, a terminal, or the caller's
  current directory;
- future normal pulls update the code opened by the same shortcut, with no
  frozen executable rebuild;
- the wrapper adds only the verified checkout root to the import path and then
  calls the existing `run_ui` seam;
- neither the production installer nor production `orion/**` is involved.

The checked-in deterministic creator is
`tools/orion_development_console/create_windows_shortcut.ps1`. It validates
the checkout, `pythonw`, entry module, icon and destination directory before
using the native Windows shortcut COM interface. It never creates or repairs a
venv and never installs dependencies.

## Failure behavior

The Python entry validates the explicit checkout markers and the supported
`.venv\Scripts\pythonw.exe`. Once the entry has started, a missing/incomplete
repository, missing entry dependency, or other launch exception is shown in a
native `ORION Development Console` error dialog. If the shortcut target itself
is missing, Windows reports that the shortcut target is unavailable. No clone,
install, environment repair, elevation, or fallback global Python selection is
attempted.

There is no new single-instance framework. Repeated double-clicks may create
more than one Console window, matching the existing Console's lack of a
single-instance contract.

## Explorer Git context bugfix

The Windows entry always propagated the authoritative checkout root correctly,
but the first real `ПРОВЕРИТЬ ВСЁ` run exposed a separate executable-resolution
boundary. A terminal/self-check inherited Codex's bundled Git on `PATH`, while
Explorer inherited the normal user and machine environment, where `git.exe`
was not on `PATH`. The Git collector therefore raised `FileNotFoundError`
before it could inspect the valid checkout. This produced
`OV-20260903-152930-unknown-6a7c9972`, Git `UNKNOWN`, and an overall `ERROR`.

The Console now resolves an already-installed Git deterministically: current
`PATH`, then the standard Program Files Git locations, then the newest bundled
Git under GitHub Desktop. It does not install, repair, copy or mutate Git or
`PATH`. All Git operations continue to use the single explicit repository root
carried by `VerificationContext`.

The same bugfix removes the stale Overview dependency on the last immutable
Phase 2 checkpoint. Current Development Position and checkpoint preview are now
derived from the current Roadmap node and its `APPROVED_NEXT_STEP` node. The
last saved checkpoint is still displayed and remains authoritative as a saved
record, but it no longer misrepresents current derived position. The preview
uses known Git, Guard, Roadmap, verification and Development History facts;
only the existing explicit `SAVE CHECKPOINT` confirmation can persist it.

Real shortcut verification after the fix produced
`OV-20260903-153244-bfb3a96-feaf3738` on branch
`dev/adr004-post-389` at
`bfb3a96a7091de1358377f443fab53ae63c6da1e`. Git was `CHANGED`, reflecting the
intended uncommitted bugfix, rather than `UNKNOWN`; the overall local state was
therefore `CHANGED`, not repository-context `ERROR`. The visible Development
Position was `Full Development Console checkpoint · READY FOR USER SAVE`, and
the approved next step was `Low-latency natural informational presentation`.
Candidate `CP-20260903-153314-6a0bd921` was inspected in `CHECKPOINT PREVIEW ·
NOT SAVED` and cancelled. The only saved checkpoint remains
`CP-20260902-202904-12498c06`.

FULL post-implementation report
`AG-20260903-153713-14d044d4-bfb3a96-r2` is `COMPLETE` / `PASS`, with zero
conflicts, zero ownership drift and no user decision required.

## Actual development-computer entry

The validated entry created for this checkout is:

`C:\Users\Алексей\Desktop\ORION Development Console.lnk`

It targets:

`C:\Users\Алексей\Documents\GitHub\ORION\.venv\Scripts\pythonw.exe`

with arguments:

`"C:\Users\Алексей\Documents\GitHub\ORION\tools\orion_development_console\windows_entry.py" --repository "C:\Users\Алексей\Documents\GitHub\ORION"`

## Validation and lifecycle boundary

Focused tests cover explicit and launcher-relative checkout resolution,
current-directory independence, the bounded venv runtime, visible missing
checkout/runtime failures, exact existing-UI invocation, shortcut fields,
identity/branding, and absence of production lifecycle imports. Shortcut tests
write only to a temporary directory, never the actual Desktop.

The real self-check launched the Console through the actual Desktop shortcut.
It verified one GUI window titled `ORION Development Console`, the ORION icon,
Launcher-family styling, OVERVIEW, HISTORY, GUARD, EVIDENCE, SYSTEM, ROADMAP,
and the visible verify/recall/checkpoint/continue/refresh actions. The first
real launch exposed an import-root omission through the required visible error
dialog; the bounded fix was regression-tested and the same shortcut then
launched successfully.

Process snapshots before and after the launch showed only the expected
repository `pythonw` bootstrap and its existing base-runtime child for this
Console. Pre-existing SRS client/server processes retained the same PIDs. No
Core, production Launcher, DCS, provider session, microphone, or audio worker
was started. The pending final Development Checkpoint was not saved.

## User instruction

На рабочем столе дважды щёлкните «ORION Development Console».
