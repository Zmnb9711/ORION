# ADR-005 — SRS as a separate Radio Voice Transport

**Date:** 2026-08-24
**Status:** Accepted

## Context

ADR-004 selected a provider-separated cloud realtime voice direction and a Qwen-first vertical slice. That decision intentionally separates AI inference from ORION Core, but its initial microphone-to-provider-to-audio-output flow describes only direct local voice interaction.

ORION also needs to participate in DCS radio networks as Virtual ATC, AWACS/GCI, JTAC/FAC, Tanker and other multiplayer radio actors. Those roles require radio-specific identity, channel and transmission semantics that a direct Windows microphone/output path does not provide. They must be able to receive and transmit through SRS without turning SRS into the audio backend for every ORION conversation.

SRS and cloud AI providers solve different problems:

- SRS transports radio audio and radio metadata;
- Qwen, Yandex or another realtime provider performs speech understanding, reasoning/tool selection and speech generation;
- ORION Core remains responsible for DCS context, validated actions, role behavior, routing and safety.

## Decision

Adopt SRS as an **optional second Voice Transport**, alongside the existing Direct Voice path. SRS does not replace Direct Voice.

Voice Transport and AI Provider are independent architectural axes:

### Voice Transports

- **Direct Voice Transport** uses the selected Windows microphone and audio output through the local WASAPI/audio path. It is intended for private/personal ORION interaction, Aircraft Knowledge, troubleshooting and casual conversation.
- **SRS Radio Voice Transport** receives and transmits through the SRS radio network. It is intended for Virtual ATC, AWACS/GCI, JTAC/FAC, Tanker/AAR coordination and multiplayer radio interaction.

### AI Providers

- `QwenRealtimeProvider` is the first provider used by the ADR-004 vertical slice.
- `YandexRealtimeProvider` or another future provider may be selected without changing either Voice Transport.
- Providers must consume and produce provider-neutral audio/events. They must not contain SRS, WASAPI, DCS-radio or product-role business logic.

Conceptual flows:

`Direct/WASAPI <-> selected AI Provider <-> ORION Core/tools <-> DCS`

`SRS Radio <-> OrionSrsTransport <-> selected AI Provider <-> ORION Core/tools <-> DCS`

ORION Core owns transport selection and routing. Radio metadata needed for role behavior and response routing must remain available to Core without leaking transport-specific protocol handling into AI providers.

## OrionSrsTransport requirements

`OrionSrsTransport` must model and preserve at least:

- tuned frequency;
- AM/FM modulation;
- sender identity, including SRS client GUID and DCS `UnitID` where available;
- coalition and encryption context;
- transmission start/end boundaries and PTT state;
- channel-busy state and scheduling so ORION does not transmit over an occupied channel without an explicit role policy;
- an explicit simultaneous RX/TX policy;
- self-transmission filtering so ORION never feeds its own SRS transmission back into the AI conversation as a new remote utterance.

Self-transmission filtering must use authoritative transport identity and outbound transmission tracking, not only acoustic echo cancellation or transcript comparison. Filtering must remain correct across reconnects and identity/session changes.

Codec, sample rate, Opus framing, packet sequencing, reconnect behavior and exact SRS protocol/API bindings require a lower-level transport specification and validation against the supported SRS implementation before runtime work is declared complete. This ADR fixes the architectural boundary; it does not guess unverified wire details.

## Optional dependency and failure boundary

SRS must not become a mandatory dependency of the whole ORION runtime.

- Direct Voice must continue to start and operate when SRS is not installed, configured, connected or healthy.
- SRS availability and failures must be reported as the state of an optional capability, not as a reason for ORION Core or Direct Voice to fail startup.
- SRS-specific packaging, configuration, lifecycle and reconnect handling must remain isolated behind `OrionSrsTransport`.
- Product roles that require radio transport must report that the SRS capability is unavailable rather than silently falling back to speakers or impersonating radio operation through Direct Voice.

## Implementation order

1. Preserve the current Qwen vertical slice scope and complete `QwenRealtimeProvider <-> ORION Core` tool/session validation first, as required by ADR-004.
2. Keep the Direct/WASAPI path working and introduce only the provider-neutral Voice Transport boundary needed to avoid coupling it to Qwen.
3. Add `OrionSrsTransport` as the second, optional transport after the Qwen-to-Core vertical slice is green.
4. Validate the SRS protocol details, radio metadata, RX/TX behavior, busy-channel scheduling and self-transmission filtering with focused integration/smoke tests.
5. Expand Virtual ATC, AWACS/GCI, JTAC/FAC, Tanker and multiplayer radio behavior on top of the proven transport/provider boundaries.

Do not mix speculative SRS runtime changes into the current Qwen vertical slice merely to anticipate this later step.

## Consequences

- ORION can act as a real participant in the DCS/SRS radio network while retaining a private direct-assistant channel.
- Radio roles gain explicit frequency, modulation, identity, coalition/encryption and transmission semantics.
- Self-generated radio audio can be rejected at the transport boundary instead of relying on physical echo behavior.
- Voice transports and AI providers can evolve, be tested and be replaced independently.
- The architecture adds routing, lifecycle and radio-scheduling complexity, which must be covered by focused transport tests.

## Supersession / compatibility

This ADR **refines and extends ADR-004; it does not supersede it**. The Qwen-first vertical slice and existing local Whisper fallback remain in place. SRS is introduced only after the Qwen-to-Core vertical slice as a separate optional transport, with no required runtime-code change made by this documentation decision itself.
