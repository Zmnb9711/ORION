from __future__ import annotations

from orion.desktop_launcher_conversation import ConversationalAudioRuntimeLauncher
from orion.desktop_launcher_field_fixed import FieldFixedConversationalAudioLauncher


class _Button:
    def __init__(self) -> None:
        self.config: dict[str, object] = {}

    def configure(self, **kwargs: object) -> None:
        self.config.update(kwargs)


def test_field_fixed_stt_ready_restores_active_audio_button(monkeypatch):
    def _base_apply(self, payload):  # noqa: ANN001
        self._conversation_button.configure(state="normal" if payload.get("ready") else "disabled")

    monkeypatch.setattr(ConversationalAudioRuntimeLauncher, "_apply_stt_status", _base_apply)
    launcher = FieldFixedConversationalAudioLauncher.__new__(FieldFixedConversationalAudioLauncher)
    launcher._conversation_button = _Button()

    launcher._apply_stt_status({"ready": True})

    assert launcher._conversation_button.config["state"] == "normal"
    assert launcher._conversation_button.config["bg"] == "#4ac6d7"
    assert launcher._conversation_button.config["cursor"] == "hand2"


def test_field_fixed_stt_not_ready_keeps_audio_button_disabled(monkeypatch):
    def _base_apply(self, payload):  # noqa: ANN001
        self._conversation_button.configure(state="normal" if payload.get("ready") else "disabled")

    monkeypatch.setattr(ConversationalAudioRuntimeLauncher, "_apply_stt_status", _base_apply)
    launcher = FieldFixedConversationalAudioLauncher.__new__(FieldFixedConversationalAudioLauncher)
    launcher._conversation_button = _Button()

    launcher._apply_stt_status({"ready": False})

    assert launcher._conversation_button.config["state"] == "disabled"
    assert launcher._conversation_button.config["bg"] == "#17222b"
    assert launcher._conversation_button.config["cursor"] == "arrow"
