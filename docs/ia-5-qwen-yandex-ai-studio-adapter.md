# IA-5 Qwen3.6 / Yandex AI Studio Adapter

Status: **IMPLEMENTED — LIVE PROVIDER AND CODE VALIDATED 2026-08-27**.

Next approved stage: **IA-6 Interaction Router + controlled Planner slice**.
IA-6 and Stage 6B are not part of this change.

## Decision and boundary

IA-5 implements one real `PlannerProvider` adapter for Yandex AI Studio's
Responses API and `qwen3.6-35b-a3b`. It conforms to the unchanged IA-4
`PlannerProvider` / `PlannerRun` boundary:

```text
InteractionRequest -> IA-4 -> YandexQwenPlannerProvider -> Responses API
                                      | function_call
                                      v
                                IA-4 -> IA-3 -> IA-2
                                      | ToolResult
                                      v
                      previous_response_id continuation
                                      v
                       strict JSON -> IA-0 SemanticResponse
```

The adapter never receives World Model owners or Core handlers. It exposes only
the IA-3 definitions already filtered by IA-4 capabilities. Provider calls are
translated back to IA-4 events; only IA-4 constructs `ExecutionContext` and only
IA-3 executes a tool. No Router, presentation, Realtime, SpeechKit, SRS, DCS or
action-tool integration is introduced.

## Current official provider contract

The implementation was audited against current official Yandex documentation:

- Responses: `POST https://ai.api.cloud.yandex.net/v1/responses` and model URI
  `gpt://<folder_id>/qwen3.6-35b-a3b`.
- Authentication: `Authorization: Api-Key <secret>` and
  `OpenAI-Project: <folder_id>`. The API key requires the current AI Studio
  scope `yc.ai.foundationModels.execute`; `yc.ai.languageModels.execute` is the
  Text Generation API scope. Responses access also depends on current service
  account roles, documented as `ai.assistants.editor` and
  `ai.languageModels.user`.
- Non-streaming Responses supports function tools, strict JSON Schema,
  `previous_response_id`, usage and reasoning effort. IA-5 uses the live-verified
  `low` default because IA-4 deliberately has no provider-specific effort seam.
- Provider responses may be retained for 30 days when `store=true`; IA-5 keeps
  IDs only inside one planner run, calls DELETE for every obtained response at
  terminal success/failure/cancellation, then closes the session. Hidden
  reasoning items are counted/ignored and never copied into Core state.

Authoritative references:

- <https://aistudio.yandex.ru/docs/en/ai-studio/api/Responses/createResponse.html>
- <https://aistudio.yandex.ru/docs/en/ai-studio/api-ref/authentication.html>
- <https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/models.html>
- <https://yandex.cloud/en/docs/iam/concepts/authorization/api-key>
- <https://aistudio.yandex.ru/docs/en/ai-studio/operations/generation/multimodels-request-responses.html>
- <https://aistudio.yandex.ru/docs/en/ai-studio/concepts/agents/assistant-responses-migration.html>
- <https://aistudio.yandex.ru/docs/en/ai-studio/api/Responses/getResponse.html>

Provider documentation does not define a useful server-side cancellation token
for this synchronous mode. IA-5 therefore cancels its local future, enforces the
Core absolute deadline, closes the reusable connection, and deletes every
response ID it actually received. Deletion after a connection failure is not
observable when no response ID was returned.

## Live gates

All provider probes used the existing Windows Credential Manager target and the
existing non-secret Folder ID. No key, Authorization header or provider body was
persisted. DCS, SRS, Launcher and audio devices were not started.

1. **Auth/model:** the existing credential authenticated and the exact model URI
   was accepted. A deliberately tiny output budget produced `incomplete`, which
   proved auth/model availability but not ordinary completion.
2. **Ordinary response:** `store=false`, low reasoning, HTTP 200, completed exact
   visible text, response ID and valid usage. Reasoning content was discarded.
3. **Structured output:** simple, optional/null and nested schemas passed strict
   validation. A tightened SemanticResponse-like schema passed both provider
   strict JSON and local IA-0 Pydantic validation. Broad fact schemas were
   rejected as unsafe and were not used.
4. **Function continuation:** a harmless synthetic function produced a call ID;
   `function_call_output` plus opaque `previous_response_id` returned the exact
   synthetic value. Both stored responses were deleted.
5. **Adapter:** deterministic offline transport tests prove parsing, errors,
   retry, cleanup, privacy, aliases, strict schemas and continuation.
