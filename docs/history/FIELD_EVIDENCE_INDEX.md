# ORION field evidence index

Updated 2026-09-14. Historical classification; no new tests.
Current product verdict: FIELD FAIL. [Current state](../ORION_PROJECT_MEMORY.md).
Foundation Step 1 on governance `be413a8`: [offline routing record](2026-09-14-foundation-step1-routing.md).
Real service route with fake provider/audio/radio I/O only; NOT a new physical
session, acoustic PASS, Conversation quality PASS or Mixed execution PASS.
E5 means scoped physical proof; E6 means blind, continuous installed-host
acceptance of a named capability. No current E6 general Foundation PASS exists.

“Completed” means machine TX completion, not acoustic proof. UNKNOWN is intentional.
Archive root R: C:/Users/Алексей/AppData/Local/ORION/runtime/test-evidence/.
Source IDs refer to [audit section A](2026-09-14-foundation-recovery-audit.md).
Archive filenames may use UTC; known actual times below use Moscow.

## FIELD PASS — only the explicitly named scope

| Capability / date | Build, session, exact input if available | Route / Core fact or action / TTS / SRS | Hearing / blind wording / production host / DCS | Evidence scope |
|---|---|---|---|---|
| Early natural voice, Aug 20 | #402 / 4e8b49a; session, question and answer not recovered; S2 user 75bb1360… | Qwen Realtime generated audio → direct FIFO playback; no SRS or Core-fact proof. | User: “речь стала нормальной”; blind UNKNOWN; normal ORION reported; DCS UNKNOWN. | E5 speech quality, not exhaustive knowledge or follow-ups. |
| Two no-DCS SRS answers, Aug 24 | 1a06a09 / fae96a9; exact words and session UNKNOWN; ADR007. | Yandex Realtime → SRS; canonical RadioInfo; reported 382 frames; no Core facts. | Two answers heard; blind UNKNOWN; tester, NOT production host; no DCS. | E5 controlled 251 AM / BLUE transport. |
| Cockpit channel isolation, Aug 25 | Stage 5.1 / e2bdb4a historical linkage; S2 user 4ba36188… | 251 → 252 → 251; response → silence → response; Yandex/SRS. | Hearing confirmed; prepared procedure; production host; real F/A-18C. | E5 frequency routing; exact spoken words not recorded. |
| IA-1.1 presentation, Aug 26, 22:35–22:37 | R/ORION-Test-Evidence-20260826-193719.zip; session 20e810b1462e461392556159eba07499; run 0d55414b75924092b36b9bda31308657; 293b627 external code linkage; ZIP build UNKNOWN. | Ten synthetic cases × Realtime/SpeechKit; 20 WAV / 20 TX; semantic checks passed. Historical retry after a real connect timeout. | Acoustic review clear; NOT blind; probe UI; no authoritative live DCS facts required. | E5 output fidelity, not twenty conversational requests. |
| 6B routed radio, Aug 28, 01:45 | R/ORION-Test-Evidence-20260827-224514.zip; session 950de1dea1c5431d898e19a287d5be3a; a955d7c via historical closure; ZIP build UNKNOWN. | RadioRouter → SrsRadioTransportAdapter → existing TX; 20 tx_completed and 20 adapter completions; synthetic WAV. | Historical closure records user confirmation; NOT blind; product probe; live DCS fact use not established. | E5 router/transport migration. |
| 7C protected phrases, Sep 6 | Implementation 847188d52f04a46656b1be5f5be7c39a407bbc00; closure 72625dc; run d2bfaf3a1a454d05807db394bb39550e. | 037, 264.500, 44X, 0157, minus 850, unavailable; one SpeechKit en-US/john synthesis per case → protected RadioRouter/SRS. Actual radio channel 251 AM. | User confirmed all six clear and correct; prepared outputs; controlled proof, not a live DCS query. | E5, closure document and user statement. Raw report not reopened in this audit; identity below. |
| Ownship full voice, Sep 7 | 57a563a / e753d0c; docs/full-voice-field-ready.md; twice: “Какой мой текущий курс и координаты?” | Native FINAL/EOU → selected typed heading/latitude/longitude → 7A/7B/7C → john → SRS; changed authoritative facts on turn two. | Both answers heard clearly; prepared query; dedicated host, NOT installed Launcher; real DCS. | E5 bounded vertical; 3266/3000 ms to first TX. |
| Unsupported gate, Sep 7 | Same 57a563a; joke query; exact recognized wording not claimed. | Native final → Core unsupported → zero TX. Earlier STT failure excluded from this proof. | User confirmed silence; prepared gate; dedicated host; DCS running. | E5 fail-closed behavior for that case, NOT generative chat. |
| Recovered installed ownship, Sep 7 | 333ca5e / freeze 05c8327; R/ORION-Test-Evidence-20260907-202700.zip; session 198e1e16acd24f45b27a21be3542bf6d; turn d9b31e5c-9853-4c07-994a-297490ef32d3. | STT → bounded Core → protected TTS → SRS. | User heard clearly; prepared; installed host; real DCS. | E5 audible bounded answer. Exact response and matching source snapshot were not fully logged. |
| Measured installed ownship, Sep 8 | 18a3a79 via S12 artifact linkage; ZIP build UNKNOWN. R/ORION-Test-Evidence-20260908-123259.zip and -123800.zip; sessions c3e60b2fb0774a5d8fcd8c1be167d45c / e778258e81ac470a874384d98fd46adc. | “какой мой текущий курс и координаты”; same authoritative Core path; 385 frames each. Turns 47613e3e-3cbb-4ec3-8e8a-5d576d743f76 / 7cbef17b-a1d8-41e7-bd1c-1af42a53f1a6. | Both clear; prepared; installed host; real F/A-18C. | E5, two queries; 3389.100/3039.413 ms to first TX. No independent numerical re-audit here. |
| Bounded generated social reply, Sep 10, 00:45 | d324529; R/ORION-Test-Evidence-20260909-214800.zip; session 95d8d892d19a46df93bb301e8f9b9e69; turn 956e58a6-ecc0-418a-b32e-7e17958578dd. | “что то сегодня полет идет тяжело” → one Yandex text call → “Сочувствую, бывает такое… надеюсь, скоро ситуация наладится!” → jane → 131 frames; zero Core fact reads. | User: “звук есть, нормальный, с небольшой задержкой”; prepared class, not general blind acceptance; installed host; DCS context present but no fact read. | E5, one generated support turn; about 5.3 seconds. |
| Aircraft natural language, Sep 10 | 2c58b3752ad79a639db6e406e2eeb1927b21086d; R/ORION-Test-Evidence-20260910-161956.zip; session 6fdc19215e7744feb10ccaf446879b18. | “что у нас за машина” → AI typed aircraft.identity → orion.world.ownship.get / dcs_export → “Вы находитесь в F/A-18C Hornet.” → 91 frames. | User hearing confirmed; natural field wording, not proof of all paraphrases; installed host; real DCS. | Strongest current user-facing fact slice; about 602 ms semantic processing / 3125 ms to first TX. |

