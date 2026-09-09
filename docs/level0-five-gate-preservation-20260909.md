# Level-0 accumulated protocol checkpoint (before free-conversation integration)

ORION ARCHITECTURE GUARD: OFF

Parent: 9ccab967dfe018f29302fb87e8105a4bb11a89de. This preserves the complete
unfinished event/candidate-envelope work, NOT a successful voice feature.
Canonical recovery docs: d0f58b5693e4a5f7467e32566be88674e24d4001.
Hybrid field runtime f0c9e364; frozen full-voice historical runtime 57a563a.

External immutable reports: C:\Users\Алексей\Documents\ORION-Builds\level0-event-contract-20260909.

| Report | Outcome | SHA-256 |
|---|---|---|
| structured-provider-result.json | response audio configuration rejected as payload | 17DC876913337185C1430E4E3DC82BF889B69FF8D150FD05574D385F999EF81B |
| second-structured-provider-result.json | structural audio type rejected | FCC8E48F293358983AC997368ABBB2D5E6B4B90B3AD278C38B24776E367909F4 |
| third-structured-provider-result.json | null transcript extra key rejected | 7AE7127324A6AC50B0C62EB5F3F6047B60C628598219E3705E627982FDE4BC51 |
| fourth-structured-provider-result.json | completed text; fenced candidate rejected | 8E73E2F0ECAEC32E6338A77E5DF7EE35CAE243B1F3DCD1C45A3266978B544529 |
| fifth-structured-provider-result.json | typed candidate; positive phrase admission rejected | 9C88F6A9D2C47D68A350F7DFBF5AE6A440BE42929BEAEE9AAB7241AEB31BCC25 |

Fifth terminal completed with 0 audio deltas, 0 actual audio payload, 0 tools,
0 Planner/ToolGateway/DCS facts, clean request-scoped shutdown. First text 375 ms,
text/candidate 625 ms after response.create. No TTS or field validation.

Candidate-envelope offline gate: 1410 PASS / 4 existing SKIP, static PASS.
The subsequent semantic-admission audit made no code changes and no sixth call.
Its stop showed that deterministic phrase matching cannot be described as
general semantic assurance. The new 2026-09-09 product authorization replaces
that requirement with explicit routing/capability isolation and bounded,
non-authoritative conversation. Historical reports remain unchanged.
