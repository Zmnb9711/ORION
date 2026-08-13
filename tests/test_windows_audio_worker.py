from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orion.app import app
from orion.windows_audio_worker import AudioDevice, AudioPlaybackRequest, AudioWorkerState, WindowsAudioWorker


def test_worker_accepts_wav_and_tracks_selected_device() -> None:
    worker = WindowsAudioWorker()
    worker.select_device(AudioDevice(device_id="pimax", name="Pimax VR Headset", is_default=False))
    command_id = uuid4()

    status = worker.play(AudioPlaybackRequest(command_id=command_id, audio_path="runtime/tts/test.wav", output_device_id="pimax"))

    assert status.state is AudioWorkerState.PLAYING
    assert status.command_id == command_id
    assert status.output_device_id == "pimax"


def test_worker_rejects_second_playback_until_stopped() -> None:
    worker = WindowsAudioWorker()
    first = uuid4()
    worker.play(AudioPlaybackRequest(command_id=first, audio_path="runtime/tts/first.wav"))

    with pytest.raises(ValueError):
        worker.play(AudioPlaybackRequest(command_id=uuid4(), audio_path="runtime/tts/second.wav"))

    stopped = worker.stop(first)
    assert stopped.state is AudioWorkerState.STOPPED


def test_worker_rejects_non_wav_paths() -> None:
    worker = WindowsAudioWorker()
    with pytest.raises(ValueError):
        worker.play(AudioPlaybackRequest(command_id=uuid4(), audio_path="runtime/tts/test.mp3"))


def test_windows_audio_routes_are_registered() -> None:
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/windows-audio/devices" in paths
    assert "/v1/windows-audio/wasapi/inputs" in paths
    assert "/v1/windows-audio/wasapi/outputs" in paths
    assert "/v1/windows-audio/selection" in paths
    assert "/v1/windows-audio/selection/reset" in paths
    assert "/v1/windows-audio/play" in paths
    assert "/v1/windows-audio/stop" in paths
