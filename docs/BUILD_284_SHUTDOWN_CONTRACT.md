# Build #284 controlled shutdown contract

Baseline: ORION Alpha Windows Build #284, commit `302d3633c3d2e1c776226d5bccf74c357d1ee971`.

This baseline is field-confirmed working for Voice/STT and must not be redesigned by this lifecycle change.

## Window close / minimize to tray

Closing the Launcher window when minimize-to-tray is enabled MUST only hide the window and start/retain the tray icon.

Expected runtime after the window is hidden:

- ORION Launcher: running
- ORION Core: running
- ORION Voice / `whisper-stream.exe`: running

ORION remains operational.

## Explicit Exit from the tray

The tray `Exit` action is the only normal full-product shutdown command. The shutdown order is:

1. Voice STOP is initiated.
2. The exact Voice-owned Windows process tree is stopped, including its `whisper-stream.exe` child.
3. ORION Core is shut down.
4. The Launcher window/process exits.

A bounded timeout is required. If the owned Voice process tree does not terminate in time, only that exact tree rooted at the PID created by this Launcher is force-terminated. Global image-name killing is forbidden.

After full Exit the field invariant is:

- ORION Launcher = 0
- ORION Core = 0
- `whisper-stream.exe` = 0

## Validation gate

CI-only PR #116 exists solely to run the historical Build #284 Windows workflows against this candidate head. It must never be merged into `main`. The lifecycle change is accepted only after the generated installer passes the same real-machine Voice/STT test as Build #284 and the process-count invariant above is verified after tray Exit.
