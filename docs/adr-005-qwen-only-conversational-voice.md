# ADR-005 — Qwen-only conversational voice transport

Status: Accepted

Supersedes: ADR-004 for current voice transport policy

Accepted baseline: commit `1963c60f0f4969cf05857d840bbaeb5bd4520250`

Parent and preserved transport reference: Build #389 / commit
`816efb0594a61cd43caacad8fa0bd8afa6b8cbd3`

## Context

Build #389 validated Qwen Realtime speech-to-speech through ORION Core while
the older ORION-Voice/whisper.cpp path remained active as a local fallback.
Maintaining both transports creates parallel lifecycle, packaging, readiness,
and audio-device ownership. The callback experiment represented by Build #395
was rejected and is not an architectural baseline.

## Decision

Qwen Realtime is the only supported conversational voice transport. The local
Whisper, whisper.cpp, and ORION-Voice fallback is removed. Conversational voice
therefore requires an API key plus network and provider availability. If any is
unavailable, voice mode is unavailable; ORION provides neither local STT nor a
text-only fallback.

Qwen remains a replaceable transport provider rather than a domain dependency.
ORION Core, DCS integration, tools, authorization, and safety logic stay local.
Generic audio-device selection and WASAPI infrastructure also stay local.

Qwen is not started automatically with Launcher. The existing explicit user
action starts it. Minimizing Launcher to tray does not terminate Core or an
active Qwen session. Explicit application Exit requests a graceful Qwen stop
through Core before Core shutdown.

The Qwen audio transport behavior in Build #389 remains authoritative,
including its duplex stream, sample rates, resampling, VAD, provider session,
and WebSocket behavior. Build #395 is explicitly excluded.

## Consequences

- Voice is unavailable during provider, network, or authentication failures.
- The product no longer builds, installs, starts, or supervises ORION-Voice or
  whisper.cpp.
- Core and DCS startup do not require voice readiness because Qwen is manually
  started and voice readiness remains non-blocking.
- Existing historical documents remain records of the architecture they
  described; this ADR defines the active policy.

## Accepted Qwen-only baseline

Commit `1963c60f0f4969cf05857d840bbaeb5bd4520250` is the first accepted
Qwen-only structural baseline. Its parent, Build #389 commit
`816efb0594a61cd43caacad8fa0bd8afa6b8cbd3`, is the last accepted baseline
that contained the legacy Whisper/ORION-Voice architecture and remains the
authoritative reference for the preserved Qwen Live transport.

Acceptance evidence:

- ORION CI #1103 succeeded: 974 tests passed on Linux Python 3.11, Linux
  Python 3.12, and Windows Python 3.12.10; Ruff succeeded; Pyright reported
  zero errors and zero warnings; Lua validation succeeded.
- ORION Alpha Windows Build #396 succeeded: Qwen/audio structural
  regressions, Core and Launcher executables, product layout, installer,
  packaged smoke, and controlled legacy cleanup all succeeded.
- ORION-Voice, the Whisper runtime, and `/v1/voice/text` are absent from the
  accepted product architecture and payload.

The accepted architecture keeps Qwen Realtime as the sole conversational
voice transport and as a replaceable cloud provider. Core, DCS integration,
tools, safety/domain logic, and generic WASAPI/audio-device infrastructure
remain local. Qwen does not auto-start with Launcher; minimizing to tray
preserves the active Core/Qwen lifecycle, while explicit Exit requests a
graceful Qwen stop before Core shutdown.

The Qwen transport in `1963c60` is unchanged from Build #389. It continues to
use one full-duplex `sounddevice.RawStream`, synchronous `stream.read()` and
`stream.write()`, input resampling to 16 kHz, Qwen output at 24 kHz, output
resampling to the native device rate, and the existing VAD and WebSocket
contracts. The Build #395 callback/queue transport remains rejected and must
not be reintroduced.

The next development phase is not another architectural cleanup. It is
**Qwen Live field validation: latency, playback quality, and language**. The
accepted baseline must be measured as validated before changing latency,
sample rates, VAD, buffering, or the Qwen prompt.
