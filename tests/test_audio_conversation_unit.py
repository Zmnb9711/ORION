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
    monkeypatch.setattr(subject, "_capture_wav", lambda endpoint, path: path.write_bytes(b"RIFF"))
    monkeypatch.setattr(subject, "recognize_wav", lambda path, language="auto": "Привет как дела")

    class Backend:
        def __init__(self, spool_dir: str) -> None:
            self.spool_dir = Path(spool_dir)

        def render(self, request):
            target = self.spool_dir / "reply.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF")
            return SimpleNamespace(accepted=True, output_path=str(target), message="ok")

    class Player:
        def play(self, path, endpoint) -> None:
            assert endpoint == out

    monkeypatch.setattr(subject, "WindowsSapiBackend", Backend)
    monkeypatch.setattr(subject, "NativeWasapiPlayer", Player)
    result = subject.run_conversational_audio_test()
    assert result.ok
    assert all(result.stages.values())
