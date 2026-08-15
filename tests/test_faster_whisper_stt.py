from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import orion.faster_whisper_stt as stt


def _complete_model(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "preprocessor_config.json"):
        (root / name).write_bytes(b"model")


def test_runtime_ready_requires_complete_ctranslate2_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    root = stt.model_dir()
    _complete_model(root)
    marker = stt.stt_root() / stt.RUNTIME_VERSION_MARKER

    assert stt.runtime_ready() is False
    marker.write_text(stt.ENGINE_VERSION + "\n", encoding="utf-8")
    assert stt.runtime_ready() is True
    (root / "model.bin").unlink()
    assert stt.runtime_ready() is False


def test_ensure_runtime_downloads_medium_to_orion_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    calls: list[tuple[str, str]] = []

    def fake_download(name: str, output_dir: str):
        calls.append((name, output_dir))
        root = Path(output_dir)
        _complete_model(root)
        return str(root)

    monkeypatch.setattr(stt, "_import_engine", lambda: (object, fake_download))
    result = stt.ensure_runtime()

    assert result == stt.model_dir()
    assert calls == [("medium", str(stt.model_dir()))]
    assert stt.runtime_ready() is True


def test_recognize_wav_uses_cpu_int8_without_external_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("ORION_WHISPER_THREADS", "4")
    _complete_model(stt.model_dir())
    (stt.stt_root() / stt.RUNTIME_VERSION_MARKER).write_text(stt.ENGINE_VERSION + "\n", encoding="utf-8")

    init_kwargs: dict[str, object] = {}
    transcribe_kwargs: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model_path: str, **kwargs):
            init_kwargs["model_path"] = model_path
            init_kwargs.update(kwargs)

        def transcribe(self, audio: str, **kwargs):
            transcribe_kwargs["audio"] = audio
            transcribe_kwargs.update(kwargs)
            return iter([SimpleNamespace(text=" Привет, "), SimpleNamespace(text="как дела? ")]), SimpleNamespace()

    monkeypatch.setattr(stt, "_import_engine", lambda: (FakeWhisperModel, object()))
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setattr(stt, "_model_path", None)

    audio = tmp_path / "input.wav"
    audio.write_bytes(b"wav")
    text = stt.recognize_wav(audio, language="ru")

    assert text == "Привет, как дела?"
    assert init_kwargs["model_path"] == str(stt.model_dir())
    assert init_kwargs["device"] == "cpu"
    assert init_kwargs["compute_type"] == "int8"
    assert init_kwargs["cpu_threads"] == 4
    assert init_kwargs["num_workers"] == 1
    assert init_kwargs["local_files_only"] is True
    assert transcribe_kwargs["language"] == "ru"
    assert transcribe_kwargs["beam_size"] == 1
    assert transcribe_kwargs["best_of"] == 1
