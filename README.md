# ORION

ORION is an AI flight-assistant runtime for DCS World. The current repository contains the core service, DCS export/mission bridge components, aircraft knowledge, voice infrastructure, Mission Control building blocks, and an increasingly complete aerial-refueling runtime.

## Current runtime path

The current Build 001 architecture now supports an end-to-end path from pilot input and live DCS state into grounded actions and voice output preparation:

`DCS telemetry / Mission Pack -> live mission context -> dialogue intent -> guarded action orchestration -> subsystem state machine -> proactive monitor -> Voice Core priority queue -> speech scheduler -> TTS/audio adapter`

The actual TTS/audio backend remains adapter-facing. ORION now decides *what* should be spoken, *when* it is eligible to be spoken, and whether a higher-priority callout should interrupt lower-priority speech.

## Grounded dialogue runtime

`POST /v1/dialogue-runtime`

The dialogue runtime combines free-form RU/EN intent classification with current DCS and mission context. STATUS, THREATS, AWACS and tanker queries return factual data from live state rather than generic acknowledgements.

Explicit aerial-refueling phrases such as `Start AAR`, `Request refueling`, or `Запросить дозаправку` enter the existing AAR rendezvous state machine. Informational tanker queries remain read-only. Active AAR sessions support status/update, guarded pre-contact requests and explicit abort commands.

Laser and smoke target-designation intents remain confirmation-required and are not executed directly by the dialogue runtime.

## Proactive AAR runtime

`GET /v1/aar/proactive?language=en|ru`

The proactive AAR monitor produces sparse callouts for meaningful changes only. It can report rendezvous/join-up guidance changes, closure and vertical deviations, pre-contact readiness, contact-envelope loss/restoration, and active tanker loss/restoration.

`POST /v1/aar/proactive/voice?language=en|ru`

This bridge publishes significant proactive AAR callouts into the shared Voice Core queue. Routine guidance uses NORMAL priority. More urgent AAR conditions such as tanker loss, excessive closure, or contact-envelope loss use HIGH priority. CRITICAL remains reserved for higher-severity warnings such as threat/terrain events.

## Voice Core and speech scheduling

Voice Core stores commands with agent identity, intent, context and priority. Higher-priority queued items are selected before routine speech.

`POST /v1/speech/next`

The speech scheduler selects the next eligible Voice Core command for an external TTS/audio adapter. It prevents two simultaneous RUNNING speech items, allows a higher-priority item to preempt lower-priority speech, and suppresses repeated identical non-critical callouts for a short cooldown window.

CRITICAL messages bypass duplicate cooldown so genuinely urgent warnings are never muted by anti-chatter logic.

`POST /v1/speech/{command_id}/spoken`

The audio/TTS adapter acknowledges completed playback through this endpoint. ORION then records the callout for duplicate suppression and marks the Voice Core command completed.

## Safety and state authority

Voice and proactive guidance do not invent physical DCS state. Confirmed AAR transitions such as pre-contact clearance, physical contact, active fuel transfer, disconnect, and completion continue to come from trusted DCS/Mission Pack observations through the normalized AAR event layer.

## Validation

Repository CI compiles all ORION Python modules and runs the complete pytest suite for each pull request revision.
