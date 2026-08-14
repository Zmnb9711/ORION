from pathlib import Path
from types import SimpleNamespace

import orion.audio_conversation_test as subject
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


def _endpoints():
    mic = WasapiEndpoint(device_id="mic", name="Mic", direction=WasapiDirection.INPUT)
    out = WasapiEndpoint(device_id="out", name="Out", direction=WasapiDirection.OUTPUT)
    return mic, out


def test_matches_control_phrase() -> None:
    assert subject._matches_control_phrase("Привет, как дела?")
    assert subject._matches_control_phrase("ПРИВЕТ! Как, дела...")
    assert not subject._matches_control_phrase("Привет")


def test_conversation_rejects_missing_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        subject.audio_device_config,
        "state",
        lambda: SimpleNamespace(resolved_input=None, resolved_output=None),
    )
    result = subject.run_conversational_audio_test()
    assert not result.ok
    assert result.message == "Core could not resolve selected audio endpoints"
    assert not result.stages["input_resolved"]
    assert not result.stages["output_resolved"]


def test_conversation_rejects_unrecognized_phrase(monkeypatch) -> None:
    mic, out = _endpoints()
    monkeypatch.setattr(subject.audio_device_config, "state", lambda: SimpleNamespace(resolved_input=mic, resolved_output=out))
    monkeypatch.setattr(subject, "_capture_wav", lambda endpoint, path: 48000)
    monkeypatch.setattr(subject, "recognize_wav", lambda path, language="auto": "совсем другая фраза")
    result = subject.run_conversational_audio_test()
    assert not result.ok
    assert result.recognized_text == "совсем другая фраза"
    assert result.input_samplerate == 48000
    assert result.stages["audio_captured"]
    assert not result.stages["phrase_recognized"]
    assert "Control phrase was not recognized" in result.message


def test_conversation_reports_tts_rejection(monkeypatch) -> None:
    mic, out = _endpoints()
    monkeypatch.setattr(subject.audio_device_config, "state", lambda: SimpleNamespace(resolved_input=mic, resolved_output=out))
    monkeypatch.setattr(subject, "_capture_wav", lambda endpoint, path: 48000)
    monkeypatch.setattr(subject, "recognize_wav", lambda path, language="auto": "Привет как дела")

    class Backend:
        def __init__(self, spool_dir: str) -> None:
            self.spool_dir = spool_dir

        def render(self, request):
            return SimpleNamespace(accepted=False, output_path=None, message="tts unavailable")

    monkeypatch.setattr(subject, "WindowsSapiBackend", Backend)
    result = subject.run_conversational_audio_test()
    assert not result.ok
    assert result.stages["phrase_recognized"]
    assert not result.stages["response_played"]
    assert result.message == "tts unavailable"


def test_conversation_wraps_runtime_error(monkeypatch) -> None:
    mic, out = _endpoints()
    monkeypatch.setattr(subject.audio_device_config, "state", lambda: SimpleNamespace(resolved_input=mic, resolved_output=out))

    def fail_capture(endpoint, path):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(subject, "_capture_wav", fail_capture)
    result = subject.run_conversational_audio_test()
    assert not result.ok
    assert result.message == "Audio test failed: capture failed"
    assert not result.stages["audio_captured"]


def test_conversation_success_without_hardware(monkeypatch) -> None:
    mic, out = _endpoints()
    monkeypatch.setattr(subject.audio_device_config, "state", lambda: SimpleNamespace(resolved_input=mic, resolved_output=out))
    monkeypatch.setattr(subject, "_capture_wav", lambda endpoint, path: 48000)
    monkeypatch.setattr(subject, "recognize_wav", lambda path, language="auto": "Привет как дела")

    class Backend:
        def __init__(self, spool_dir: str) -> None:
            self.spool_dir = Path(spool_dir)

        def render(self, request):
            assert request.text == subject.RESPONSE
            assert request.output_device == "out"
            target = self.spool_dir / "reply.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF")
            return SimpleNamespace(accepted=True, output_path=str(target), message="ok")

    class Player:
        def play(self, path, endpoint) -> None:
            assert path.name == "reply.wav"
            assert endpoint == out

    monkeypatch.setattr(subject, "WindowsSapiBackend", Backend)
    monkeypatch.setattr(subject, "NativeWasapiPlayer", Player)
    result = subject.run_conversational_audio_test()
    assert result.ok
    assert result.input_samplerate == 48000
    assert result.recognized_text == "Привет как дела"
    assert result.message == subject.RESPONSE
    assert all(result.stages.values())
