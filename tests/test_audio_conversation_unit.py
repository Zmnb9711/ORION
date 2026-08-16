from pathlib import Path
from types import SimpleNamespace

import orion.audio_conversation_test as subject
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


def test_matches_control_phrase() -> None:
    assert subject._matches_control_phrase("Привет, как дела?")
    assert not subject._matches_control_phrase("Привет")


def test_conversation_success_without_hardware(monkeypatch) -> None:
    mic = WasapiEndpoint(device_id="mic", name="Mic", direction=WasapiDirection.INPUT)
    out = WasapiEndpoint(device_id="out", name="Out", direction=WasapiDirection.OUTPUT)
    monkeypatch.setattr(subject.audio_device_config, "state", lambda: SimpleNamespace(resolved_input=mic, resolved_output=out))
    monkeypatch.setattr(subject, "runtime_ready", lambda: True)

    def fake_capture(endpoint, path):  # noqa: ANN001, ANN202
        assert endpoint == mic
        path.write_bytes(b"RIFF")
        return 48000

    monkeypatch.setattr(subject, "_capture_wav", fake_capture)
    monkeypatch.setattr(subject, "recognize_wav", lambda path, language="ru": "Привет как дела")

    class Backend:
        def __init__(self, spool_dir: str) -> None:
            self.spool_dir = Path(spool_dir)

        def render(self, request):  # noqa: ANN001, ANN201
            target = self.spool_dir / "reply.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF")
            return SimpleNamespace(accepted=True, output_path=str(target), message="ok")

    class Player:
        def play(self, path, endpoint) -> None:  # noqa: ANN001
            assert path.name == "reply.wav"
            assert endpoint == out

    monkeypatch.setattr(subject, "WindowsSapiBackend", Backend)
    monkeypatch.setattr(subject, "NativeWasapiPlayer", Player)
    result = subject.run_conversational_audio_test()
    assert result.ok
    assert result.input_samplerate == 48000
    assert all(result.stages.values())
