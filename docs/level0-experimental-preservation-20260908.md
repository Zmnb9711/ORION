# Level-0 experimental preservation — 2026-09-08

ORION ARCHITECTURE GUARD: OFF

This branch is an archival checkpoint of an **UNWIRED EXPERIMENT**. It is not a
production baseline, integration approval, successful provider gate or build input.
Do not merge, build, install, field-test or run these modules/probes on the basis
of this preservation commit. Existing production runtime files are unchanged.

The four new `orion/` modules and two new offline tests are preserved in their
original paths and bytes. The original prerequisite stop report is preserved
unchanged; its statements about being uncommitted describe its earlier timestamp.
All seven files match the SHA-256 recorded by the subsequent protocol probe.

The first prerequisite probe stopped at `nontext_session` before sending user
text. A later, separate diagnostic probe generated text but received audio-related
events. Zero audio-delta events does not prove zero audio payload in every field.
The draft predicate remains unchanged and Level-0 is NOT INTEGRATED / NOT BUILT /
NOT FIELD READY. No new runtime validation is claimed by this archival commit.

Yandex support ticket [DT403405](https://center.yandex.cloud/support/tickets/DT403405)
is **awaiting provider clarification**, according to the saved submission record
of 2026-09-08. No engineering reply is present in the checkpoint evidence.

Full end-of-day recovery record, original reports and evidence are maintained on
`codex/eod-20260908-checkpoint`, in `docs/history/2026-09-08/` and
`docs/history/2026-09-08-end-of-day-checkpoint.md`. That branch starts from the
same docs freeze `dca668d530dc6cbc4de05064400b22c2216ada3f` and does not add the
experimental runtime to its production package.

Approved presentation policy: **authoritative source labels silent by default;
provenance remains internal unless explicitly requested.** Authority, freshness
and exact binding remain mandatory. The frozen spoken DCS prefix was not changed;
policy approval is not an implementation claim.

Next step: read the saved checkpoint and the provider's actual answer, when
available; reconcile session/response modality, all audio payload locations and
terminal text consistency before considering any separately authorized parser
change. Do not repeat probes or substitute historical Qwen voice automatically.
