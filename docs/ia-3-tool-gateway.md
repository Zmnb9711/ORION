# IA-3 Tool Gateway

Status: **IMPLEMENTED — CODE-VALIDATED 2026-08-26**.

Next approved stage: **IA-4 PlannerProvider Contract**.

## Decision

IA-3 introduces one Core-owned, provider-neutral security boundary between a
future Planner and ORION capabilities. It is not connected to a provider in this
stage and exposes no new HTTP/provider API.

```text
future provider adapter -> ToolCall
                              |
                       ToolGateway.execute
               registry -> policy -> input validation
                              |
                     typed read-only handler
                              |
                      WorldModelFacade
                              |
                   authoritative owners
                              |
               output validation -> ToolResult
```

The Planner cannot import WorldModelFacade, telemetry/mission stores, aircraft
adapters, DCS/SRS integration or domain state machines. Provider descriptions
and requested tools are informational; the Core capability allowlist and policy
are authoritative.

## AS-IS tool audit

| Path/concept | IA-3 disposition | Finding |
|---|---|---|
| `RealtimeToolService` | KEEP AS-IS / DEPRECATE LATER | Working Qwen-era voice prototype with `dict[str, Any]`, legacy API and direct ATC session effects. It is not renamed or made the final Gateway. |
| Legacy `orion.test.ping` | ADAPT INTO GATEWAY | Stable harmless name and behavior are reused through a new typed IA-3 registration. Legacy runtime remains unchanged. |
| `orion.virtual_atc.request` | KEEP AS-IS | It can create an ATC session and belongs to the legacy voice path. No side-effecting ATC tool is admitted to IA-3. |
| Qwen function definition/name mapping | DEPRECATE LATER | Provider-specific JSON and name translation remain at the provider boundary; IA-3 imports none of it. |
| Yandex Realtime/presentation | NOT RELEVANT | No provider tool-call integration is added. IA-1 presentation remains independent. |
| `RuntimeModuleRegistry` | ADAPT INTO GATEWAY | Existing availability/enabled state is checked before a dependent handler. The Gateway never enables a module. |
| IA-0 `CapabilityId` | KEEP / EXTEND | Reused unchanged for Core-assigned capability allowlists. |
| IA-2 `WorldModelFacade` | KEEP AS-IS | Sole read source for initial world tools; no direct store bypass was required. |
| Existing `ConfirmationStore` | KEEP / EXTEND LATER | One-time resolution exists, but expiry and actor/session/tool/action binding do not. IA-3 confirmation validation therefore fails closed. |
| Mission/ATC/JTAC/AAR action services and APIs | KEEP AS-IS / NOT EXPOSED | Domain ownership and authorization remain untouched. |
| Existing Test Evidence recorder | KEEP AS-IS | Tool Gateway diagnostics are a separate bounded lifecycle ring, not a duplicate payload recorder. |
| Bound confirmation adapter, write idempotency store, provider cancellation binding | GAP | Explicit future seams; no fake authority is invented. |

## Contracts

`tool_gateway_contracts.py` defines immutable typed contracts:

- `ToolDefinition`: stable ORION name/version, `CapabilityId`, input/output
  schema identities, read/write mode, latency, side-effect class and policy.
- `ToolCall`: call identity, exact name/version, bounded JSON-safe arguments,
  Core-owned `ExecutionContext`, and optional future idempotency key.
- `ExecutionContext`: actor and correlation IDs, provider identity as metadata
  only, Core-assigned capabilities/permissions, confirmation identity, deadline
  and cancellation state.
- `ToolResult` / `ToolError`: stable result/error codes, validated bounded data,
  IA-2 provenance/freshness summary, warnings and receipt.
- `ToolReceipt`: actor/session binding, start/completion timestamps, bounded
  latency, idempotency identity and whether a handler started.

Arguments are JSON-safe and bounded at the envelope, then converted to the exact
registered Pydantic input model before execution. Outputs are validated against
the registered output model and bounded again before release. Schema identity
mismatch or duplicate name/version registration is rejected.

