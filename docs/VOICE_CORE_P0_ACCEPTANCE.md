# ORION Voice Core — P0 acceptance gate

Voice Core is a release-blocking P0. No ATC/mission feature work is accepted until the installed-product voice path passes this gate.

## Required diagnostic stages

1. **Product identity**
   - Report Launcher build/commit and executable path.
   - Report Core build/commit, PID and executable path.
   - Report Whisper executable path/version and model path.
   - The installed files, not `dist-product`, are the test subject.

2. **Microphone capture**
   - Resolve the configured Windows/WASAPI input.
   - Capture the control phrase to a persistent diagnostic WAV under `%LOCALAPPDATA%/ORION/diagnostics/voice/last-microphone-test.wav`.
   - Report sample rate, channels, duration and file size.

3. **Recording playback**
   - Play the exact persisted microphone WAV through the configured output.
   - This stage is independent from STT.

4. **Whisper executable self-test**
   - Verify runtime files/model before recognition.
   - Launch the real installed `whisper-cli.exe` independently and record command, cwd, exit/status, stdout and stderr.
   - A native-process crash is a hard failure and must not be reported as a phrase-recognition failure.

5. **STT recognition**
   - Pass the exact persisted microphone WAV from stage 2 to Whisper.
   - Preserve stdout/stderr/transcript diagnostics.
   - Display the recognized text explicitly.
   - Control phrase: `Привет. Как дела?`.

6. **TTS independent test**
   - Must run even if STT failed.
   - Render and play: `Всё хорошо. Связь установлена.` through the configured output.

7. **Full conversation acceptance**
   - Input: spoken `Привет. Как дела?`.
   - Visible recognized text must contain the control phrase.
   - Audible response: `Всё хорошо. Связь установлена.`.

## CI / release requirements

A build must not be handed to the user for voice testing until all automatable stages pass on Windows as an **installed product**:

- build the production installer;
- install it to the normal installation location;
- verify installed Launcher/Core identity and hashes;
- launch the installed Core/Launcher paths;
- exercise real Whisper with a real speech WAV;
- exercise TTS rendering;
- exercise the complete audio-file STT -> Core -> TTS pipeline;
- run an upgrade test from the previous installer and prove old processes/payload cannot masquerade as the new build.

Physical microphone/speaker validation on the user's specific hardware is the final environment-specific check only after the installed-product gate passes.

## Diagnostic artifact

Every Voice Diagnostic run must leave a self-contained diagnostic directory containing at least:

- `manifest.json` with build IDs, PIDs, executable paths and hashes;
- `last-microphone-test.wav`;
- Whisper command/cwd/environment summary;
- Whisper stdout/stderr and native exit/status;
- recognized transcript;
- TTS rendered WAV;
- stage-by-stage PASS/FAIL/SKIP results.

Diagnostics must not disappear with a temporary directory.
