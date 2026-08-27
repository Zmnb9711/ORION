# Stage 6B.1 radio context and transport-neutral router

Status: **IMPLEMENTED AS AN UNWIRED ARCHITECTURE SLICE — 2026-08-28**.

## Purpose and boundary

Stage 6B.1 establishes the Core-owned semantic boundary between finalized PCM
and a future radio transport adapter. It proves that this boundary can express
ORION's current 251.000 MHz AM use case while remaining independent of SRS and
any possible future DCS Native Voice Chat adapter.

This stage does not migrate production traffic. Existing SRS/Yandex/Hybrid
Probe code, registration, RadioInfo, Opus, resampling, pacing, PTT, UDP/TCP and
readiness behavior remain unchanged. There is no production adapter and no new
Core/Launcher endpoint. SRS migration is deferred to Stage 6B.2.

## Ownership

Core owns:

- the immutable resolved transmission request;
- explicit/default transport selection, with no heuristic fallback;
- one bounded semantic TX queue;
- priority/FIFO ordering, correlation, replay and queued cancellation;
- generic readiness/capability interpretation and normalized failures;
- bounded safe diagnostics and deterministic Router shutdown.

A transport adapter owns transport mechanics. A future SRS adapter will retain
SRS registration, GUID, RadioInfo, radio index, EAM, TCP/UDP, Opus, resampling,
packet construction, frame pacing and protocol diagnostics.

The World Model remains the owner of cockpit/telemetry facts such as COMM1,
COMM2 and selected radio. A future upstream resolver may use those facts to
construct a `RadioContext`; the Router neither queries nor stores them.
Phraseology and provider reasoning remain upstream. The Router accepts finalized
PCM, not text, semantic units, prompts or TTS configuration.

## Immutable contracts

`RadioEntityRef` contains only:

- stable logical `entity_id`;
- `operational_callsign`;
- optional provider-neutral coalition identity.

`RadioContext` contains only one resolved transmission's:

- `tx_correlation_id`;
- `source_domain` using the existing `CommunicationDomain`;
- immutable `radio_entity`;
- positive finite `target_frequency_hz`;
- `AM` or `FM` modulation;
- the existing IA-6 `CommunicationPriority`;
- optional interaction/session/turn correlation;
- at most 16 unique opaque provenance references.

It deliberately contains no SRS GUID/index/RadioInfo, mutable readiness, raw
cockpit payload, World Model snapshot, communication profile, phraseology,
provider configuration, credential or password. Communication profile cannot
alter radio authority because it is not an input to this boundary.

`FinalizedPcmAudio` is immutable, mono signed 16-bit little-endian PCM with a
validated 8–192 kHz sample rate, complete sample frames and a hard 2,646,000-byte
bound (30 seconds at 44.1 kHz). The generic boundary does not require SRS Opus
or a transport-specific sample rate; conversion belongs to an adapter.

The current proven SRS case is represented without SRS types as 251,000,000 Hz,
AM, mono PCM16 at 44.1 kHz and one correlated transmission.

## Adapter contract

`RadioTransportAdapter` is a small synchronous protocol:

- stable `transport_id`;
- typed immutable `capabilities()`;
- typed `status()` and `start()` readiness;
- `transmit(request)` returning one correlated terminal result;
- capability-dependent `cancel(tx_correlation_id)`;
- bounded `shutdown(timeout_s)`.

The real Stage 6B.2 adapter established that synchronous transmission also
needs a bounded caller deadline. `RadioTransmissionRequest.timeout_s` defaults
to 35 seconds, is limited to 120 seconds and is included in replay identity.

Required TX capabilities are `TX_AUDIO`, `TX_COMPLETION`, `FREQUENCY` and
`MODULATION`. Optional values describe RX, active cancellation, radio selection,
coalition, positional radio and encryption. There is no generic PTT capability:
the request itself represents one adapter-managed TX window.

Readiness is intentionally generic: `UNAVAILABLE`, `STARTING`, `READY`,
`DEGRADED`, `STOPPING`, `STOPPED`, `ERROR`. Stage 6B.2 will map SRS-specific
handshake states behind the adapter.

Failures are typed as transport unavailable, not ready, radio unavailable,
invalid context, unsupported capability, rejected, cancelled, timeout or
transport error. Raw adapter exceptions and transport-specific messages are
normalized before crossing the Router boundary.

## Router policy

The default queue holds eight queued transmissions and is configurable for
tests. Active work is separate from this bound. A single worker is the only
component allowed to reorder semantic transmissions. Adapters may perform only
the frame-level buffering needed for the currently selected request.

The heap key is descending communication priority followed by ascending enqueue
sequence. Therefore `IMMEDIATE` precedes queued lower priorities and equal
priority is FIFO. An already active transmission is never preempted in 6B.1;
the design does not claim missile-warning preemption.

A request names an explicit transport or uses one Core-configured default.
Unknown, unavailable or not-ready transports fail with a typed result. The
Router never tries another registered adapter.

The replay ledger is Core-owned and bounded (256 entries by default). An
identical request with the same correlation ID returns the current/terminal
snapshot and never calls the adapter again. Reusing the ID with different
context, transport, audio metadata or PCM hash fails closed. A single terminal
adapter result creates a single logical completion. Once work becomes terminal,
the replay ledger retains only its signature and safe snapshot; the PCM request
is released rather than being retained across the 256-entry replay window.

Queued cancellation is immediate: the snapshot becomes `CANCELLED` and the
adapter never sees it. Active cancellation is delegated only when the adapter
advertises `TRANSMISSION_CANCEL`; otherwise the result explicitly reports an
unsupported capability. Stage 6B.1 does not fake active cancellation.

Shutdown stops admission, marks every queued request cancelled, requests
supported active cancellation, closes every adapter within the caller's shared
deadline and joins the worker within the same bound. Its immutable result
reports worker and adapter closure; repeated shutdown is idempotent.

## Observability and privacy

The Router retains at most 500 typed diagnostics by default. Events contain
only stage/timestamp, transport and correlation IDs, source domain, radio
entity ID, priority, frequency, modulation and normalized failure code.
Snapshots may also contain adapter-provided frame count and duration. PCM,
Opus, transcripts, raw provider/transport bodies, credentials, passwords and
full protocol identities are absent.

## Verification and future seams

The tests-only `FakeRadioTransportAdapter` is configurable for readiness,
capabilities, deterministic completion/failure/exception, controlled blocking,
active cancellation and shutdown. It counts exact calls and uses no network,
SRS process, audio device or provider.

Focused tests cover contract validation/immutability, the 251 MHz AM case,
adapter registration and bounds, no fallback, readiness/capability rejection,
success/correlation, queue capacity, priority/FIFO, queued and active
cancellation, identical/conflicting replay, single completion, failure
normalization, bounded diagnostics and shutdown/idempotency. Static tests prove
the generic modules contain no SRS, provider, World Model, phraseology or
`OperationalSemanticUnit` dependency and no duplicate mutable radio state.

A future DCS-native adapter can implement only capabilities an official API
actually provides. The generic contract does not assume such an API and does
not require any SRS identity or registration concept.

## Acceptance and next boundary

Stage 6B.1 is accepted when its focused and full isolated regression suites,
coverage threshold and static/privacy gates pass. No DCS, external SRS, live
Yandex/Qwen or physical audio device is required. Packaging is not required
because neither new module is imported by the packaged Core runtime.

The next separately authorized stage is 6B.2: adapt the existing proven SRS
transport to this boundary without changing its wire behavior. Do not begin
that migration as part of 6B.1.
