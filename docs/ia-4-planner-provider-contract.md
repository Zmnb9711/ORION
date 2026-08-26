# IA-4 PlannerProvider Contract

Status: **IMPLEMENTED — CODE-VALIDATED 2026-08-27**.

Next approved stage: **IA-5 Qwen3.6-35B / Yandex AI Studio Adapter**.

## Decision

IA-4 adds a provider-neutral boundary and a small Core-owned lifecycle for one
planning interaction. It does not select planner versus fast-path routing and
does not connect to an AI provider.

```text
InteractionRequest
        |
        v
Core PlannerTaskRunner ---- Core policy/deadline/cancellation
        |                              |
        v                              v
PlannerProvider / PlannerRun      filtered IA-3 catalog
        |                              |
        | PlannerToolRequest           |
        +------------------------------+
                                       v
                               IA-3 ToolGateway
                                       |
                                       v
                                   ToolResult
                                       |
        +------------------------------+
        | continue_with_tool_results
        v
PlannerRun -> SemanticResponse -> Core validation -> PlannerExecutionResult
```

Core owns task and interaction identity, capability and permission policy, the
tool catalog, `ExecutionContext`, call/result correlation, receipts, replay
ledger, deadlines, cancellation, final-response acceptance and diagnostics.
The provider owns only its short-lived continuation and optional opaque request,
model, usage and latency metadata. It receives no MissionStore, telemetry
history, cockpit dump, transcript history, domain owner or unrestricted state.

## Contracts

`planner_contracts.py` defines immutable, extra-forbid, bounded Pydantic models:

- `PlannerProviderRequest` contains the original task-scoped
  `InteractionRequest`, the exact Core capability allowlist, only matching IA-3
  `ToolDefinition` entries, bounded Core instructions, absolute deadline and
  provider retry policy.
- `PlannerToolRequest` contains stable call identity, ORION tool name/version,
  bounded arguments and an optional future idempotency key. It deliberately has
  no `ExecutionContext`; the provider cannot grant itself capabilities,
  permissions, confirmation or actor identity.
- provider-neutral events cover started, tool-call batch, final response,
  provider failure, cancellation acknowledgement and provider timeout. Tool
  results are returned directly through `continue_with_tool_results`; a second
  provider event merely to echo acceptance would add no Core truth.
- `PlannerTaskSnapshot` and `PlannerExecutionResult` expose explicit
  created/running/waiting/completed/failed/cancelled/timed-out semantics,
  correlation IDs, completed IA-3 receipts, safe failure, usage and bounded
  latency. No chain-of-thought or provider payload is represented.

`PlannerProvider` starts one task and returns a short-lived `PlannerRun`.
`next_event` receives the Core absolute deadline and cancellation token so an
IA-5 adapter can use bounded, interruptible I/O rather than busy polling.
`PlannerCancellationToken.wait` is event-backed. IA-4 itself performs no network
wait and no provider HTTP retry.

## Core-owned tool loop

For each tool batch, Core checks cancellation and deadline, enforces the
configured maximum round count, constructs IA-3 `ExecutionContext` from Core
policy and calls only `ToolGateway.execute`. Results, including stale,
unavailable or restricted provenance, are returned unchanged to the provider.
A non-completed ToolResult fails the planner task as `tool_call_rejected`; the
provider cannot reinterpret a rejected call as execution success.

Call IDs are task-local replay identities. Core stores a canonical signature and
the completed ToolResult. Repeating the same call reuses that exact result and
receipt without invoking the handler again; reusing the ID with changed tool,
arguments, version or idempotency key fails. Provider event IDs have the same
conflict check. An exact replay does not consume another tool round. This is
already useful for read-only tools and is required before any future write tool
can be exposed. IA-3 receipt/idempotency policy remains the execution authority.

Sequential rounds and multiple calls in one batch are supported. IA-4 executes
a batch deterministically in order; the contract permits a future safe parallel
implementation without changing event shape. No workflow engine, background
agent loop or persistent provider continuation is introduced.

## Final SemanticResponse acceptance

Success requires an IA-0 `SemanticResponse`; raw text, arbitrary JSON and
provider response objects are invalid. Core verifies:

1. the response interaction ID equals the task interaction ID;
2. any declared response capability belongs to the original allowlist;
3. every authoritative fact cites a `tool_result` context reference matching a
   completed call in the Core ledger;
4. that result has IA-2 provenance containing authoritative source authority.

Pydantic validation preserves IA-0 categories and rejects extra fields before
the event reaches the runner. Restricted/non-completed results cannot establish
authoritative fact provenance.

The current seam intentionally does **not** prove that each semantic key/value
is an exact projection of bytes inside the cited ToolResult, nor does it turn a
stale authoritative source into fresh truth. Exact fact-to-result binding and
policy for freshness/warnings require the controlled IA-6 interaction context.
Until then, missing or non-authoritative provenance fails closed; no invented
provenance is accepted.

## Deadline, cancellation, retry and failure

The absolute Core deadline covers provider start, provider waits, every tool and
every continuation. Core checks it before provider start, around each event,
before every new tool execution and before continuation. Expiry cancels the
provider run where possible, executes no new tool and returns `timed_out` with
`deadline_exceeded`.

Cancellation uses the same boundary and stops new tools. Completed reads remain
recorded and are never undone or repeated. A future adapter must honor the
deadline/token passed to `next_event` and implement transport interruption in
IA-5.

`ProviderRetryPolicy` is a Core-owned bound for future adapter network retries.
Only provider-unavailable/timeout failures may be marked retryable. IA-4 has no
HTTP retry loop, and a provider retry never calls the Tool Gateway by itself;
completed tool replays are resolved from the Core ledger. Tool execution retry
is a separate IA-3 concern.

Stable safe errors distinguish provider availability/timeout/protocol,
invalid events/tool requests/final response, rejected tools, round limit,
deadline, cancellation and internal failure. Provider failure messages are
normalized to Core text. Raw exceptions from provider start/event/continuation,
Gateway calls or cancellation are never copied to results or diagnostics.

## Diagnostics and metadata

The default in-memory diagnostic ring retains at most 500 typed scalar lifecycle
events: task/provider start, tool request/result, continuation, completion,
failure, cancellation or timeout, with safe correlation IDs and latency.
Prompts, user text, tool arguments/results, provider payloads, credentials,
headers, mission state and hidden reasoning are excluded.

Optional provider-neutral usage holds bounded opaque provider request IDs, model
identity, token counts, attempts and provider/tool-wait latency. It contains no
credential or transport fields.

## Deterministic proof and STOP boundary

The test-only scripted provider covers immediate response, one and multiple tool
rounds, multi-call batches, call and event replay/conflict, rejected tools,
stale/restricted/unavailable results, round limits, provider failures, deadline,
cancellation and privacy. The vertical acceptance test proves:

`InteractionRequest -> fake provider -> IA-3 -> IA-2 ownship -> ToolResult ->`
`fake continuation -> provenance-bound SemanticResponse`.

IA-4 imports no Qwen, Yandex, OpenAI, Anthropic, MCP, SRS or SpeechKit module and
performs no network, audio or DCS operation. It does not add a Router, provider
adapter, action tool or voice change.

**FIELD TEST NOT REQUIRED.** The exact next stage is IA-5, which may translate a
real Qwen/Yandex AI Studio API into these contracts. IA-6 remains responsible
for routing and the first controlled runtime Planner slice. IA-5, IA-6 and Stage
6B are not started here.