6. **Real vertical:** synthetic ownship state completed through real Qwen, one
   IA-3 ownship call, IA-2 ToolResult, continuation and IA-0 response. Accepted
   facts included heading and position scalar leaves with the completed call ID.

The live vertical exposed three adapter-specific issues and their narrow fixes:

- Yandex function names reject dots. Canonical IA-3 names remain unchanged;
  IA-5 uses a stable readable alias plus SHA-256 suffix and reverses it only
  after validating that the alias belongs to the task's exposed set.
- Reading only the first available HTTP chunk can truncate a valid JSON body.
  The transport now accumulates all chunks to EOF under a hard 1 MiB ceiling.
- Combining forced function selection with the final strict text schema caused
  Qwen to produce a message instead of the tool call. Tool and final phases are
  separated: the first tool step has no final text schema; continuations and
  no-tool runs use the strict SemanticResponse schema.

One stochastic provider response produced an invalid semantic shape. It was
rejected by unchanged IA-4 and did not become an ORION response. A subsequent
bounded run passed. Provider structured output reduces malformed syntax but
does not replace IA-0/IA-4 semantic validation.

## Translation and truth handling

IA-3 input model identities map deterministically to their Core-owned Pydantic
JSON Schemas. Annotation-only titles/defaults are removed, every property is
explicitly required for provider strict mode, optional values remain nullable,
and extra properties are forbidden. Unknown schema identities fail closed.

Provider tool aliases never grant capability, permission, module, freshness,
confirmation or side-effect authority. A call is accepted only when its alias,
call ID and JSON-object arguments validate against the current exposed set. The
adapter creates `PlannerToolRequest`; it never executes provider JSON.

Core retains the complete `ToolResult` and receipt. The provider receives a
bounded projection of nested WorldFacts: composite values become scalar leaves,
while status, authority, source, unit, reason, observed time, age, generation and
confidence are preserved. Non-WorldFact outputs such as ping remain intact.
Unknown/unavailable/stale/restricted are never converted to empty/current/false.

The final provider draft omits Core-owned interaction/response identity. IA-5
injects the original interaction ID and constructs a real `SemanticResponse`.
Strict schema requires naturalized semantic data; no radio wording is generated.
IA-4 then independently verifies capability and authoritative call provenance.
The existing IA-4 limitation remains: exact value-to-ToolResult byte binding and
freshness presentation policy are IA-6 work, not relaxed in IA-5.

## HTTP, retry, errors and diagnostics

One reusable `aiohttp.ClientSession` lives on a dedicated loop for one bounded
planner run and is reused across every continuation. Connect/read limits and the
Core absolute deadline bound waits; cancellation is polled without busy waiting.
The full body is bounded to 1 MiB. Sessions and loop threads close
deterministically; terminal stored response IDs are deleted.

Only transport timeout/reset, 429 and selected 5xx responses are retried, and
only up to IA-4's `ProviderRetryPolicy`. A provider retry does not call IA-3 and
cannot repeat a completed Core ToolResult. 400/401/403, schema, tool and final
semantic failures are never retried. Detailed adapter diagnostics distinguish
auth, permission, model unavailable, rate limit, timeout, unavailable, protocol,
invalid response/tool and structured-output classes; IA-4 events map them into
its existing provider-neutral failure set.

The bounded diagnostic ring records task/model, stage, attempt, HTTP scalar,
opaque response ID, latency, tool name and safe failure category. It excludes
the API key, headers, prompt/user text, request/response bodies, tool arguments,
ToolResults, World Model data and provider reasoning.

## Credentials and lifecycle

The API key is loaded only from existing Credential Manager target
`ORION/Voice/v1/YandexApiKey`; Folder ID is loaded from existing
`cloud-voice.json`. `qwen_workspace_id` / Realtime Workflow ID is neither part of
the IA-5 config nor emitted to Responses requests. The model and endpoint are
fixed to the audited IA-5 contract; arbitrary URLs/models fail configuration.

IA-5 creates no persistent provider memory. `previous_response_id` is used only
inside one IA-4 task, instructions are repeated because the provider does not
carry them automatically, and all local continuation state is discarded at the
terminal boundary.

## STOP boundary

IA-5 supplies an adapter and a proven synthetic vertical only. It does not wire
normal product traffic to Qwen. The next approved stage is IA-6, which may add a
controlled Interaction Router slice and the missing exact semantic fact binding.
Do not begin Stage 6B, domain action exposure or voice integration as IA-5 work.
