# Yandex Realtime Reference Tester v1.1A + SRS Radio v0.1

`YandexRealtimeTester` is a standalone Windows reference application for
speech-to-speech testing with Yandex AI Studio Realtime API and deterministic
PortAudio endpoints. It does not import ORION modules and is not part of the
ORION production runtime. Direct Audio remains the validated v1.1A path. The
isolated experimental SRS Radio v0.1 path is a sibling session and does not
import or modify ORION production. The tester does not contain ATC, DCS, HOTAS, tools, function
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
`UNSUPPORTED AUDIO FORMAT`; v1.1A does not resample or alter PCM. Capture and
playback use persistent blocking streams and an unbounded provider-order output
FIFO. Each decoded provider delta is split into exact response-scoped 20 ms
slices (at most 882 frames / 1,764 bytes). The final short slice is written
without padding. Concatenating uninterrupted writes therefore reproduces the
decoded provider PCM byte-for-byte. No WAV, PCM dump, or audio file is created.

`START SESSION` and `STOP SESSION` use a background network event loop and
bounded shutdown. A new session object is created for every Start, so repeated
Start → Stop cycles do not reuse a closed WebSocket. Server VAD automatically
creates turns. Following the official example, `speech_started` invalidates the
response-owned playback epoch and removes its queued slices. One already
committed short write may finish; no subsequent stale slice can start. The
persistent output stream remains open, and normal provider audio is never
reordered, padded, or dropped. This generic path does not inspect transcript
text.

## Analysis-only playback/microphone correlation probe

v1.1A copies the exact microphone blocks and only the response-scoped slices
that are committed immediately before `RawOutputStream.write()` into a bounded
diagnostic queue. Queue submission is non-blocking: if analysis falls behind,
only the diagnostic job is dropped and counted. The microphone send, playback
write, 20 ms slicing, VAD, and interruption paths never consult probe results.

The worker keeps at most 1,000 ms of recent playback reference in memory and
searches playback-to-microphone lag from 0 through 500 ms. Correlation operates
on a diagnostic-only 4,900 Hz feature copy made by retaining every ninth sample
from the 44,100 Hz PCM; live audio is never resampled. Each candidate pair is
mean-centered. The signed normalized correlation preserves possible polarity
inversion, while its absolute value measures gain-independent similarity. At
the best lag, least-squares scalar gain is fitted and the residual RMS divided
by centered microphone RMS is recorded as an observational double-talk metric.

Every server `speech_started` event receives a scalar snapshot aggregated over
200 ms before through 300 ms after the event. Playback-active and idle controls
are sampled every 100 ms. Results are response/epoch-associated scalar values,
not behavioral echo classifications. No result gates, delays, suppresses, or
changes audio. Raw and decimated audio exist only in bounded memory and are
released at session shutdown; exports contain derived scalars only.

## Diagnostic export

`EXPORT DIAGNOSTIC REPORT` writes a human-readable UTF-8 text report for the
most recent session. Export works after success, failure, or manual Stop and
does not reconnect, open an audio device, or consume API quota. It includes
application/runtime versions, safe session configuration, exact PortAudio
device/Host API details, input aggregate RMS/peak/silence metrics, VAD and
transcription counts, connection/close state, response latency and delta
cadence, response-scoped slicing/invalidation and current-write counters,
playback/microphone correlation distributions and speech-start snapshots,
sanitized errors, and a compact event timeline.
It never includes credentials, Base64 audio, or raw PCM.

## Build the standalone executable

```powershell
.\build.ps1
```

The output is `YandexRealtimeTester\YandexRealtimeTester.exe`. PyInstaller
packages Python, Tkinter, aiohttp, sounddevice, and their runtime dependencies.
It also packages the pinned x64 `libopus 1.6.1` DLL, `samplerate==0.2.4`, NumPy,
and the native/license material required by those components. The frozen
offline codec/resampler check is available as:

```powershell
YandexRealtimeTester\YandexRealtimeTester.exe --srs-offline-smoke-test
```

That switch creates and destroys one Opus encoder/decoder and performs a short
in-memory resample. It opens no SRS/Yandex connection and no PortAudio stream.

## SRS Radio v0.1 architecture

Select `Audio Mode: SRS Radio` to replace the Direct Audio device panel with
SRS host, port, bot name, EAM password, frequency, and modulation controls.
SRS Start does not enumerate or validate devices, call PortAudio format checks,
or open a Windows input/output stream. All bot audio follows this path:

```text
SRS Opus mono 16 kHz / 40 ms
→ strict SRS packet decode and original-sender arbitration
→ stateful 16 kHz → 44.1 kHz resampling
→ exact 20 ms Yandex input blocks
→ complete response-scoped Yandex output buffer
→ stateful 44.1 kHz → 16 kHz resampling
→ Opus mono 16 kHz / 40 ms
→ absolute-deadline paced SRS UDP TX
```

The current compatibility target is SRS 2.4.x, tested against 2.4.0.0. TCP is
UTF-8 newline-delimited JSON. Start requires `SYNC`, server version validation,
enabled External AWACS Mode, successful password authentication yielding
coalition 1 or 2, one 251.000 MHz AM radio update, then an exact 22-byte UDP
ClientGuid echo. Voice is not accepted or transmitted before that echo.

