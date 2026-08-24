# ADR-007: SRS radio voice transport and provider/transport separation

Status: Accepted

Field-proven reference baseline: commit
`1a06a093eb8e9b9efbf2f33793ed84f7e7b40040` (`Fix SRS radio registration
handshake`)

## Context

ADR-006 made Qwen Realtime and Yandex Realtime independently selectable AI
providers while preserving their unlike protocol and audio implementations.
The no-DCS `reference_tests/yandex_realtime_gui/` experiment has now proved a
second independent dimension: SRS is a voice/radio transport, not an AI
provider and not a replacement for Qwen or Yandex.

The field topology was an SRS 2.4.0.0 server, an official SRS Client acting as
the human participant, and YandexRealtimeTester acting as the headless AI radio
participant. DCS was not running. Both clients authenticated through External
AWACS Mode as BLUE (`coalition = 2`) and used 251.000 MHz AM with encryption
off.

## Field-proven baseline

The successful test reported:

- SRS `READY`, `radio_registered = True`, server `2.4.0.0`, frequency
  `251000000.0`, AM, coalition 2;
- 125 received UDP packets, 78,720 decoded samples and 216,970 resampled
  samples;
- two transmissions started and two completed;
- zero malformed packets, Opus decode errors, duplicates, out-of-order
  packets and sequence gaps;
- 286 Yandex input blocks and two successful completed voice responses;
- first useful response audio at approximately 1,187 ms and 985 ms;
- two SRS output transmissions comprising 382 frames;
- maximum TX scheduling jitter of 15 ms and 14 ms, with cumulative pacing
  drift of 3 ms and 0 ms;
- the human heard both Yandex answers through the official SRS Client.

This proves the complete path:

`human microphone -> official SRS Client -> SRS Server -> headless SRS RX ->
Opus decode -> stateful 16 kHz to 44.1 kHz resample -> Yandex Realtime ->
Yandex response -> stateful 44.1 kHz to 16 kHz resample -> Opus encode -> paced
SRS TX -> SRS Server -> official SRS Client -> human headset`.

The report also recorded two collisions and later RX packets intentionally
dropped as `bot_tx_collision`. This is evidence that the v0.1 half-duplex
collision protection operates; it is not a baseline defect. Barge-in and radio
interruption policy remain later decisions.

## Root-cause checkpoint and protected handshake

Before the successful field test, initial SRS `SYNC` omitted
`Client.RadioInfo`. SRS 2.4.0 stored `RadioInfo = null`; the subsequent
`RADIO_UPDATE` then caused a server-side `NullReferenceException` inside
`HandleClientRadioUpdate`. A UDP GUID echo could still produce a false
`READY`, although the Tester was not a valid receiver on 251 MHz. The observed
symptom was `udp_packets_received = 0`.

The fixed protocol invariant is:

1. Initial `SYNC` contains non-null compatible `RadioInfo`.
2. Initial `SYNC` and subsequent `RADIO_UPDATE` use the same canonical radio
   state.
3. Readiness proceeds as `RADIO_UPDATE sent -> matching own server
   RADIO_UPDATE received -> UDP GUID echo -> READY`.

The canonical SRS 2.4.0 radio state contains 11 `PlayerRadioInfoBase.radios`
slots. `radios[1]` is active at `251000000.0`, modulation `0`/AM, `enc = false`,
`encKey = 0`, `retransmit = false`, `secFreq = 1.0`; the other slots are
disabled, and `unitId = 100000`.

## Decision

ORION Voice separates two independently selected dimensions:

- **AI Provider:** Qwen Realtime or Yandex Realtime;
- **Voice Transport:** Direct Audio or SRS Radio.

A Core-owned `VoiceSession`/coordinator remains the exclusivity and lifecycle
authority. The selected provider owns provider protocol/session semantics. The
selected transport owns audio ingress/egress and, for SRS, radio/network
semantics. Provider and transport meet at a narrow PCM/session boundary; Core
tools and domain state remain behind a provider-neutral boundary.

Required existing combinations remain Qwen + Direct Audio and Yandex + Direct
Audio. The first SRS production acceptance target is Yandex + SRS. Qwen + SRS
is architecturally desirable but is not required in the first tranche.

Direct Audio remains the personal ORION assistant path for casual
conversation, Aircraft Knowledge, troubleshooting and fallback when SRS is
unavailable. SRS Radio is the future transport for Virtual ATC, AWACS/GCI,
JTAC, tanker, wingman and multiplayer radio services. SRS transport itself
contains no ATC, runway, AWACS, JTAC, tanker or DCS mission logic.

## Protected SRS invariants

- Initial `SYNC` contains non-null SRS-compatible `RadioInfo`.
- `SYNC` and `RADIO_UPDATE` radio state remains semantically identical.
- `READY` requires server-confirmed radio state and UDP readiness.
- Compatibility targets SRS 2.4.x and is field-proven on 2.4.0.0.
- The v0.1 baseline is one 251.000 MHz AM radio with EAM BLUE authentication.
- The UDP codec retains the official 57-byte fixed tail and correct
  `OriginalClientGuid`/current-sender semantics.
- Own-origin rejection and half-duplex busy-channel protection remain.
- Opus remains mono PCM16, 16 kHz, 40 ms and 640 samples per frame.
- Streaming resamplers remain stateful.
- SRS mode does not open Windows microphone/output devices through PortAudio.
- Credentials and raw PCM, Opus or Base64 audio are never persisted.
- Direct Audio remains independent and behaviorally unchanged.
- DCS is not required for basic SRS transport.
- The reference Tester GUI, diagnostics and packaging are proof apparatus, not
  production architecture; production must not import `reference_tests`.

## Consequences

- The existing provider coordinator may be extended only at the smallest seam
  supported by the production code; this decision does not approve a generic
  realtime framework or a Qwen rewrite.
- One Core-owned realtime voice session remains the default safety model until
  concurrent session ownership is separately designed and proven.
- SRS native dependencies belong to the Core production bundle when SRS is
  implemented; Launcher should configure and supervise but not load the radio
  codec/runtime.
- EAM password is a secret and remains memory-only unless an explicitly
  approved secure secret store is introduced.
- Production SRS diagnostics persist scalar, sanitized metadata only.

## Approved staged roadmap

1. Freeze the SRS baseline in project history.
2. Complete a read-only production integration audit.
3. Implement only SRS transport in production ORION.
4. Add independent Direct Audio / SRS Radio transport selection.
5. Pass the production ORION + SRS no-DCS field gate.
6. Add DCS radio context only: aircraft, cockpit radios, frequencies, callsign
   and position.
7. Add a `RadioRouter` using frequency and sender identity as routing context.
8. Add Core-owned durable `FlightContext`; provider conversation memory is not
   authoritative flight state.
9. Prove a provider-neutral tool-call gate, first with `orion.test.ping`, then
   one safe ATC tool.
10. Add full Virtual ATC only after the preceding layers are independently
    proven.

## Non-goals of this decision

This ADR does not implement production SRS, DCS radio context, RadioRouter,
FlightContext, provider-neutral tool calling or ATC behavior. It records the
field-proven transport baseline and the approved boundary for later work.
