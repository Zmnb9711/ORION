from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orion.app import app
from orion.windows_audio_worker import AudioDevice, AudioPlaybackRequest, AudioWorkerState, WindowsAudioWorker
import orion.windows_audio_worker_api as audio_api


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
    assert "/v1/windows-audio/stt/status" in paths
    assert "/v1/windows-audio/stt/prepare" in paths
    assert "/v1/windows-audio/play" in paths
    assert "/v1/windows-audio/stop" in paths


def test_stt_snapshot_promotes_existing_runtime_to_ready(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=False))
    monkeypatch.setattr(audio_api, "runtime_ready", lambda: True)
    status = audio_api._stt_snapshot()
    assert status.ready is True
    assert status.stage == "ready"
    assert status.percent == 100.0


def test_stt_progress_tracks_percent_and_ready_state(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=False))
    audio_api._stt_progress("model", 25, 100)
    status = audio_api._stt_status
    assert status.running is True
    assert status.percent == 25.0
    assert status.downloaded_bytes == 25
    assert status.total_bytes == 100

    audio_api._stt_progress("model", 200, 100)
    assert audio_api._stt_status.percent == 100.0

    audio_api._stt_progress("runtime", 10, None)
    assert audio_api._stt_status.percent is None

    audio_api._stt_progress("ready", 100, 100)
    assert audio_api._stt_status.ready is True
    assert audio_api._stt_status.running is False
    assert audio_api._stt_status.percent == 100.0


def test_prepare_worker_records_failure(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=True, stage="starting"))

    def fail(*, progress):
        raise RuntimeError("download failed")

    monkeypatch.setattr(audio_api, "ensure_runtime", fail)
    audio_api._prepare_stt_worker()
    assert audio_api._stt_status.running is False
    assert audio_api._stt_status.stage == "failed"
    assert "download failed" in audio_api._stt_status.error


def test_prepare_worker_forwards_progress(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=True, stage="starting"))

    def succeed(*, progress):
        progress("runtime", 5, 10)
        progress("ready", 10, 10)
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(audio_api, "ensure_runtime", succeed)
    audio_api._prepare_stt_worker()
    assert audio_api._stt_status.ready is True
    assert audio_api._stt_status.stage == "ready"


def test_prepare_stt_returns_when_already_ready_or_running(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "runtime_ready", lambda: False)
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=True, running=False, stage="ready"))
    assert audio_api.prepare_stt().ready is True

    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=True, stage="model"))
    status = audio_api.prepare_stt()
    assert status.running is True
    assert status.stage == "model"


def test_prepare_stt_starts_background_worker(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "runtime_ready", lambda: False)
    monkeypatch.setattr(audio_api, "_stt_status", audio_api.SttProvisionStatus(ready=False, running=False))
    started = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            assert name == "orion-whisper-prepare"
            assert daemon is True

        def start(self):
            started.append(True)

    monkeypatch.setattr(audio_api.threading, "Thread", FakeThread)
    status = audio_api.prepare_stt()
    assert started == [True]
    assert status.running is True
    assert status.stage == "starting"


def test_conversation_endpoint_refuses_unprepared_stt(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "runtime_ready", lambda: False)
    result = audio_api.conversation_audio_test()
    assert result.ok is False
    assert "not prepared" in result.message
    assert result.stages["core_connected"] is True


def test_conversation_endpoint_returns_success_and_diagnostic_failure(monkeypatch) -> None:
    monkeypatch.setattr(audio_api, "runtime_ready", lambda: True)
    success = audio_api.ConversationalAudioTestResult(
        ok=True,
        recognized_text="Привет, как дела?",
        stages={
            "core_connected": True,
            "input_resolved": True,
            "audio_captured": True,
            "phrase_recognized": True,
            "output_resolved": True,
            "response_played": True,
        },
        message="ok",
    )
    monkeypatch.setattr(audio_api, "run_conversational_audio_test", lambda: success)
    assert audio_api.conversation_audio_test().ok is True

    monkeypatch.setattr(audio_api, "run_conversational_audio_test", lambda: (_ for _ in ()).throw(RuntimeError("device boom")))
    failure = audio_api.conversation_audio_test()
    assert failure.ok is False
    assert "device boom" in failure.message


def test_audio_api_delegates_device_catalog_and_selection(monkeypatch) -> None:
    endpoint = SimpleNamespace()
    monkeypatch.setattr(audio_api.windows_audio_worker, "devices", lambda: [AudioDevice(device_id="a", name="A", is_default=True)])
    monkeypatch.setattr(audio_api.wasapi_endpoint_catalog, "endpoints", lambda direction=None: [endpoint])
    monkeypatch.setattr(audio_api.wasapi_endpoint_catalog, "vr_candidates", lambda: [endpoint])
    monkeypatch.setattr(audio_api.audio_device_config, "state", lambda: "state")
    monkeypatch.setattr(audio_api.audio_device_config, "reset", lambda: "reset")

    assert audio_api.list_audio_devices()[0].device_id == "a"
    assert audio_api.list_wasapi_endpoints() == [endpoint]
    assert audio_api.list_wasapi_inputs() == [endpoint]
    assert audio_api.list_wasapi_outputs() == [endpoint]
    assert audio_api.list_wasapi_vr_candidates() == [endpoint]
    assert audio_api.get_audio_selection() == "state"
    assert audio_api.reset_audio_selection() == "reset"