7C primary closure: docs/history/2026-09-06-stage-7c-field-validation.md at
57a563a. Original temporary report directory:
C:/Users/CD86~1/AppData/Local/Temp/orion-stage7c-utjux1dc.
Recorded report SHA-256:
de35673d03f57d559f27c1a1df2ceead45c06de8c49ae6a9f6df9532914a2d31.
This is the closure document's hash record, not a new hash verification of that report.

Historical local Hybrid aircraft success at dca668d/f0c9e36 is distinct from
the later AI interpretation proof at 2c58b37. This index consolidates capabilities;
it does not list every repetition in all 91 ZIPs.

## FIELD FAIL

| Scope | Build / evidence | Failure and user/host status |
|---|---|---|
| Early Qwen voice | #396 / 1963c60; S2 user 095e97dd…; subsequent #398 report. | Choppy, unintelligible answer after about ten seconds; #398 produced a clear greeting then crashed. Not stable voice. |
| General Conversation | 2c58b37; R/ORION-Test-Evidence-20260910-163257.zip; session 852052d544bf4635b153091625c792d5. | Six finals: four ordinary conversational turns ended not_applicable/unsupported/silent; a local “как дела” constant and aircraft route answered. Zero Conversation provider calls. Installed DCS host. |
| General ingress | 7b6981a; R/ORION-Test-Evidence-20260910-182918.zip; session e14aa26dce5c446e99bd956a3c5c555f. | Twenty finals; invalid provider terminal, later zero-operation failures and position delivery silence. User blind FIELD FAIL. |
| Latest general product | 5c9ab244; R/ORION-Test-Evidence-20260910-213600.zip; session b09b2c3176734601991bfc67000266e0. | Twenty finals; twelve completed and eight failed transmissions. Seven RESOURCE_EXHAUSTED failures with zero PCM/frames; one partial 89-frame response; weapons enum error; identical repeated joke. User: “это опять провал”. Blind installed DCS session; no WAV. |

