# ADR-004 — Cloud Realtime Voice / Qwen vertical slice

Status: Accepted for experimental implementation

Baseline: ORION current field-confirmed working baseline is Build #312. Build #284 remains the immutable Voice/STT recovery GOLDEN.

## Context

ORION currently has a field-confirmed local Voice/STT path based on whisper.cpp. It works, but local speech processing consumes host CPU/GPU resources that are also valuable to DCS World and VR rendering.

The next architecture experiment is a cloud realtime voice path designed to reduce local compute load while preserving ORION's local product boundaries and DCS integration.

Qwen Realtime is selected as the first experimental cloud voice backend. This selection is not a permanent coupling: Qwen must be implemented behind a replaceable provider boundary so another realtime voice provider can be substituted later without redesigning ORION Core.

## Decision

### 1. Local product boundary remains unchanged

ORION Core stays local on the Windows PC.

DCS integration, telemetry ingestion, mission state, tool execution, safety/authorization logic and all deterministic ORION behavior stay local.

Cloud voice is an adapter around the local system, not a replacement for ORION Core.

Canonical direction:

`Microphone / Launcher voice session -> Cloud Realtime Voice Provider -> local ORION Core -> local tool -> provider response/audio -> user`

### 2. Provider abstraction is mandatory

Qwen must not be hard-coded into ORION Core.

A provider-neutral realtime voice interface is introduced outside the domain/tool logic. Qwen is the first adapter implementing that interface.

Core may know only provider-neutral requests/events such as:

- session ready / unavailable;
- recognized user intent/text or provider event;
- tool-call request;
- tool result;
- assistant response lifecycle;
- health/error/latency state.

Provider-specific WebSocket URLs, authentication headers, event names, codecs and protocol details remain inside the Qwen adapter.

### 3. CPU/GPU minimization is a primary goal

The cloud path is successful only if it materially reduces local speech/AI compute load compared with the whisper.cpp primary path.

The experiment therefore prefers direct realtime audio streaming to the provider and avoids local STT/LLM/TTS work unless needed for fallback or safety.

Local measurements must include at minimum:

- ORION Voice CPU usage;
- ORION Core CPU usage;
- optional GPU usage attributable to ORION;
- session latency / first-response latency;
- reconnect behavior.

### 4. First implementation is a narrow vertical slice

The first slice is intentionally not ATC/AWACS/JTAC/AAR.

Required path:

`Launcher/Qwen -> local ORION Core -> test tool -> result -> Qwen/Launcher`

The test tool must be deterministic, harmless and easy to verify. It exists only to prove the end-to-end provider/tool contract.

Example tool class: `orion.test.echo`, `orion.test.ping`, or equivalent provider-neutral smoke tool.

The slice is complete only when a real cloud session can:

1. connect from the Launcher-side voice runtime;
2. reach Qwen Realtime;
3. receive a tool-call request;
4. route that request into local ORION Core;
5. execute the local test tool;
6. return the tool result to the realtime provider;
7. receive/render the resulting assistant response;
8. shut down cleanly with ORION lifecycle rules.

### 5. Realtime voice comes after the tool bridge smoke

Implementation order is mandatory:

Phase A — provider-neutral interfaces and configuration.

Phase B — Qwen connection from Launcher/Voice runtime to Core using a deterministic test tool.

Phase C — realtime microphone/audio session and full duplex voice behavior.

Phase D — resilience: reconnect, timeout, provider unavailable, authentication failure, rate-limit handling and fallback selection.

Phase E — only after successful field smoke-test: expose real ORION tools such as ATC, AWACS, JTAC, AAR and later mission-control capabilities.

No combat/mission-control tool is enabled in the Qwen path before the vertical-slice smoke gate passes.

### 6. whisper.cpp remains installed and available as fallback

The working Build #312 whisper.cpp path is preserved during the experiment.

Cloud realtime must not delete, rewrite or silently replace the field-confirmed local Voice/STT implementation.

Provider selection must eventually support at least:

- `cloud_realtime` (Qwen initially);
- `local_whisper` fallback;
- explicit disabled/offline state.

Fallback policy may be automatic or user-selected later, but the first implementation must preserve a reliable manual path back to local whisper.cpp.

### 7. Launcher owns user-facing provider selection/status

The Launcher is the user-facing control plane for cloud voice configuration and status.

It should eventually show provider-neutral state such as:

- Voice provider: Qwen / Local Whisper / Disabled;
- Connection: Connecting / Ready / Error / Fallback;
- authentication/configuration state;
- realtime session state;
- measured latency when available.

Secrets must not be committed to the repository or embedded in Core. Provider credentials belong in local protected configuration/environment handling appropriate for Windows.

### 8. ORION lifecycle rules remain authoritative

ADR-004 does not weaken the Build #312 lifecycle baseline.

Close Launcher window to tray:

- Launcher remains running;
- Core remains running;
- active cloud realtime session or local Whisper remains running as configured;
- ORION remains operational.

Explicit Exit from tray:

1. stop active voice/provider session;
2. close provider socket/stream and release microphone/audio resources;
3. stop local Voice/Whisper fallback worker if running;
4. stop Core;
5. exit Launcher;
6. leave no ORION-owned orphan processes or sessions.

## Smoke-test gate

ADR-004 is not considered implemented merely because Qwen connects.

The first acceptance gate is a real-machine vertical-slice smoke test demonstrating:

`Launcher/Qwen -> Core -> deterministic test tool -> Core -> Qwen -> user`

Acceptance must also prove:

- Build #312 local Whisper fallback still works;
- tray behavior remains correct;
- full Exit remains clean;
- provider failure does not crash Core;
- Core contains no Qwen-specific protocol code;
- local CPU/GPU load is measured and compared with the local Whisper path.

Only after this gate passes may ATC/AWACS/JTAC/AAR tools be exposed to the cloud realtime provider.

## Consequences

Positive:

- potential major reduction in local CPU/GPU speech workload;
- low-latency speech-to-speech path becomes possible;
- ORION domain logic and DCS integration remain local and controlled;
- provider lock-in is avoided;
- known-good whisper.cpp remains a recovery/fallback path.

Trade-offs:

- internet connectivity becomes required for the cloud path;
- provider availability, authentication, quotas and regional access must be handled;
- audio leaves the local PC when cloud mode is enabled;
- realtime protocol handling adds connection-state and lifecycle complexity;
- provider abstraction adds a small amount of up-front architecture work.

## Non-goals for the first slice

The first ADR-004 implementation does not attempt to:

- replace ORION Core with a cloud agent;
- remove whisper.cpp;
- implement all ORION tools;
- redesign ATC/AWACS/JTAC/AAR;
- add autonomous mission actions;
- optimize every provider;
- make Qwen a permanent mandatory dependency.

## Architectural rule

**Qwen is an adapter, not ORION.**

The durable architecture is:

`replaceable realtime voice provider <-> local ORION Core/tool contract`

Qwen is simply the first provider used to validate that contract.
