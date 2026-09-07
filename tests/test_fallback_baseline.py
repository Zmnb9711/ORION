"""Literal source and inherited lifecycle proofs, with no live I/O."""
from pathlib import Path
import ast
import subprocess
from timing_oracle import without_timing

from orion.full_voice_service import FullVoiceService
from orion.yandex_srs_live_core import YandexSrsLiveService, SHUTDOWN_TIMEOUT_SECONDS

BASE = "a955d7c39f20c020e15de6bc2be272755928cc98"
GOLDEN = "57a563a067c980c3ff8057172aa6f5fefb33a5b0"
ROOT = Path(__file__).resolve().parents[1]


def source(ref, path):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def test_launcher_core_srs_lifecycle_is_literal_baseline():
    files = list((ROOT / "orion").glob("launcher*.py"))
    files += [ROOT / "orion" / name for name in (
        "app.py", "core_process.py", "core_lifecycle.py", "core_main.py",
        "realtime_session_control.py", "realtime_provider.py", "srs_process_control.py",
        "srs_radio_transport.py", "srs_protocol.py", "srs_opus.py", "srs_resampler.py",
        "yandex_srs_live_core.py", "realtime_test_evidence_api.py", "realtime_test_evidence.py",
        "realtime_tool_api.py", "world_model.py", "tool_gateway.py")]
    for path in files:
        actual = path.read_text(encoding="utf-8")
        if path.name == "realtime_test_evidence.py":
            actual = without_timing(path.name, actual)
            # Sole separately authorized addition; all existing recorder code
            # must remain literal baseline, including START/STOP/export.
            method = next(n for n in ast.walk(ast.parse(actual))
                          if isinstance(n, ast.FunctionDef) and n.name == "record_stt_core_boundary")
            lines = actual.splitlines(keepends=True)
            actual = "".join(lines[:method.lineno-1] + lines[method.end_lineno+1:])
        assert actual == source(BASE, path.relative_to(ROOT).as_posix()), path


def test_only_existing_adapter_imports_change():
    path = "orion/realtime_live_core.py"
    expected = source(BASE, path).replace(
        "from orion.yandex_srs_live_core import YandexSrsStartRequest, yandex_srs_live",
        "from orion.yandex_srs_live_core import YandexSrsStartRequest\n"
        "        from orion.full_voice_service import full_voice_service as yandex_srs_live",
    ).replace("from orion.yandex_srs_live_core import yandex_srs_live",
              "from orion.full_voice_service import full_voice_service as yandex_srs_live")
    assert (ROOT / path).read_text(encoding="utf-8") == expected


def test_old_owner_methods_and_shutdown_bound_are_inherited_not_reimplemented():
    for name in ("__init__", "start", "status", "_set", "stop"):
        assert name not in FullVoiceService.__dict__
        assert getattr(FullVoiceService, name) is getattr(YandexSrsLiveService, name)
    assert SHUTDOWN_TIMEOUT_SECONDS == 6.0


def test_ported_production_components_are_exact_golden_not_today():
    names = ("bounded_radio_stream", "communication_contracts", "full_voice_capture",
        "full_voice_core", "full_voice_srs", "full_voice_stt", "interaction_router",
        "ownship_phraseology", "ownship_report", "phraseology_renderer", "protected_presentation",
        "protected_streaming_presentation", "protected_streaming_tts", "radio_contracts",
        "radio_router", "response_composer", "speechkit_tts_adapter", "speechkit_v3_stt_transport",
        "srs_radio_adapter", "srs_transmission", "srs_tx_state")
    paths = [f"orion/{name}.py" for name in names]
    paths += [p.relative_to(ROOT).as_posix() for p in
              (ROOT / "orion/yandex_speechkit_v3_proto").iterdir() if p.is_file()]
    paths.append("pyproject.toml")
    for path in paths:
        actual = (ROOT / path).read_text(encoding="utf-8")
        actual = without_timing(Path(path).name, actual)
        assert actual == source(GOLDEN, path), path


def test_today_worker_evidence_and_latency_are_not_deployed():
    for name in ("full_voice_runtime.py", "full_voice_evidence.py", "voice_latency_profile.py",
                 "full_voice_field.py", "full_voice_live_world.py"):
        assert not (ROOT / "orion" / name).exists()
    service = (ROOT / "orion/full_voice_service.py").read_text(encoding="utf-8")
    assert "RecoveryLiveWorld(" not in service and "start_udp_bridge" not in service
    assert "from orion.world_model import world_model" in service
    assert '"stopping"' not in service
