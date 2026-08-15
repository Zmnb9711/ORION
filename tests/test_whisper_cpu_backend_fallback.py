from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import orion.whisper_cpp_stt as stt


# Regression coverage for pinned generic CPU runtime recovery.
def test_windows_status_normalizes_signed_ntstatus():
    assert stt._windows_status(-1073741795) == stt.WINDOWS_ILLEGAL_INSTRUCTION
    assert stt._windows_status(-1073740791) == stt.WINDOWS_FAIL_FAST_EXCEPTION


def test_runtime_ready_requires_complete_cpu_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "models" / stt.WHISPER_MODEL_FILENAME
    model.parent.mkdir()
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")

    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "_windows_runtime_complete", lambda candidate: False)
    assert stt.runtime_ready() is False

    monkeypatch.setattr(stt, "_windows_runtime_complete", lambda candidate: True)
    assert stt.runtime_ready() is True


def test_pinned_generic_backend_is_preserved(tmp_path: Path):
    generic = tmp_path / stt.PORTABLE_CPU_BACKEND
    stale_variant = tmp_path / "ggml-cpu-haswell.dll"
    generic.write_bytes(b"cpu")
    stale_variant.write_bytes(b"stale")

    disabled = stt._force_portable_cpu_backend(tmp_path, trigger_status=stt.WINDOWS_FAIL_FAST_EXCEPTION)

    assert generic.is_file()
    assert not stale_variant.exists()
    assert (tmp_path / "ggml-cpu-haswell.dll.orion-disabled").read_bytes() == b"stale"
    assert {path.name for path in disabled} == {"ggml-cpu-haswell.dll.orion-disabled"}
    marker = (tmp_path / "ORION_PORTABLE_CPU_BACKEND.txt").read_text(encoding="utf-8")
    assert "ggml-cpu.dll" in marker
    assert "0xC0000409" in marker


def test_recognize_wav_retries_with_pinned_backend_after_windows_backend_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "runtime"
    root.mkdir()
    cli = root / "whisper-cli.exe"
    model = root / "models" / stt.WHISPER_MODEL_FILENAME
    model.parent.mkdir()
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    (root / stt.PORTABLE_CPU_BACKEND).write_bytes(b"cpu")
    (root / "ggml-cpu-haswell.dll").write_bytes(b"stale")

    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "_prepare_input_wav", lambda source, target: target.write_bytes(b"wav"))
    monkeypatch.setattr(stt, "_is_windows_portable_recovery_status", lambda returncode: returncode == -1073740791)

    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, -1073740791, stdout="", stderr="backend crash")
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет, как дела?\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(stt, "_run_whisper", fake_run)

    transcript = stt.recognize_wav(tmp_path / "input.wav")

    assert transcript == "Привет, как дела?"
    assert len(calls) == 2
    assert (root / stt.PORTABLE_CPU_BACKEND).is_file()
    assert not (root / "ggml-cpu-haswell.dll").exists()
    assert (root / "ggml-cpu-haswell.dll.orion-disabled").is_file()


def test_failure_detail_always_preserves_return_code_and_backend_output():
    completed = subprocess.CompletedProcess(["whisper-cli"], 7, stdout="", stderr="backend detail")
    detail = stt._failure_detail(completed)
    assert "exit=7" in detail
    assert "status=" in detail
    assert "backend detail" in detail
