# ORION Architecture Guard AG-0

AG-0 is repository-local development tooling. It does not run inside ORION
Core or Launcher and does not decide product architecture.

Its invariant is limited to source discovery:

> The Guard knows which historical source streams exist, where they are, what
> they are, and whether they changed.

## Commands

From the repository root:

```powershell
python -m tools.orion_arch_guard discover
python -m tools.orion_arch_guard verify
```

An explicit local configuration may be supplied with `--config`. The tracked
template is
`tools/orion_arch_guard/source-roots.example.json`. User-specific paths belong
in a private copy outside Git.

The default generated manifest is:

```text
%LOCALAPPDATA%\ORION\development\architecture-guard\source-manifest.json
```

`discover` fingerprints configured sources, reports the differential against
an existing manifest, then atomically writes the current manifest. `verify`
re-discovers the configured sources and reports differences without modifying
the manifest. Its exit code is zero only when every record is unchanged.

## Source records

Every record includes:

- stable source ID;
- source type and path;
- availability;
- bounded size, SHA-256 and UTC mtime where applicable;
- format, privacy class and discovery method;
- bounded metadata and a bounded error value.

Immutable files use full-file SHA-256 plus size. Identical immutable content at
a different path has the same content-derived source ID and is reported as
`RELOCATED`.

Git uses a stable hashed repository identity plus a state fingerprint covering
HEAD, all refs, tracked/staged diff hashes and tracked/staged counts. Raw remote
URLs are not stored.

Release directories use a bounded manifest of top-level installers/archives
and nested `build-identity.json` markers. Binary dependency trees are not
recursively hashed. Source-root records use the identities of discovered child
records, not the bytes of every child directory.

## Change semantics

- `UNCHANGED`: same logical source and fingerprint;
- `CHANGED`: same source path/type, different fingerprint;
- `MISSING`: previously recorded source is unavailable;
- `NEW`: newly discovered or newly available source;
- `RELOCATED`: same immutable source fingerprint at a different path.

A new ChatGPT export is `NEW`, not corruption. Same-path changed immutable
content is surfaced explicitly and is never silently treated as unchanged.

## Privacy

Supported classes are:

- `PRIVATE_PRIMARY_HISTORY`;
- `PRIVATE_EVIDENCE`;
- `PRIVATE_RUNTIME_LOG`;
- `PROJECT_GIT`;
- `PUBLIC_OR_NON_SENSITIVE`;
- `GENERATED_GUARD_METADATA`.

Unknown historical user data defaults to private. The manifest contains no raw
conversation body, raw audio, Authorization header, API key, token or password.
Evidence ZIP inspection is bounded to allowlisted scalar metadata such as a
valid build SHA or session identity. Primary archives and Evidence remain in
their original locations and are never copied into Git.

## AG-1 boundary

AG-0 does not create SQLite/FTS or semantic indexes, parse conversation meaning,
build capability graphs, ingest decisions, mine implementations, compare
Previous Best solutions, or apply FULL/STANDARD/LIGHT Architecture Gate rules.
Those are later Architecture Guard stages.
