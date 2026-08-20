# Qwen Live hardware control and Core ATC integration

Status: implementation candidate for Windows/HOTAS/DCS field validation.

Baseline: Build #402 / commit
`4e8b49afff0b8f5d1ec1a008f09f79ae08e1a546` remains the protected Qwen
transport/playback control point.

## One Qwen lifecycle

Launcher buttons and the assigned controller button both use the existing Core
endpoints:

`/v1/realtime/qwen/live/start`

`/v1/realtime/qwen/live/stop`

The controller path does not own a Qwen service or a second state machine. It
reads the current Core status before each toggle and serializes commands while
START or STOP is in progress. A controller press can therefore start Qwen from
STOPPED without a prior Launcher Start action, and either control surface can
stop the same Core-owned session.

## Controller boundary

The first tranche uses SDL joystick support through pygame. It supports button
input from devices exposed by SDL as joysticks, including compatible HOTAS
sticks, throttles and button boxes. It does not claim keyboard or mouse binding
support.

The monitor polls button state at 20 Hz in the Launcher process with background
controller input enabled. It is nonexclusive and does not consume the event
before DCS sees it. Only a button-down edge toggles Qwen. A held button and its
release do nothing; rapid duplicate edges are debounced.

The persisted binding contains SDL backend/type, GUID, device name, axis/button/
hat shape, zero-based button index and a human-readable control name. Device
ordering is not part of the identity. SDL cannot uniquely distinguish two
fully identical devices with the same fingerprint; that case is marked
ambiguous/unavailable instead of silently resolving to either controller.

## Active mission authority

Qwen mission tools are available only when both Core authorities are current:

1. `telemetry_handshake.snapshot()` is connected and contains a current
   `aircraft_type`; and
2. `mission_bridge_telemetry.state()` is connected, not stale and contains a
   `session_id`.

`DCS.exe` process presence alone is never treated as an active mission. When
either authority becomes stale or disconnects, Virtual ATC becomes unavailable
immediately while the user-controlled Qwen session and free conversation remain
active.

## Core-owned Virtual ATC tool

The realtime provider sees one mission tool,
`orion_virtual_atc_request`, mapped inside Core to
`orion.virtual_atc.request`. Core validates arguments, live mission authority
and runtime module availability before it calls the canonical `virtual_atc`
facade and shared `airport_atc_dialogue` gateway.

The common dialogue gateway currently wires Arrival. Ground, Tower, Departure
and Carrier return `domain_not_yet_wired`; the Qwen integration preserves that
truth and does not fabricate a clearance. Missing context, disabled/unavailable
ATC, malformed arguments and isolated ATC failures all return structured tool
results for a natural spoken explanation.

The minimal runtime module gate represents modules present and enabled in the
current runtime. It is not installer state. A future installer/Launcher module
registry can drive the same gate without changing the Qwen tool boundary.
