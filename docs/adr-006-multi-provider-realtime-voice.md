# ADR-006: Multi-provider realtime voice

Status: Accepted

## Context

ADR-005 selected Qwen for the first production conversational-voice vertical
slice. ORION now also needs a production Yandex Realtime voice path without
changing the field-validated Qwen transport or forcing unlike provider
protocols through a universal audio engine.

## Decision

ORION supports selectable realtime voice providers. A small Core-owned
coordinator serializes Start and Stop, exposes normalized status, and guarantees
that at most one provider owns the selected microphone and output endpoint.
Qwen and Yandex retain independent transport, audio rates, VAD semantics, event
loops, and playback implementations.

Qwen remains at its existing provider-specific rates and behavior. Yandex uses
its direct mono PCM16LE 44.1 kHz protocol path and response-scoped playback.
Provider-specific protocol rates are explicitly allowed.

The Launcher keeps API keys only in process memory. Non-secret provider fields,
including Yandex Folder ID, may be persisted. Explicit Start remains the
lifecycle policy; DCS readiness does not require a mandatory Voice READY gate in
this tranche.

ATC and business logic remain provider-neutral. Yandex function/tool calling is
deferred. Dream Air echo suppression, correlation-driven behavior, AEC,
microphone gating, and semantic echo filtering are also deferred.

## Consequences

- Provider switching is explicit: the active provider must be stopped first.
- The common layer owns lifecycle and exclusivity only, not PCM or WebSocket
  event abstraction.
- Existing Qwen routes remain backward compatible.
- Future Yandex tools can be added behind the provider boundary without making
  Core ATC logic provider-specific.

This ADR supersedes only ADR-005's Qwen-only provider assumption. It does not
rewrite or invalidate the Qwen baseline decisions recorded there.
