# Yandex Realtime Reference Tester v1

`YandexRealtimeTester` is a standalone Windows reference application for
speech-to-speech testing with Yandex AI Studio Realtime API and deterministic
PortAudio endpoints. It does not import ORION modules and is not part of the
ORION production runtime. It does not contain ATC, DCS, HOTAS, tools, function
calling, provider selection, or ORION credential storage.

## Current provider contract

- Endpoint: `wss://ai.api.cloud.yandex.net/v1/realtime`
- Authentication: `Authorization: Api-Key <API_key>`
- Model URI: `gpt://<folder_ID>/speech-realtime-260528`
- Model query: `?model=gpt://<folder_ID>/speech-realtime-260528`
- Input and output: headerless mono signed PCM16 little-endian at 44,100 Hz
- Input event: `input_audio_buffer.append` with Base64 audio
- Output event: `response.output_audio.delta` with Base64 audio
- Russian recognition setting: `languages: ["ru-RU"]`
- Default voice: `dasha`
- Server VAD: threshold `0.5`, silence duration `400 ms`

The session payload follows the post-May 12, 2026 nested schema under
`session.audio.input` and `session.audio.output`. The current Yandex model
catalog and May 28 release notes list `speech-realtime-260528`; some generated
Realtime event-reference text and the general voice-agent tutorial still say
that only, or exemplify, `speech-realtime-250923`. This tester deliberately
uses the current catalog target `speech-realtime-260528` and does not silently
fall back to the older model. The generated server-event index also labels some
audio-delta pages as "currently not supported," while the current official
voice-agent tutorial uses those events for live speech playback; this tester
follows the working tutorial flow and records the actual events received.

Official references:

- [Realtime API format update](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/agents/realtime-changes.html)
- [Voice agents and audio schema](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/agents/realtime.html)
- [Official voice-agent example](https://aistudio.yandex.ru/docs/en/ai-studio/operations/agents/create-voice-agent.html)
- [Available models](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/models.html)
- [Realtime client events](https://aistudio.yandex.ru/docs/en/ai-studio/clientEvents/index.html)
- [Realtime server events](https://aistudio.yandex.ru/docs/en/ai-studio/serverEvents/)
- [AI Studio authentication](https://aistudio.yandex.ru/docs/en/ai-studio/api-ref/authentication.html)

## Credentials

Use a Yandex Cloud service-account API key with access to Realtime API and the
service account's parent Folder ID. The API key remains only in process memory.
It is not written to settings, logs, reports, or build metadata. Reports also
redact Authorization, Api-Key, Bearer, IAM-token, and query-token patterns.

## Run from source

```powershell
cd reference_tests\yandex_realtime_gui
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python yandex_realtime_tester.py
```

The application enumerates devices using `sounddevice.query_devices()` and
`sounddevice.query_hostapis()`. Input and output lists include every eligible
PortAudio endpoint, including MME and WASAPI, with concrete numeric index,
device name, and Host API. Duplicate names remain distinct. The selected index
is passed directly to `RawInputStream` or `RawOutputStream`; it is never
re-resolved by name. Refresh preserves only the same complete endpoint identity
and clears a stale selection instead of substituting another endpoint.

Before a WebSocket connection is attempted, both selected devices are checked
for mono PCM16 at 44,100 Hz. An incompatible device produces
`UNSUPPORTED AUDIO FORMAT`; v1 does not resample or alter PCM. Capture and
playback use persistent blocking streams, an unbounded provider-order output
FIFO, and one provider audio delta per queue item. No WAV, PCM dump, or audio
file is created.

`START SESSION` and `STOP SESSION` use a background network event loop and
bounded shutdown. A new session object is created for every Start, so repeated
Start → Stop cycles do not reuse a closed WebSocket. Server VAD automatically
creates turns. Following the official example, `speech_started` invalidates and
clears only queued playback from the interrupted response; normal provider
audio is never reordered, padded, or dropped.

## Diagnostic export

`EXPORT DIAGNOSTIC REPORT` writes a human-readable UTF-8 text report for the
most recent session. Export works after success, failure, or manual Stop and
does not reconnect, open an audio device, or consume API quota. It includes
application/runtime versions, safe session configuration, exact PortAudio
device/Host API details, input aggregate RMS/peak/silence metrics, VAD and
transcription counts, connection/close state, response latency and delta
cadence, playback counters, sanitized errors, and a compact event timeline.
It never includes credentials, Base64 audio, or raw PCM.

## Build the standalone executable

```powershell
.\build.ps1
```

The output is `YandexRealtimeTester\YandexRealtimeTester.exe`. PyInstaller
packages Python, Tkinter, aiohttp, sounddevice, and their runtime dependencies.

## Dream Air field test

Keep ORION, DCS, and Qwen closed. Connect Dream Air normally, select
`REFRESH DEVICES`, then choose the currently enumerated endpoints matching:

- Input: `Микрофон (Pimax Dream Air)` on MME
- Output: `Pimax m (NVIDIA High Definition...)` on MME

Do not rely on historical indices. Enter the API key and Folder ID, keep model
`speech-realtime-260528`, voice `dasha`, and language `Russian (ru-RU)`, then
start. Say `Привет. Как дела?` and converse in Russian for at least 30 seconds.
Verify VAD events, any provider transcription, audio deltas and latency, clear
playback, Stop, a second Start, and a clean close. Stop and export the report.
Only after Dream Air passes, repeat with Logitech endpoints.

## v1 limitations

- No resampling, echo cancellation, or custom DSP.
- No function calling, MCP, web/file tools, ATC, DCS, or ORION integration.
- No credential persistence.
- Input transcription and output transcript are displayed only when the
  provider emits documented events; none are synthesized locally.
- WebSocket close codes are reported only when the transport supplies one.