## Initial read-only catalog

All tools are version `1.0`; all are local and side-effect-free.

| Tool | Capability | Source/policy |
|---|---|---|
| `orion.test.ping` | `test.ping` | Deterministic Core smoke. |
| `orion.world.ownship.get` | `world.ownship.read` | IA-2 ownship; stale/unavailable status is preserved. |
| `orion.world.navigation.get` | `world.navigation.read` | IA-2 navigation; explicit terrain/airfield/route gaps remain. |
| `orion.world.mission.get` | `world.mission.read` | IA-2 MissionStore and Mission Bridge identities. |
| `orion.world.units.query` | `world.units.read` | Mission required; bounded mission-truth query, not observed contacts. |
| `orion.world.geometry.relative` | `world.geometry.read` | Mission required; IA-2 derived range/bearing/vertical separation. |
| `orion.world.contacts.observed` | `world.contacts.read` | Returns IA-2 `restricted`; never substitutes MissionStore units. |

No aircraft-system, ATC, AWACS action, JTAC, tanker, radio or general state-dump
tool is exposed.

## Policy and execution order

For an exact registered name/version, the Gateway evaluates before handler
execution:

1. cancellation and deadline;
2. Core capability allowlist;
3. required actor permissions;
4. module availability/enabled state;
5. mission availability and required freshness;
6. confirmation binding;
7. idempotency requirement;
8. exact input schema.

It then invokes one statically registered handler, validates the output schema,
applies post-query freshness policy, creates a typed result/receipt and records
bounded lifecycle diagnostics. Raw exceptions become `handler_failure`; raw
exception text, arguments and results do not enter ToolResult or diagnostics.

The stable error vocabulary covers lookup/version, arguments, capability,
module, mission/data availability, stale/restricted state, permissions,
confirmation, idempotency, deadline, cancellation and handler failure.
Deterministic policy/validation errors are non-retryable. Only current-state
availability/freshness failures are conservatively retryable.

## Authority and freshness preservation

IA-2 facts are serialized without flattening their status, source, authority,
age, generation, unit or reason. ToolResult additionally summarizes provenance.
Informational tools may return stale/unavailable facts with explicit warnings.
A definition can instead require fresh data, in which case stale output is
rejected by Core policy. Observed-contact restriction returns a completed typed
result with `restricted` status so it cannot be confused with an empty contact
set.

## Future write/action seam

The contracts can declare a write tool, side-effect class, confirmation and
idempotency requirements, actor/session binding and an execution receipt. No
real write tool is registered. The default confirmation adapter rejects every
confirmation ID because the existing ConfirmationStore cannot yet prove expiry,
actor/session/tool/action binding. A future action adapter must validate those
properties and maintain idempotency before invoking its existing domain owner.

Receipt status vocabulary includes queued, accepted, completed and failed for
that future work; IA-3 local reads complete synchronously.

## Diagnostics, privacy and performance

The in-memory diagnostic ring stores at most 500 typed scalar events: stage,
time, tool/version/capability, safe correlation IDs, policy decision and
latency. It stores no arguments, output, user/provider payload, credentials,
headers, prompts, audio or hidden reasoning.

Gateway and World Model perform no network calls. Deterministic tests inject
clock/monotonic sources instead of asserting flaky wall time. The design target
remains well below 100 ms for local tools and below 300 ms for bounded mission
queries.

## Validation and STOP boundary

IA-3 is deterministically testable without DCS or a live provider. The focused
matrix covers registry/versioning, input/output validation, policy ordering,
modules, mission/freshness/restricted states, exception isolation, correlation,
deadlines/cancellation, diagnostics privacy, future write contracts, no state
mutation and provider neutrality.

**FIELD TEST NOT REQUIRED.** The first meaningful live AI/tool test belongs
after IA-4 PlannerProvider, IA-5 provider adapter and the controlled IA-6 Router
slice. IA-3 does not begin those stages or Stage 6B.
