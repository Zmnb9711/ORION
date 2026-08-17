# ADR-004 — Cloud Realtime Voice / Qwen vertical slice

**Date:** 2026-08-17  
**Status:** Approved direction for experimental validation

## Context

ORION should minimize local CPU/GPU load so DCS World and VR retain the maximum possible compute budget. The local ORION runtime remains necessary as the deterministic DCS integration/gateway layer, but AI inference does not need to run locally when Internet connectivity is available.

The current local `whisper.cpp` path remains useful as a proven/fallback voice path, but it should not dictate the long-term voice architecture.

The project evaluated cloud STT + LLM + TTS and native cloud speech-to-speech approaches. A native realtime audio model can move speech recognition, reasoning and speech generation to the cloud while ORION Core remains responsible for DCS state, validated tools/actions and runtime safety.

Qwen3.5 Omni Realtime (initial candidate: Flash Realtime) is selected for the first experimental vertical slice because it is a cloud realtime audio-in/audio-out candidate with Russian/English support and realtime function/tool calling suitable for ORION Core integration. Availability, latency, billing/payment from Russia and real aviation-language quality must be validated in practice; this ADR does not treat those operational questions as already proven.

## Decision

Adopt a **cloud-first, provider-separated realtime voice architecture** for the next ORION voice experiment.

Target flow:

`Microphone -> Qwen Realtime cloud <-> ORION Core/tools <-> DCS -> Qwen Realtime cloud -> Audio output`

Local responsibilities:

- ORION Core and canonical runtime;
- DCS telemetry/state integration;
- deterministic and validated tool/action execution;
- Launcher/service lifecycle and configuration;
- audio capture/playback and network transport;
- diagnostics, transcripts/events and tool-call logging.

Cloud responsibilities for the Qwen experiment:

- realtime speech understanding;
- conversational/reasoning layer;
- selection of ORION tools/functions;
- realtime speech generation.

`whisper.cpp` is **not deleted**. It remains the existing/fallback path until the cloud realtime path proves superior and stable in real Windows/DCS testing.

## Implementation order

Do **not** begin by adding many ATC/AWACS/JTAC/AAR capabilities to Core. First prove one complete vertical path.

1. Add Qwen as a separate provider/backend managed by the ORION runtime and surfaced in Launcher.
2. Launcher controls/configures the provider and displays connection/readiness state; Launcher must not contain DCS or AI business logic.
3. Establish Qwen session lifecycle, credentials/configuration, reconnect/error handling and diagnostics.
4. Expose only one or two safe test tools from Core, e.g. `ping_core()` / `get_orion_status()`.
5. Prove Qwen -> tool call -> ORION Core -> tool result -> Qwen response without adding product modules.
6. Add realtime microphone input and audio output.
7. Run a dedicated voice smoke test covering latency, CPU/GPU load, RU/EN, callsigns, numbers/frequencies, interruption/VAD behavior, network recovery and tool-call correctness.
8. Only after the vertical slice is green, expand the Core tool surface for real product modules such as ATC, AWACS/GCI, tanker/AAR, JTAC/FAC and Mission Control.

## Architectural boundary

Launcher remains a control surface, not an AI/DCS execution host.

Preferred separation:

`Launcher -> manages/configures runtime`

`Qwen Provider <-> ORION Core <-> DCS`

The provider boundary must remain replaceable so Qwen is not hard-wired into Core. Future realtime/cloud providers should be addable without rewriting DCS integration or product modules.

## Acceptance criteria for the vertical slice

The experiment is successful only if real Windows testing demonstrates:

- stable Qwen realtime session lifecycle;
- correct Core tool invocation and argument/result round-trip;
- realtime audio input/output without local AI inference;
- acceptable end-to-end conversational latency;
- materially lower local AI CPU/GPU load than the local Whisper path;
- usable Russian and English aviation speech;
- reliable recognition of callsigns, digits, frequencies and aviation terms;
- usable interruption/VAD behavior in DCS cockpit audio conditions;
- transcript/event/tool-call diagnostics sufficient for debugging;
- graceful network/API failure and recovery;
- no violation of the existing Core/Launcher lifecycle invariants.

## Rationale

This order isolates risk. If voice transport or cloud function calling fails, the project can debug Qwen/network/audio/provider integration without simultaneously debugging a large new ATC/AWACS/JTAC tool surface. Once the vertical slice is proven, ORION Core becomes a stable DCS AI gateway to which product modules can be added incrementally.

## Cost / Russia constraints

The desired production solution should be inexpensive and preferably free for personal use, but free access is a preference rather than a reason to compromise the Core architecture. Qwen's current free quota can be used for validation; long-term pricing, Russian access and practical payment options must be verified before declaring Qwen the permanent default provider.

## Supersession / compatibility

This decision does not invalidate the existing ORION Core, DCS telemetry architecture, Launcher/Core separation, Virtual ATC designs or other module requirements. It changes the **voice/AI integration direction and implementation order**. Existing local Whisper work is retained as fallback/test evidence rather than being removed prematurely.