Latest case identifiers: coordinate turns f8dc1fac…, 0ef22fd3…, a4ea0263…;
META turns a978a7e4…, 2e3004b8…, 0f66d932…, 7b6a9dc5…;
partial cosmos response cd7fbef5…; weapons 774f9e6f…; repeated joke a7de870a….
The malformed STT text “какие у нее карты надо” is what reached Core. Without
RX WAV, the exact physical utterance cannot be reconstructed. RESOURCE_EXHAUSTED
does not distinguish quota/billing from the local 1 MiB receive bound. The exact
message of the partial-response RuntimeError is absent.

## PARTIAL / HISTORICAL INDIVIDUAL PASS

- S9, August 25: 16315 telemetry records containing Hornet identity. Ingress proof,
  not proof that all values have valid units or can be spoken safely.

- Some latest aircraft, heading and general dialogue responses completed TX.
  There is no separate acoustic confirmation for each; the overall blind verdict
  is FAIL. Do not count twelve completed transmissions as twelve correct answers.

- 7b6981a position turn d269d15e-3edd-479c-9bc5-a375216a2680 in
  R/ORION-Test-Evidence-20260910-191229.zip: the existing report records
  1032764 PCM bytes and 269 frames. Individual technical success, not reliability.

- Latest weapons validation failure → warm owner RECOVERY_READY at 1109 ms →
  a later real AI/Core operation. Recovery worked; this does not fix weapons
  coverage or failed TTS delivery.

- The remembered MODEL C telemetry dump remains a mandatory regression constraint.
  Its exact defective commit is unproven. It is distinct from Stage 6A value errors.

## NOT FIELD VALIDATED AS CURRENT PRODUCT CAPABILITIES

General Conversation and general DCS access; consistent knowledge and follow-ups;
all seven selectors across modules; arbitrary safe fact selection; mixed dialogue
and facts; reliable longer TTS; generalized fuel/speed/payload/cockpit/mission
access; broad ATC/AWACS/GCI/JTAC/AAR; persistent personal context.

Some have code or provider fixtures; others remain blocked or unimplemented.
An aggregate test count cannot change this classification.

## Evidence retrieval

Audit section A records archive hashes, source linkage and inspection limits.
Many recent ZIPs contain metadata/events but no WAV. Exact AI/TTS text may exist
in slice events even when the separate assistant-transcript counter is zero.
Acoustic success must come from user confirmation or recording, never from
a local UDP-send event alone.

Latest archive SHA-256:
7e8971fbc4a1e53b196aa0321d3d765666f7f16950c86a445dda411d268aa2c7.
