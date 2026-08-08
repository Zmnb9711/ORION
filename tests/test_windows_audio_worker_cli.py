from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from orion.windows_audio_worker import AudioWorkerState, WindowsAudioWorker
from orion.windows_audio_worker_cli import AudioBackend, WindowsAudioWorkerProcess


def test_worker_process_selects_device_and_plays_existing_wav(tmp_path: Path) -> None:
    calls: list[tuple[Path, str, float]] = []
    backend = AudioBackend(lambda path, device, volume: calls.append((path, device, volume)), lambda: None)
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), backend)
    process.handle({"action": "select_device", "device_id": "vr-headset", "name": "VR Headset"})

    wav = tmp_path / "callout.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    command_id = uuid4()
    result = process.handle({
        "action": "play",
        "command_id": str(command_id),
        "audio_path": str(wav),
        "output_device_id": "vr-headset",
        "volume": 0.7,
    })

    assert result["state"] == AudioWorkerState.IDLE.value
    assert calls == [(wav, "vr-headset", 0.7)]


def test_worker_process_rejects_missing_audio_file(tmp_path: Path) -> None:
    backend = AudioBackend(lambda path, device, volume: None, lambda: None)
    worker = WindowsAudioWorker()
    process = WindowsAudioWorkerProcess(worker, backend)

    with pytest.raises(FileNotFoundError):
        process.handle({
            "action": "play",
            "command_id": str(uuid4()),
            "audio_path": str(tmp_path / "missing.wav"),
        })

    assert worker.status().state is AudioWorkerState.STOPPED


def test_stop_delegates_to_backend_and_worker() -> None:
    stopped: list[bool] = []
    backend = AudioBackend(lambda path, device, volume: None, lambda: stopped.append(True))
    worker = WindowsAudioWorker()
    process = WindowsAudioWorkerProcess(worker, backend)

    result = process.handle({"action": "stop"})

    assert stopped == [True]
    assert result["state"] == AudioWorkerState.IDLE.value


def test_unknown_action_is_rejected() -> None:
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), AudioBackend(lambda path, device, volume: None, lambda: None))
    with pytest.raises(ValueError, match="Unsupported worker action"):
        process.handle({"action": "explode"})
