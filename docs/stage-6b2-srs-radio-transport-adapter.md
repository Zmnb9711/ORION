# Stage 6B.2 production SRS radio transport adapter

Status: **IMPLEMENTED AND DETERMINISTICALLY VALIDATED; LIVE SRS FIELD GATE
REQUIRED**.

## Purpose and preserved implementation

Stage 6B.2 adds the first production implementation of the Stage 6B.1
`RadioTransportAdapter`: `SrsRadioTransportAdapter`. SRS remains ORION's primary
and field-proven radio transport. The adapter is deliberately thin and does not
replace or fork the SRS implementation.

The existing implementation remains responsible for:

- SRS 2.4.x TCP synchronization, EAM authentication and canonical initial
  `RadioInfo`;
- server-echoed radio registration and UDP GUID registration;
- client GUID, coalition and registered frequency/modulation state;
- RX packet filtering, collision/sequence tracking and the 400 ms boundary;
- 250 ms channel-clear guard;
- 44.1 kHz to 16 kHz conversion through the existing pinned samplerate path;
- the existing libopus 1.6.1 encoder, 40 ms frames and final-frame padding;
- SRS voice packet construction, packet IDs, retransmit=0 and 40 ms pacing;
- UDP send and the existing `srs_tx_started` / `tx_completed` diagnostics.

No protocol, resampler, codec, packetizer or pacer was reimplemented in the
adapter.

## Production path and compatibility boundary

The controlled migrated production path is the IA-1.1 Hybrid Presentation
Probe:

```text
finalized Hybrid Probe PCM
  -> SrsYandexPcmEndpoint.transmit_probe_audio
  -> RadioRouter
  -> SrsRadioTransportAdapter
  -> existing single-slot SRS TX worker
  -> existing resampler / Opus / packetizer / pacer / UDP send
  -> existing matching tx_completed
  -> generic terminal completion
```

This path was selected because it already supplies finalized mono PCM and has a
strict synchronous requirement for the matching SRS `tx_completed`. It proves
the real adapter without migrating every domain or changing normal IA-1
presentation.

Ordinary Yandex Realtime response audio remains the temporary legacy
compatibility path into the same single-slot SRS TX worker. It does not use a
second SRS implementation. Stage 6B.2 does not migrate ATC, AWACS/GCI, JTAC,
AAR or Mission Control. Future removal of the legacy admission path belongs to
a separately authorized migration stage.

## Adapter boundary

The adapter sees only a generic immutable `RadioTransmissionRequest` and a
narrow SRS port implemented by `SrsYandexPcmEndpoint`. The port exposes:

- a safe scalar runtime projection;
- one correlated finalized-PCM transmit call;
- the existing correlated completion timing/frame result;
- bounded shutdown of the owned endpoint resources.

The generic contracts still import no SRS types. SRS-specific lifecycle and
completion projections exist only in `srs_radio_adapter.py`, below that
boundary.

The real adapter advertises exactly:

- `TX_AUDIO`;
- `TX_COMPLETION`;
- `FREQUENCY`;
- `MODULATION`.

It does not advertise `TRANSMISSION_CANCEL`. The current SRS path can stop the
whole session, but it cannot safely cancel only the active semantic TX. Queued
cancellation therefore remains owned by `RadioRouter`; active cancellation is
explicitly unsupported and never faked.

AM maps to SRS modulation `0` and FM maps to `1`. The adapter mapping and fake
port tests cover both. The currently wired Yandex/SRS product request remains
AM-only, exactly as before, so this stage makes no field-validation claim for
FM.

## Readiness mapping

| Existing SRS state | Generic readiness |
|---|---|
| `DISCONNECTED` | `UNAVAILABLE` |
| TCP connect, SYNC, EAM, radio/UDP registration | `STARTING` |
| `READY` plus endpoint started, radio registered and UDP registered | `READY` |
| `READY` missing any prerequisite | `DEGRADED` |
| `ERROR` or endpoint failure | `ERROR` |
| `STOPPING` | `STOPPING` |
| `STOPPED` | `STOPPED` |

`RADIO_REGISTERED` and `REGISTERING_UDP` remain SRS diagnostics. Neither
`RadioRouter` nor generic callers depend on them.

## Context and audio mapping

For each transmission the adapter checks the resolved context against the
already registered SRS endpoint:

- frequency must exactly match the endpoint's registered frequency;
- modulation must match;
- operational callsign must match the registered bot name;
- optional coalition must match EAM coalition (`red=1`, `blue=2`).

It does not mutate registration per transmission or copy COMM1/COMM2/cockpit
state. Domain, priority and provenance remain generic correlation metadata.

The existing SRS TX converter accepts finalized mono PCM16LE at 44.1 kHz.
Although the generic descriptor permits other sample rates for future adapters,
this real adapter rejects other rates with a typed unsupported-capability
failure rather than introducing a second conversion chain.

