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
