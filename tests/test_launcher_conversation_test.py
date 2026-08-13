from types import SimpleNamespace

import orion.launcher_conversation_test as subject


def test_conversation_result_success(monkeypatch) -> None:
    shown = []
    monkeypatch.setattr(subject.messagebox, "showinfo", lambda title, text, parent=None: shown.append((title, text)))
    launcher = SimpleNamespace(
        root=object(),
        _core_json=lambda path, method="GET": {
            "ok": True,
            "recognized_text": "Привет, как дела?",
            "message": "Дела отлично. Связь установлена.",
            "stages": {
                "core_connected": True,
                "input_resolved": True,
                "audio_captured": True,
                "phrase_recognized": True,
                "output_resolved": True,
                "response_played": True,
            },
        },
    )
    subject.LauncherConversationTestMixin._run_conversational_audio_test(launcher)
    assert shown
    assert "Привет, как дела?" in shown[0][1]
    assert "PASS — Response played" in shown[0][1]


def test_conversation_result_core_error(monkeypatch) -> None:
    errors = []
    monkeypatch.setattr(subject.messagebox, "showerror", lambda title, text, parent=None: errors.append(text))
    launcher = SimpleNamespace(root=object(), _core_json=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("core down")))
    subject.LauncherConversationTestMixin._run_conversational_audio_test(launcher)
    assert errors == ["core down"]
