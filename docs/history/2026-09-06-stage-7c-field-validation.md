# Stage 7C — recovery-line physical field validation

**STAGE 7C — CLOSED / FIELD VALIDATED.**

Recorded: 2026-09-06.
Machine gate: **PASS**.
Human acoustic gate: **PASS 6/6 (user-confirmed through the official SRS Client)**.

## Recovery source boundary

Canonical closure record for `recovery/a955d7c-radio-validated` in
`C:\Users\Алексей\Documents\GitHub\ORION-recovery-a955d7c`.
Pre-edit branch and HEAD were verified; HEAD was the Stage 7C implementation
`847188d52f04a46656b1be5f5be7c39a407bbc00`
(`Implement Stage 7C protected SpeechKit radio path`). Tracked/staged changes
were empty; unrelated untracked `data/fa18c_value_profiles.json` was preserved.
Only this recovery tree and the supplied field evidence support this closure.
No post-recovery history was used as an architectural source.

## Machine evidence — existing report, no retransmission

Source: the user's uploaded `report.json` from conversation
`6a9ada37-87d0-83eb-a761-c3fc0cffc182` (“Проверка checkpoint источников”).
Original evidence directory reported by the probe:
`C:\Users\CD86~1\AppData\Local\Temp\orion-stage7c-utjux1dc`.
The uploaded attachment was read directly for closure; it was not regenerated.

- Run ID: `d2bfaf3a1a454d05807db394bb39550e`.
- Report SHA-256:
  `de35673d03f57d559f27c1a1df2ceead45c06de8c49ae6a9f6df9532914a2d31`.
- `machine_pass=true`; `presentation_shutdown_clean=true`.
- All six cases: `renderer_composer_exact=true`, unique `tx_id`,
  `state=completed`, `terminal=true`, `failure=null`.
- SpeechKit: `en-US` + `john` for every case, matching exact request-text hashes,
  nonempty bounded even-length PCM, one successful synthesis per case.
- Each correlation: one radio `ENQUEUED → STARTED → COMPLETED` on
  **251.000 MHz AM**, with `failure_code=null`.
- Each correlation: one ordered transport chain
  `srs_adapter_tx_started → srs_tx_started → tx_completed → srs_adapter_tx_completed`.
- Existing recovery implementation's pure `field_machine_gate(report)` returned
  `true` on the uploaded report during this documentation task, including its
  duplicate, ordering, request-hash and correlation checks. Shutdown and radio
  frequency/modulation/failure fields were also checked independently.

The raw report remains external to Git; the run ID and SHA-256 above identify
its exact contents. Temporary evidence paths are not a durable archive.
No provider request, probe execution, or radio transmission was repeated.

## Human acoustic evidence — user confirmation

The user physically listened through the official SRS Client and confirmed:
“все 6/6 были чёткими и правильными” (all six were clear and correct).
This confirmation applies to the six messages in report order:

| Case | Exact protected text | Acoustic result |
| --- | --- | --- |
| heading | `Fly heading zero three seven deg.` | User-confirmed PASS (037) |
| frequency | `Frequency 264.500 MHz.` | User-confirmed PASS (264.500) |
| tacan | `TACAN 44X.` | User-confirmed PASS (44X) |
| laser | `Laser code zero one five seven.` | User-confirmed PASS (0157) |
| negative | `Altitude correction -850 ft.` | User-confirmed PASS (negative −850) |
| unavailable | `Heading unavailable.` | User-confirmed PASS (unavailable) |

The spoken frequency value 264.500 is test content; the transmission channel
was 251.000 MHz AM. Acoustic PASS is attributed to the user, not inferred from
PCM, synthetic WAVs, transport events, or independent listening by the agent.
The report retains `human_review=REQUIRED`; this separate human attestation
fulfills the acoustic gate without altering the machine artifact.

## Closure scope

The validated path is Stage 7A renderer → Stage 7B composer → finalized
protected text → SpeechKit en-US/john → PCM → RadioRouter →
SrsRadioTransportAdapter → SRS → official SRS Client → user-confirmed hearing.
This closes the bounded Stage 7C six-case physical gate. It does not claim that
later stages, live conversational integration, or broader phraseology coverage
have passed. Production code is unchanged; this is a separately authorized
focused documentation closure and recovery-branch push.

Related canonical documents:
[Stage 7C implementation](../stage-7c-protected-presentation.md) and
[ORION Project Memory](../ORION_PROJECT_MEMORY.md#29-recovery-line-stage-7c-physical-field-closure--2026-09-06).
