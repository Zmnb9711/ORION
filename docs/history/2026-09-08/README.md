# Preserved ORION records — 2026-09-08

ORION ARCHITECTURE GUARD: OFF

Start with [the end-of-day recovery checkpoint](../2026-09-08-end-of-day-checkpoint.md).
This archive contains original historical reports. Their imperative language,
earlier pending stages and earlier no-commit statements describe their original
task, not fresh authorization. No archived probe/script should be executed as
part of recovery. Its one-shot latch is preserved with its result.

## Reports

- [Early free-conversation recovery audit](reports/early-free-conversation-audit.md):
  complete saved Codex final response, including Data Export evidence provenance.
- [Level-0 prerequisite stop](reports/level0-conversation-prerequisite-stop-20260908.md):
  original report before the later diagnostic probe and preservation commit.
- [Yandex text protocol probe](reports/yandex-text-protocol-probe-report.md).
- [Yandex audio-envelope documentation audit](reports/yandex-audio-envelope-contract-audit.md):
  original uploaded report with official-source links/access date; no new web audit.
- [Submitted support ticket DT403405](reports/support-ticket-DT403405.md):
  exact saved submission report/message, Open/awaiting clarification at that time.
- [Earlier latency profile](reports/latency-profile.md): historical measurements;
  subsequent commit `92a019f3` preserves that separate branch's completed history.

## Evidence and inventory

- `evidence/field/`: six original field-evidence ZIPs from 2026-09-08.
- `evidence/level0-conversation-20260908/`: original first probe source/result and
  saved prerequisite regression XML. The probe is live-capable archival source.
- `evidence/yandex-realtime-text-protocol-probe-20260908/`: original probe source,
  characterization tests/result, attempt latch and protocol JSON. Do not run it.
- `evidence/hybrid-*/`: saved artifact identities, existing smoke results and
  regression XMLs, where available. Copying these is not a new build/test run.
- `evidence-manifest.json`: original paths, sizes and SHA-256 for copied evidence
  and baseline documents. `artifact-file-inventory.json` retains hashes of other
  existing build-source/log/archive files that remain local.
- `archive-hashes.json`: SHA-256 for every saved archive file except itself;
  verifies reports, evidence and canonical snapshots after Git storage.
- `level0-original-files.json`: seven original untracked files, hashes and
  classification. They are now committed only on the experiment branch.
- `worktrees-before.json`, `branches-before.json`: observed local inventory and
  actual remote refs before pushes. Unrelated dirty trees were not cleaned.
- `preservation-validation.json`: bounded local preservation checks, not new
  runtime/field validation.

## Canonical document snapshots

`canonical-snapshots/dev-42520a57/` preserves the broader development branch's
Project Memory, master architecture checkpoint, master decision register,
canonical development policy and IA/radio history. These were missing/newer
relative to recovery `dca668d5`. Both histories remain available without merging
their runtime. Current recovery position is specified by the end-of-day file.

The original report paths may refer to this user's machine; the corresponding
files saved here are portable. Full unrelated ChatGPT Data Export contents,
credentials and installed products are not published in this archive.
