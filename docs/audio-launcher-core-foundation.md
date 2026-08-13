# Launcher ↔ Core Audio Foundation

This milestone is deliberately separated from STT, TTS, and Voice ↔ ATC.

## Scope

1. Enumerate real Windows audio input and output endpoints.
2. Expose separate input/output selectors in Launcher, including `Windows Default`.
3. Persist stable endpoint IDs and display names.
4. Refresh endpoint lists without restarting Launcher.
5. Run a physical microphone test on the selected input endpoint.
6. Run a physical output test on the selected output endpoint.
7. Send selected endpoint IDs from Launcher to Core and have Core report the active configuration back.
8. Preserve the active Core/audio state when Launcher closes and reconnects to the same Core.
9. Keep all status, test results, and errors inside Launcher; no helper/console windows.

## Explicitly deferred

- Speech recognition/STT.
- Speech synthesis/TTS responses.
- Voice ↔ ATC routing.
- Further Ground/Tower/Departure expansion.

## Acceptance evidence

`Windows endpoints detected -> manual selection -> microphone physical test -> output physical test -> Core acknowledges selected endpoints -> Launcher reconnect preserves/displays active Core state`.
