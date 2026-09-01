from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        runtime = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        runtime = base / "ORION" / "runtime"
    else:
        runtime = Path.home() / ".orion" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["ORION_RUNTIME_DIR"] = str(runtime)
    return runtime


def _integrated_product_smoke(result_path: Path, host: str, port: int) -> int:
    """Prove the frozen canonical Launcher -> Core product contract."""

    from orion.core_process import CoreProcessManager

    launcher = Path(sys.executable).resolve()
    expected_core = launcher.parent.parent / "Core" / "ORION-Core.exe"
    runtime = _runtime_root()
    core = CoreProcessManager(host, port, runtime)
    spawned = None
    result: dict[str, object] = {
        "ok": False,
        "launcher_path": str(launcher),
        "core_path": str(expected_core),
        "canonical_launcher_name": launcher.name == "ORION-Launcher.exe",
        "canonical_core_name": expected_core.name == "ORION-Core.exe",
        "canonical_relative_layout": expected_core.is_file(),
        "core_started_by_launcher": False,
        "core_health_ok": False,
        "realtime_status_ok": False,
        "communication_profiles_ok": False,
        "launcher_remained_operational": False,
        "shutdown_ok": False,
        "orphan_core_process": False,
        "network_scope": "loopback-only",
        "audio_devices_opened": False,
        "external_srs_process_started": False,
        "credential_store_ok": False,
        "credential_persisted_after_smoke": False,
        "credential_secret_exposed": False,
    }
    try:
        from orion.windows_credentials import frozen_credential_store_smoke

        if not getattr(sys, "frozen", False):
            raise RuntimeError("Integrated product smoke requires a frozen Launcher")
        if launcher.name != "ORION-Launcher.exe" or not expected_core.is_file():
            raise RuntimeError("Canonical Launcher/Core product layout is incomplete")
        if core.healthy(timeout=0.2):
            raise RuntimeError("Integrated smoke port is already occupied by a healthy Core")

        credential_result = frozen_credential_store_smoke()
        result["credential_store_ok"] = bool(credential_result["ok"])
        result["credential_persisted_after_smoke"] = bool(
            credential_result["credential_persisted_after_smoke"]
        )
        result["credential_secret_exposed"] = bool(credential_result["secret_exposed"])

        core.start()
        spawned = core._process  # Exact child handle owned by this Launcher smoke.
        if spawned is None or not core.owns_process:
            raise RuntimeError("Launcher did not create the delivered Core process")
        result["core_pid"] = spawned.pid
        result["core_started_by_launcher"] = True

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not core.healthy(timeout=0.5):
            if spawned.poll() is not None:
                raise RuntimeError(f"Delivered Core exited during startup: {spawned.returncode}")
            time.sleep(0.1)
        if not core.healthy(timeout=0.5):
            raise RuntimeError("Delivered Core did not become healthy")
        result["core_health_ok"] = True

        with urllib.request.urlopen(
            f"{core.base_url}/v1/realtime/live/status",
            timeout=2.0,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        result["realtime_status_ok"] = (
            status.get("state") == "stopped" and status.get("provider") is None
        )
        with urllib.request.urlopen(
            f"{core.base_url}/v1/communication-profiles",
            timeout=2.0,
        ) as response:
            profiles = json.loads(response.read().decode("utf-8"))
        profile_rows = profiles.get("profiles") if isinstance(profiles, dict) else None
        result["communication_profiles_ok"] = (
            isinstance(profile_rows, list)
            and [item.get("profile_id") for item in profile_rows]
            == ["ICAO", "FAA_US", "NATO_MILITARY", "FAP_RUSSIAN_ATC"]
            and profiles.get("configured_profile_id") is None
            and profiles.get("registry_status") == "UPDATE SOURCE NOT CONFIGURED"
        )
        result["launcher_remained_operational"] = True
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        core.shutdown()
        if spawned is not None:
            result["orphan_core_process"] = spawned.poll() is None
        result["shutdown_ok"] = not bool(result["orphan_core_process"])
        result["ok"] = all(
            bool(result[key])
            for key in (
                "canonical_launcher_name",
                "canonical_core_name",
                "canonical_relative_layout",
                "core_started_by_launcher",
                "core_health_ok",
                "realtime_status_ok",
                "communication_profiles_ok",
                "launcher_remained_operational",
                "shutdown_ok",
                "credential_store_ok",
            )
        ) and not any(
            bool(result[key])
            for key in (
                "orphan_core_process",
                "credential_persisted_after_smoke",
                "credential_secret_exposed",
            )
        )
        result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return 0 if result["ok"] else 1


def _credential_store_smoke(result_path: Path) -> int:
    from orion.windows_credentials import CredentialStoreError, frozen_credential_store_smoke

    try:
        result = frozen_credential_store_smoke()
    except CredentialStoreError as exc:
        result = {"ok": False, "error": str(exc)}
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return 0 if result.get("ok") else 1


def _clear_voice_credentials() -> int:
    from orion.windows_credentials import CredentialStoreError, clear_saved_voice_credentials

    try:
        clear_saved_voice_credentials()
    except CredentialStoreError:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the ORION Launcher UI only.

    The launcher is a client/lifecycle controller. It starts or attaches to the
    independent ORION Core process through ``CoreProcessManager``; it never
    embeds the FastAPI application in its own process.
    """

    parser = argparse.ArgumentParser(description="ORION Launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--srs-control-smoke", metavar="RESULT_JSON")
    parser.add_argument("--integrated-product-smoke", metavar="RESULT_JSON")
    parser.add_argument("--credential-store-smoke", metavar="RESULT_JSON")
    parser.add_argument("--clear-voice-credentials", action="store_true")
    args = parser.parse_args(argv)

    if args.srs_control_smoke:
        from orion.srs_process_control import launcher_srs_offline_smoke

        Path(args.srs_control_smoke).write_text(
            json.dumps(launcher_srs_offline_smoke(), sort_keys=True),
            encoding="utf-8",
        )
        return 0

    if args.integrated_product_smoke:
        return _integrated_product_smoke(
            Path(args.integrated_product_smoke),
            args.host,
            args.port,
        )

    if args.credential_store_smoke:
        return _credential_store_smoke(Path(args.credential_store_smoke))

    if args.clear_voice_credentials:
        return _clear_voice_credentials()

    os.environ["ORION_PROCESS_ROLE"] = "launcher"
    os.environ["ORION_CORE_BASE_URL"] = f"http://{args.host}:{args.port}"

    from orion.desktop_launcher_field_fixed import run_field_fixed_launcher

    return run_field_fixed_launcher(_runtime_root(), host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
