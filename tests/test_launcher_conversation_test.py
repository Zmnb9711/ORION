from types import SimpleNamespace

import orion.launcher_conversation_test as subject


class Harness(subject.LauncherConversationTestMixin):
    def __init__(self, tmp_path, responder) -> None:
        self.root = object()
        self.runtime_dir = tmp_path
        self.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
        self._responder = responder

    def _core_json(self, path, method="GET"):
        return self._responder(path, method)


def test_conversation_result_success(monkeypatch, tmp_path) -> None:
    shown = []
    monkeypatch.setattr(subject.messagebox, "showinfo", lambda title, text, parent=None: shown.append((title, text)))
    launcher = Harness(
        tmp_path,
        lambda path, method: {
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
    launcher._run_conversational_audio_test()
    assert shown
    assert "Привет, как дела?" in shown[0][1]
    assert "PASS — Response played" in shown[0][1]
    logs = list((tmp_path / "test-logs").glob("orion-test-*.log"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "START test=conversation" in text
    assert "END status=PASS" in text


def test_conversation_result_core_error_is_logged(monkeypatch, tmp_path) -> None:
    errors = []
    monkeypatch.setattr(subject.messagebox, "showerror", lambda title, text, parent=None: errors.append(text))

    def fail(path, method):
        raise RuntimeError("core down")

    launcher = Harness(tmp_path, fail)
    launcher._run_conversational_audio_test()
    assert errors
    assert "core down" in errors[0]
    logs = list((tmp_path / "test-logs").glob("orion-test-*.log"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "ERROR" in text
    assert "core down" in text
    assert "END status=FAIL" in text
