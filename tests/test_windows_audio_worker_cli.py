from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from orion.windows_audio_worker import AudioDuckingPolicy, AudioWorkerState, WindowsAudioWorker
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


def test_worker_process_applies_radio_effect_and_ducking_hooks(tmp_path: Path) -> None:
    played: list[Path] = []
    ducking: list[tuple[AudioDuckingPolicy, bool]] = []
    wav = tmp_path / "awacs.wav"
    radio_wav = tmp_path / "awacs-radio.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    radio_wav.write_bytes(b"RIFF0000WAVE")
    backend = AudioBackend(
        lambda path, device, volume: played.append(path),
        lambda: None,
        prepare_radio=lambda path: radio_wav,
        set_ducking=lambda policy, active: ducking.append((policy, active)),
    )
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), backend)

    result = process.handle({
        "action": "play",
        "command_id": str(uuid4()),
        "audio_path": str(wav),
        "ducking_policy": "non_radio",
        "radio_effect": True,
    })

    assert result["state"] == AudioWorkerState.IDLE.value
    assert result["ducking_policy"] == "non_radio"
    assert result["radio_effect"] is True
    assert played == [radio_wav]
    assert ducking == [
        (AudioDuckingPolicy.NON_RADIO, True),
        (AudioDuckingPolicy.NON_RADIO, False),
    ]


def test_worker_process_releases_ducking_when_playback_fails(tmp_path: Path) -> None:
    ducking: list[tuple[AudioDuckingPolicy, bool]] = []
    wav = tmp_path / "callout.wav"
    wav.write_bytes(b"RIFF0000WAVE")

    def fail_play(path: Path, device: str, volume: float) -> None:
        raise RuntimeError("backend failure")

    backend = AudioBackend(
        fail_play,
        lambda: None,
        set_ducking=lambda policy, active: ducking.append((policy, active)),
    )
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), backend)

    with pytest.raises(RuntimeError, match="backend failure"):
        process.handle({
            "action": "play",
            "command_id": str(uuid4()),
            "audio_path": str(wav),
            "ducking_policy": "all",
        })

    assert ducking == [
        (AudioDuckingPolicy.ALL, True),
        (AudioDuckingPolicy.ALL, False),
    ]


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
