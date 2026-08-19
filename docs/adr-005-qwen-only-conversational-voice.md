# ADR-005 — Qwen-only conversational voice transport

Status: Accepted

Supersedes: ADR-004 for current voice transport policy

Baseline: Build #389 / commit `816efb0594a61cd43caacad8fa0bd8afa6b8cbd3`

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
