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

Core follows the same containment rule. The packaged Core writes its exact PID to `runtime/orion-core.pid`. If Launcher reconnects to an already-running healthy Core, that PID is accepted only after Windows confirms that the PID belongs to `ORION-Core.exe`. Full Exit first requests termination of that exact PID, waits for a bounded timeout, and only then force-terminates the same PID if needed. No `taskkill /IM ORION-Core.exe` or other global image-name kill is allowed.

After full Exit the field invariant is:

- ORION Launcher = 0
- ORION Core = 0
- `whisper-stream.exe` = 0

## Validation gate

Build #284 remains the immutable Voice/STT golden baseline. A lifecycle candidate may become the next baseline only after its generated Windows installer passes the same real-machine Voice/STT test as Build #284 and verifies both tray persistence and the process-count invariant above after explicit tray Exit.
