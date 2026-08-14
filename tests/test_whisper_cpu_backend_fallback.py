from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import orion.whisper_cpp_stt as stt


def test_windows_status_normalizes_signed_ntstatus():
    assert stt._windows_status(-1073741795) == stt.WINDOWS_ILLEGAL_INSTRUCTION


def test_force_portable_cpu_backend_keeps_x64_and_disables_optimized(tmp_path: Path):
    generic = tmp_path / "ggml-cpu-x64.dll"
    haswell = tmp_path / "ggml-cpu-haswell.dll"
    alderlake = tmp_path / "ggml-cpu-alderlake.dll"
    generic.write_bytes(b"x64")
    haswell.write_bytes(b"haswell")
    alderlake.write_bytes(b"alderlake")

    disabled = stt._force_portable_cpu_backend(tmp_path)

    assert generic.is_file()
    assert not haswell.exists()
    assert not alderlake.exists()
    assert (tmp_path / "ggml-cpu-haswell.dll.orion-disabled").read_bytes() == b"haswell"
    assert (tmp_path / "ggml-cpu-alderlake.dll.orion-disabled").read_bytes() == b"alderlake"
    assert {path.name for path in disabled} == {
        "ggml-cpu-haswell.dll.orion-disabled",
        "ggml-cpu-alderlake.dll.orion-disabled",
    }
    assert (tmp_path / "ORION_PORTABLE_CPU_BACKEND.txt").is_file()


def test_recognize_wav_retries_with_portable_backend_after_illegal_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "runtime"
    root.mkdir()
    cli = root / "whisper-cli.exe"
    model = root / "models" / stt.WHISPER_MODEL_FILENAME
    model.parent.mkdir()
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    (root / "ggml-cpu-x64.dll").write_bytes(b"x64")
    (root / "ggml-cpu-haswell.dll").write_bytes(b"haswell")

    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    monkeypatch.setattr(stt, "_prepare_input_wav", lambda source, target: target.write_bytes(b"wav"))
    monkeypatch.setattr(stt, "_is_windows_illegal_instruction", lambda returncode: returncode == -1073741795)

    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                command,
                -1073741795,
                stdout="",
                stderr="load_backend: loaded CPU backend from ggml-cpu-haswell.dll",
            )
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет, как дела?\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(stt, "_run_whisper", fake_run)

    transcript = stt.recognize_wav(tmp_path / "input.wav")

    assert transcript == "Привет, как дела?"
    assert len(calls) == 2
    assert (root / "ggml-cpu-x64.dll").is_file()
    assert not (root / "ggml-cpu-haswell.dll").exists()
    assert (root / "ggml-cpu-haswell.dll.orion-disabled").is_file()


def test_failure_detail_always_preserves_return_code_and_backend_output():
    completed = subprocess.CompletedProcess(
        ["whisper-cli"],
        7,
        stdout="",
        stderr="backend detail",
    )

    detail = stt._failure_detail(completed)

    assert "exit=7" in detail
    assert "status=" in detail
    assert "backend detail" in detail
