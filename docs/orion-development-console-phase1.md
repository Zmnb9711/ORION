# ORION Development Console — Phase 1

## Boundary

The Development Console is repository-local development tooling under
`tools/orion_development_console/`. It is not imported by `orion/**`, is not a
Launcher mode, is not shipped by the product installer, and never starts Core
or any other production ORION process during default verification.

The UI uses Python's existing Tk/ttk stack. This reuses the repository's proven
desktop presentation pattern without embedding the Console in the end-user
Launcher or adding a web/framework dependency. Run it from a development
checkout with:

```powershell
python -m tools.orion_development_console ui --repository C:\path\to\ORION
```

The headless equivalent of `ПРОВЕРИТЬ ВСЁ` is:

```powershell
python -m tools.orion_development_console verify --repository C:\path\to\ORION
```

## Truth domains

Every observation belongs to exactly one domain:

- `HISTORICAL_TRUTH`: Guard, L0-derived index, decisions and Evidence;
- `CURRENT_DEVELOPMENT_STATE`: local Git and cached tracking refs;
- `CURRENT_MACHINE_STATE`: installation, local data, DCS and SRS.

Repository HEAD is never used as proof of the installed build. A checkpoint is
never used as proof of current machine state. File presence is never promoted
to live DCS/SRS readiness.

## Verification model

`VerificationObservation` carries its subject, domain, explicit state,
verification timestamp and method, fingerprint, bounded source reference,
invalidation reasons, details, and independent `installed`, `configured`,
`running`, and `ready` facts. Allowed states are `VERIFIED`, `STALE`,
`CHANGED`, `NEW`, `MISSING`, `PARTIAL`, `UNKNOWN`, `ERROR`, and
`NOT_CHECKED`.

The permanent panel shows Git, History, Logs, Evidence, Installed ORION, Local
ORION Data, DCS Integration, and SRS. Each row exposes its current state,
summary, timestamp and a details view. The architecture preflight AG report ID
is displayed separately from the local `OV-...` verification report ID.

## Read-only collectors

Phase 1 reconnects the existing mechanisms rather than creating parallel
scanners:

- local Git CLI metadata without `fetch` or other network access;
- AG-0 manifest fingerprints, the AG-1 SQLite index opened in read-only mode,
  AG-2 graph metadata and the applicable AG-3 report;
- AG-0 bounded runtime-log, Evidence and local-release discovery;
- the existing frozen Core/Launcher build identity marker validation;
- the installer AppId, uninstall metadata and bounded canonical layout;
- existing DCS installation/Saved Games discovery and Export hook semantics;
- existing SRS bounded executable discovery and passive exact-process
  inspection.

The default action never launches ORION, Core, Launcher, DCS, SRS, a provider
or a microphone; never repairs/installs files; never elevates; and never
creates a missing source directory. Cached upstream data is labelled as a
local tracking ref, not a live remote verification.

## Reports, privacy and staleness

Private derived reports are stored below
`%LOCALAPPDATA%\ORION\development\console\`. Their stable identity is
`OV-<timestamp>-<head7>-<hash8>`. Reports contain observation fingerprints and
bounded metadata, but no raw audio, credentials, Authorization data, provider
tokens or private log/Evidence bodies.

The latest report is a comparison baseline, not an authority. A changed
dependency fingerprint invalidates a previously verified observation as
`CHANGED`. A cached verified observation ages to `STALE` after the configured
freshness interval. Missing and inaccessible inputs remain `MISSING`,
`PARTIAL`, `UNKNOWN`, or `ERROR`; they are never converted into green status.

## Deferred phases

Phase 1 does not implement Recall All, Task Recall, checkpoints, checkpoint
comparison, roadmap, continuation prompts, or direct ChatGPT/Codex delivery.
Those features must use the typed verification report seam rather than infer
current machine state from historical data.
