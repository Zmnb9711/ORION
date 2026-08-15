from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from orion import whisper_cpp_stt as stt


def _bind_ready_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    cli = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-medium.bin"
    source = tmp_path / "input.wav"
    cli.write_bytes(b"cli")
    model.write_bytes(b"model")
    source.write_bytes(b"wav")
    monkeypatch.setattr(stt, "runtime_ready", lambda: True)
    monkeypatch.setattr(stt, "whisper_cli_path", lambda: cli)
    monkeypatch.setattr(stt, "whisper_model_path", lambda: model)
    return source, cli


class FakeProcess:
    def __init__(self, returncode: int) -> None:
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


def test_legacy_recognition_paths_are_removed() -> None:
    assert not hasattr(stt, "_prepare_input_wav")
    assert not hasattr(stt, "_read_pcm16_mono_16k")
    assert not hasattr(stt, "_force_portable_cpu_backend")
    assert not hasattr(stt, "_run_whisper")


def test_recognizer_uses_original_wav_and_sanitized_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, cli = _bind_ready_runtime(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        output_base = Path(command[command.index("--output-file") + 1])
        output_base.with_suffix(".txt").write_text("Привет как дела", encoding="utf-8")
        return FakeProcess(0)

    monkeypatch.setattr(stt.subprocess, "Popen", fake_popen)
    assert stt.recognize_wav(source, language="ru") == "Привет как дела"

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert isinstance(command, list)
    assert command[command.index("--file") + 1] == str(source.resolve())
    assert command[command.index("--language") + 1] == "ru"
    assert "--no-gpu" in command
    assert kwargs["cwd"] == str(cli.parent)
    assert "creationflags" not in kwargs
    assert "capture_output" not in kwargs
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["stdin"] is stt.subprocess.DEVNULL
    assert isinstance(kwargs["env"], dict)


def test_recognizer_reports_native_windows_status_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _cli = _bind_ready_runtime(monkeypatch, tmp_path)
    calls = 0

    def fake_popen(command, **kwargs):
        nonlocal calls
        calls += 1
        return FakeProcess(-1073740791)

    monkeypatch.setattr(stt.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError, match="0xC0000409"):
        stt.recognize_wav(source, language="ru")
    assert calls == 1


def test_recognizer_never_installs_runtime_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    source.write_bytes(b"wav")
    monkeypatch.setattr(stt, "runtime_ready", lambda: False)
    with pytest.raises(RuntimeError, match="not prepared"):
        stt.recognize_wav(source)


@pytest.mark.skipif(os.name != "nt", reason="Windows PyInstaller DLL search behavior")
def test_frozen_child_environment_removes_meipass_from_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "Core" / "_internal"
    nested = bundle / "some-hook"
    normal = tmp_path / "normal-bin"
    bundle.mkdir(parents=True)
    nested.mkdir()
    normal.mkdir()
    monkeypatch.setattr(stt.sys, "frozen", True, raising=False)
    monkeypatch.setattr(stt.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join((str(bundle), str(nested), str(normal))))

    env = stt._sanitized_child_env()

    assert str(bundle) not in env["PATH"]
    assert str(nested) not in env["PATH"]
    assert str(normal) in env["PATH"]


@pytest.mark.skipif(os.name != "nt", reason="Windows PyInstaller DLL search behavior")
def test_frozen_whisper_launch_resets_and_restores_dll_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "Core" / "_internal"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(stt.sys, "frozen", True, raising=False)
    monkeypatch.setattr(stt.sys, "_MEIPASS", str(bundle), raising=False)
    calls: list[object] = []

    class Kernel32:
        @staticmethod
        def SetDllDirectoryW(value):
            calls.append(value)
            return 1

    monkeypatch.setattr(stt.ctypes, "windll", SimpleNamespace(kernel32=Kernel32()), raising=False)

    with stt._external_program_dll_scope():
        calls.append("child-created")

    assert calls == [None, "child-created", str(bundle)]


@pytest.mark.skipif(os.name != "nt", reason="Windows PyInstaller DLL search behavior")
def test_spawn_restores_core_dll_path_before_waiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "Core" / "_internal"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(stt.sys, "frozen", True, raising=False)
    monkeypatch.setattr(stt.sys, "_MEIPASS", str(bundle), raising=False)
    calls: list[object] = []

    class Kernel32:
        @staticmethod
        def SetDllDirectoryW(value):
            calls.append(("dll", value))
            return 1

    class Process:
        def wait(self):
            calls.append(("wait", None))
            return 0

    def fake_popen(*args, **kwargs):
        calls.append(("popen", None))
        return Process()

    monkeypatch.setattr(stt.ctypes, "windll", SimpleNamespace(kernel32=Kernel32()), raising=False)
    monkeypatch.setattr(stt.subprocess, "Popen", fake_popen)

    returncode = stt._spawn_whisper(
        ["whisper-cli.exe"],
        cwd=tmp_path,
        stdout_handle=None,
        stderr_handle=None,
    )

    assert returncode == 0
    assert calls == [
        ("dll", None),
        ("popen", None),
        ("dll", str(bundle)),
        ("wait", None),
    ]
