from types import SimpleNamespace

import orion.desktop_launcher_conversation as subject


def test_conversational_launcher_routes_audio_style_core_json(monkeypatch) -> None:
    launcher = object.__new__(subject.ConversationalAudioRuntimeLauncher)
    launcher.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
    calls = []

    def audio_call(self, path, *, method="GET", payload=None):
        calls.append(("audio", path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(subject.LauncherAudioSectionsMixin, "_core_json", audio_call)

    result = launcher._core_json(
        "/v1/windows-audio/selection",
        method="PUT",
        payload={"input_device_id": "default", "output_device_id": "default"},
    )

    assert result == {"ok": True}
    assert calls == [
        (
            "audio",
            "/v1/windows-audio/selection",
            "PUT",
            {"input_device_id": "default", "output_device_id": "default"},
        )
    ]


def test_conversational_launcher_routes_stt_style_core_json(monkeypatch) -> None:
    launcher = object.__new__(subject.ConversationalAudioRuntimeLauncher)
    launcher.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
    calls = []

    def conversation_call(self, method, path, *, timeout=5.0):
        calls.append(("conversation", method, path, timeout))
        return {"ready": False}

    monkeypatch.setattr(subject.LauncherConversationTestMixin, "_core_json", conversation_call)

    result = launcher._core_json("GET", "/v1/windows-audio/stt/status", timeout=3.0)

    assert result == {"ready": False}
    assert calls == [("conversation", "GET", "/v1/windows-audio/stt/status", 3.0)]


def test_conversational_launcher_core_json_rejects_ambiguous_calls() -> None:
    launcher = object.__new__(subject.ConversationalAudioRuntimeLauncher)
    launcher.core = SimpleNamespace(base_url="http://127.0.0.1:8000")

    try:
        launcher._core_json()
    except TypeError as exc:
        assert "expects path or method, path" in str(exc)
    else:
        raise AssertionError("missing TypeError")