Real-adapter work exposed one minimal 6B.1 contract omission: a synchronous TX
needs a bounded per-request deadline. `RadioTransmissionRequest.timeout_s` is
therefore now required by behavior, defaults to 35 seconds and is validated in
the range `(0, 120]`. It participates in the replay signature.

## Completion, replay and wire equivalence

One accepted Router request invokes the adapter once. The adapter enqueues one
item into the existing single-slot execution handoff and blocks on its matching
completion marker. Only after the established TX worker has completed pacing
all sent frames and emitted `tx_completed` does the adapter return generic
`COMPLETED` with first-frame time, completion time, frame count and duration.

This proves local ORION completion through the SRS UDP send path. It does not
prove server forwarding, reception by another SRS client or headphone playback.

The bounded Router replay ledger remains authoritative. Identical replay
returns the prior snapshot without another adapter call or SRS enqueue;
conflicting correlation reuse fails closed.

The deterministic equivalence test sends the same synthetic PCM once through
the legacy response admission and once through Router/adapter. Both traverse
the same resampler, encoder, packet constructor, pacer and UDP fake. It verifies
equal frame count, Opus payload, frequency, modulation, unit ID, retransmit
count and GUID fields, plus one matching `tx_completed` per semantic request.
Packet IDs intentionally continue their session sequence and are not expected
to be byte-identical.

## Failure and observability

The adapter maps failures to existing generic codes:

- unavailable or disconnected socket: `TRANSPORT_UNAVAILABLE`;
- incomplete readiness: `NOT_READY`;
- frequency/modulation/entity/coalition mismatch: `RADIO_UNAVAILABLE`;
- unsupported PCM input: `UNSUPPORTED_CAPABILITY`;
- busy/rejected execution handoff: `TX_REJECTED`;
- matching completion deadline: `TX_TIMEOUT`;
- other SRS/codec/protocol failure: `TRANSPORT_ERROR`.

Raw exception text never enters generic results. Existing bounded SRS
diagnostics receive only adapter stage, correlation, entity, frequency,
modulation, frame count, duration and normalized failure code. PCM, Opus,
credentials, EAM password, raw GUID and provider bodies remain excluded.

## Lifecycle and packaging

`SrsYandexPcmEndpoint` creates and starts the adapter and Router only after the
existing radio and Yandex session are ready and its worker boundary has started.
Endpoint stop asks the Router to stop admission and close the adapter. Adapter
shutdown closes the same endpoint-owned radio/workers/codecs under the existing
Core/Yandex session lifecycle. Each new Yandex/SRS session creates a fresh
endpoint, Router and adapter; no external SRS process ownership was added.

The Core package includes the adapter through the production endpoint import.
Launcher packaging explicitly excludes the adapter together with the existing
SRS/native modules, so Opus, samplerate and NumPy remain Core-only. A new release
directory and installer are required; no previous release is overwritten and
installation is not automatic.

## Scope boundary and field validation

No Phraseology, provider, World Model, domain, Launcher UX or DCS Native Voice
work is part of this stage. No active preemption is claimed.

Deterministic completion cannot establish external audibility. After offline
tests and frozen smokes pass, a bounded no-DCS external-SRS test remains the
appropriate final field gate: official SRS Client in the same coalition on
251.000 MHz AM, run the Hybrid Probe, confirm one response per case, no SRS
registration/readiness regression, matching local completion and audible
reception.

## Validation checkpoint

The 2026-08-28 implementation checkpoint passed 73 focused Stage 6B.1/6B.2 and
endpoint tests, 322 extended SRS/Yandex/IA/lifecycle tests and the full isolated
repository suite of 1,478 tests. Isolated branch coverage was 82%. Ruff,
Pyright, compileall, `git diff --check`, secret/privacy scans and deterministic
wire-equivalence checks passed.

Fresh Core and Launcher frozen builds passed their offline native/control
smokes. The assembled Launcher started and gracefully stopped its exact Core on
a disposable loopback port, left no orphan process, opened no audio device,
started no external SRS process and did not expose or persist the smoke
credential. The Core archive contains `orion.srs_radio_adapter`; the Launcher
archive excludes it and contains no SRS executable, Opus, samplerate or NumPy
payload. The fresh installer was compiled but not automatically installed.

Artifacts are under `release-stage6b2-20260828`. The installer is
`installer/ORION-Alpha-0.2-Setup.exe`, 73,189,488 bytes, SHA-256
`CBC83918BE631A48E50D27A3F93D97091BB1DAF44AB546C2A17CA026F06F6F46`.
Local deterministic validation proves preservation of the established SRS send
mechanics, not server forwarding or audibility; therefore the live SRS field
classification remains `REQUIRED`.
