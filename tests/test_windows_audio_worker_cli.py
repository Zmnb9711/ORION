from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from orion.windows_audio_worker import AudioDuckingPolicy, AudioWorkerState, WindowsAudioWorker
from orion.windows_audio_worker_cli import AudioBackend, WindowsAudioWorkerProcess, run_stdio


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


def test_worker_process_applies_radio_effect_without_external_audio_ducking(tmp_path: Path) -> None:
    played: list[Path] = []
    wav = tmp_path / "awacs.wav"
    radio_wav = tmp_path / "awacs-radio.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    radio_wav.write_bytes(b"RIFF0000WAVE")
    backend = AudioBackend(
        lambda path, device, volume: played.append(path),
        lambda: None,
        prepare_radio=lambda path: radio_wav,
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
    assert result["ducking_policy"] == AudioDuckingPolicy.NON_RADIO.value
    assert result["radio_effect"] is True
    assert played == [radio_wav]


def test_ducking_policy_is_metadata_only_for_windows_worker(tmp_path: Path) -> None:
    played: list[Path] = []
    wav = tmp_path / "callout.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    backend = AudioBackend(lambda path, device, volume: played.append(path), lambda: None)
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), backend)

    result = process.handle({
        "action": "play",
        "command_id": str(uuid4()),
        "audio_path": str(wav),
        "ducking_policy": "all",
    })

    assert result["ducking_policy"] == AudioDuckingPolicy.ALL.value
    assert played == [wav]


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


def test_backend_failure_stops_worker_and_preserves_original_exception(tmp_path: Path) -> None:
    wav = tmp_path / "failure.wav"
    wav.write_bytes(b"RIFF0000WAVE")

    def fail_playback(path: Path, device: str, volume: float) -> None:
        raise OSError("audio endpoint disappeared")

    worker = WindowsAudioWorker()
    process = WindowsAudioWorkerProcess(worker, AudioBackend(fail_playback, lambda: None))

    with pytest.raises(OSError, match="audio endpoint disappeared"):
        process.handle({
            "action": "play",
            "command_id": str(uuid4()),
            "audio_path": str(wav),
        })

    assert worker.status().state is AudioWorkerState.STOPPED


def test_stdio_protocol_reports_bad_command_and_continues() -> None:
    process = WindowsAudioWorkerProcess(
        WindowsAudioWorker(),
        AudioBackend(lambda path, device, volume: None, lambda: None),
    )
    stdin = io.StringIO('{bad json}\n{"action":"status"}\n')
    stdout = io.StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        assert run_stdio(process, poll_interval_s=0) == 0

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses[0]["ok"] is False
    assert responses[1]["ok"] is True
    assert responses[1]["result"]["state"] == AudioWorkerState.IDLE.value


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