The strict UDP codec uses a 6-byte header, Opus/frequency dynamic segments, and
the current 57-byte fixed tail: uint32 UnitID, uint64 PacketID, one hop byte,
22-byte OriginalClientGuid, and 22-byte current/final sender Guid. Malformed
lengths, offsets, frequencies, modulation, or GUIDs are rejected before Opus.
The original GUID identifies the human through the TCP registry. Packets whose
original or current sender is the bot are dropped before decode, so bot TX
cannot become Yandex input.

v0.1 accepts one human origin at a time. A transmission ends after a 400 ms
packet gap. The bridge then sends exactly 400 ms of bounded zero PCM to Yandex
input so the existing server VAD can observe end-of-speech; it sends no infinite
idle stream. Provider output is kept in one bounded response-scoped buffer and
is eligible for radio only after both `response.output_audio.done` and a
completed `response.done`. A failed/cancelled/oversized response is not sent.

Bot TX waits for the 400 ms RX end plus a 250 ms guard. Frames are sent every
40 ms against absolute monotonic deadlines with monotonically increasing
PacketID. If a human begins after bot TX has already started, v0.1 records the
collision, drops those packets from Yandex input, and finishes the current
bounded bot transmission. Mid-TX cancellation, auto-reconnect, multiple radios,
encryption, retransmit, radio effects, DCS radio state, and direct streaming of
provider deltas are deliberately deferred.

## Controlled no-DCS SRS field test

The first live test is manual. Do not run it from automated validation.

1. Start an isolated SRS Server 2.4.0.0 on port 5002. Enable External AWACS
   Mode with a temporary test password, disable LOS and distance, leave
   encryption off, and do not configure 251.000 as an echo/test frequency.
2. Keep DCS, ORION, and Qwen closed. Start the official SRS Client manually,
   connect to the same server in External AWACS Mode, authenticate into the
   intended coalition, tune one radio to 251.000 AM, and select the desired
   human microphone/output devices in that human client only.
3. Start the packaged tester, select `SRS Radio`, enter Yandex credentials,
   `127.0.0.1`, port `5002`, bot name `ORION YANDEX TEST`, the same EAM
   password, frequency `251.000`, and `AM`.
4. Press Start and require the sequence `CONNECTING_TCP`, `SYNCING`,
   `AUTHENTICATING_EAM`, `REGISTERING_RADIO`, `REGISTERING_UDP`, `READY`.
   Any coalition 0, version rejection, or missing UDP echo is a failure.
5. From the human SRS client transmit: `Орион, проверка связи. Как меня слышно?`
   Release PTT. The tester itself must remain silent locally; the reply must be
   heard only through the human SRS client.
6. Repeat with `Расскажи коротко, что ты умеешь.` Verify a distinct second
   turn, no stale audio, and no self-generated Yandex turn.
7. Before a later bot answer starts, make one more short human transmission.
   The bot must extend the busy wait and begin only after the final 400+250 ms.
8. Press Stop, require bounded `STOPPED`, then Start again and verify a fresh
   GUID/session/PacketID state with another turn.

Export diagnostics only after Stop. Reports contain scalar counters, masked
GUIDs, timing, response sizes, pacing jitter, and close status. They never
persist the EAM password, API key, Authorization header, raw TCP auth message,
Opus, PCM, Base64 audio, packet hex, or SRS-mode transcript text.

## Logitech v1.1 field gate

Keep ORION, DCS, and Qwen closed. Select the currently enumerated Logitech PRO X
Gaming MME input and output endpoints; do not rely on historical indices. First
verify uninterrupted normal playback. Then request a long response and say
`стоп` once while it is clearly playing. The audible old response should stop
promptly, the session should remain alive, the new response should play, and old
PCM must not resume. Repeat with a generic phrase such as
`подожди, я хочу спросить другое`. Stop normally and export only after Stop.

## Dream Air v1.1A controlled observation

Keep ORION, DCS, and Qwen closed. Connect Dream Air normally, select
`REFRESH DEVICES`, then choose the currently enumerated endpoints matching:

- Input: `Микрофон (Pimax Dream Air)` on MME
- Output: `Pimax m (NVIDIA High Definition...)` on MME

Do not rely on historical indices. Enter the API key and Folder ID, keep model
`speech-realtime-260528`, voice `dasha`, and language `Russian (ru-RU)`, then
start and preserve the Windows microphone level for every phase. Collect, in
order: playback-only while completely silent; normal `стоп` during playback;
generic `подожди, я хочу спросить другое` during playback; quiet `стоп` during
playback; `проверка микрофона без воспроизведения` while Yandex is silent; then
20–30 seconds of silence. v1.1A intentionally contains no echo suppression, so
existing Dream Air false interruptions remain expected. Stop normally and
export only after the UI reports stopped/disconnected.

## v1.1A limitations

- No resampling, echo cancellation, or custom DSP.
- Correlation and residual measurements are forensic observations only; no
  threshold or label controls runtime behavior.
- No function calling, MCP, web/file tools, ATC, DCS, or ORION integration.
- No credential persistence.
- Input transcription and output transcript are displayed only when the
  provider emits documented events; none are synthesized locally.
- WebSocket close codes are reported only when the transport supplies one.
