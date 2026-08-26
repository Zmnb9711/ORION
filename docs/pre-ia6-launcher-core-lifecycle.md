# PRE-IA-6 Launcher/Core Lifecycle Correction

Status: **IMPLEMENTED AND CODE-VALIDATED**. IA-5 remains complete; IA-6 is next.

## Contract

- Closing the Launcher window hides it to the tray. The Launcher process, tray
  icon, its Core child and active runtime sessions remain alive.
- Explicit tray **Exit** is authoritative. The Launcher stops active realtime
  work, requests graceful shutdown of its own Core, waits for a bounded period,
  verifies process exit and UDP release, then removes the tray icon and exits.
- A healthy Core that existed before Launcher startup is external. Launcher may
  use it, but Exit never terminates it by PID file, executable name, executable
  path, HTTP/UDP port or other inferred identity.

## Ownership and shutdown

Ownership requires both the live `subprocess.Popen` handle returned when this
Launcher created Core and a fresh random token passed only in the child
environment. The token is neither logged nor persisted. Core exposes a hidden
loopback lifecycle endpoint that accepts only that token and sets Uvicorn's
graceful `should_exit` flag. Uvicorn then runs normal lifespan cleanup, including
closing the telemetry UDP transport and router-owned background resources.

Launcher waits three seconds for graceful exit. If the request is unavailable
or times out, it may call `terminate()` and finally `kill()` only through the
same owned child handle. Every wait is bounded. Non-owned Core has no token or
handle in the manager, so no shutdown request or fallback is possible.

Lifecycle events are written as bounded, scalar-only JSON lines in
`launcher-lifecycle.jsonl`. Credentials, tokens, provider payloads and the
environment are excluded.

## Validation boundary

Deterministic tests cover window/tray semantics, strict ownership, token
rejection, graceful/fallback/race paths, bounded diagnostics and port reuse. An
isolated source integration test started Core twice on temporary HTTP/UDP ports;
both graceful exits released UDP and allowed clean restart. The user's installed
Core and canonical UDP 45100 were not stopped or modified.

Installer upgrade/uninstall remains a separate privileged lifecycle boundary.
Its existing image-name process cleanup is not used by normal Launcher Exit and
was not redesigned in this tranche.
