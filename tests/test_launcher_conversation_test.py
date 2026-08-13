from types import SimpleNamespace

import orion.launcher_conversation_test as subject


class Harness(subject.LauncherConversationTestMixin):
    def __init__(self, tmp_path, responder=None) -> None:
        self.root = object()
        self.runtime_dir = tmp_path
        self.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
        self._responder = responder

    def _conversation_core_json(self):
        assert self._responder is not None
        return self._responder()


def _single_log(tmp_path):
    logs = list((tmp_path / "test-logs").glob("orion-test-*.log"))
    assert len(logs) == 1
    return logs[0], logs[0].read_text(encoding="utf-8")


def test_conversation_result_success(monkeypatch, tmp_path) -> None:
    shown = []
    monkeypatch.setattr(subject.messagebox, "showinfo", lambda title, text, parent=None: shown.append((title, text)))
    launcher = Harness(
        tmp_path,
        lambda: {
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
    _, text = _single_log(tmp_path)
    assert "START test=conversation" in text
    assert "REQUEST method=POST" in text
    assert "timeout_s=20.0" in text
    assert "RECOGNIZED" in text
    assert "END status=PASS" in text


def test_conversation_result_warning_is_logged(monkeypatch, tmp_path) -> None:
    shown = []
    monkeypatch.setattr(subject.messagebox, "showwarning", lambda title, text, parent=None: shown.append(text))
    launcher = Harness(tmp_path, lambda: {"ok": False, "stages": {}, "message": "not ready"})
    launcher._run_conversational_audio_test()
    assert shown and "not ready" in shown[0]
    _, text = _single_log(tmp_path)
    assert "RESPONSE" in text
    assert "END status=FAIL" in text


def test_conversation_result_core_error_is_logged(monkeypatch, tmp_path) -> None:
    errors = []
    monkeypatch.setattr(subject.messagebox, "showerror", lambda title, text, parent=None: errors.append(text))

    def fail():
        raise RuntimeError("core down")

    launcher = Harness(tmp_path, fail)
    launcher._run_conversational_audio_test()
    assert errors
    assert "core down" in errors[0]
    _, text = _single_log(tmp_path)
    assert "ERROR" in text
    assert "core down" in text
    assert "END status=FAIL" in text


def test_physical_test_unresolved_endpoint_is_logged(monkeypatch, tmp_path) -> None:
    warnings = []
    monkeypatch.setattr(subject.messagebox, "showwarning", lambda title, text, parent=None: warnings.append(text))
    launcher = Harness(tmp_path)
    launcher._run_physical_audio_test("input", None)
    assert warnings and "No active input endpoint" in warnings[0]
    _, text = _single_log(tmp_path)
    assert "START test=physical-input" in text
    assert "ERROR endpoint=unresolved" in text
    assert "END status=FAIL" in text


def test_physical_input_success_is_logged(monkeypatch, tmp_path) -> None:
    shown = []
    monkeypatch.setattr(subject.messagebox, "showinfo", lambda title, text, parent=None: shown.append(text))
    result = SimpleNamespace(ok=True, message="input ok")
    monkeypatch.setattr(subject.AudioHardwareTester, "test_input", lambda self, endpoint: result)
    launcher = Harness(tmp_path)
    launcher._run_physical_audio_test("input", {"device_id": "mic-1", "name": "Mic", "direction": "input", "is_default": False})
    assert shown and "input ok" in shown[0]
    _, text = _single_log(tmp_path)
    assert "ENDPOINT" in text
    assert "RESULT" in text
    assert "END status=PASS" in text


def test_physical_output_failure_and_exception_are_logged(monkeypatch, tmp_path) -> None:
    warnings = []
    errors = []
    monkeypatch.setattr(subject.messagebox, "showwarning", lambda title, text, parent=None: warnings.append(text))
    monkeypatch.setattr(subject.messagebox, "showerror", lambda title, text, parent=None: errors.append(text))
    launcher = Harness(tmp_path)
    endpoint = {"device_id": "out-1", "name": "Speakers", "direction": "output", "is_default": False}

    monkeypatch.setattr(subject.AudioHardwareTester, "test_output", lambda self, ep: SimpleNamespace(ok=False, message="bad rate"))
    launcher._run_physical_audio_test("output", endpoint)
    assert warnings and "bad rate" in warnings[0]

    monkeypatch.setattr(subject.AudioHardwareTester, "test_output", lambda self, ep: (_ for _ in ()).throw(RuntimeError("boom")))
    launcher._run_physical_audio_test("output", endpoint)
    assert errors and "boom" in errors[0]

    logs = list((tmp_path / "test-logs").glob("orion-test-*.log"))
    assert len(logs) == 2
    texts = [path.read_text(encoding="utf-8") for path in logs]
    assert any("RESULT" in text and "END status=FAIL" in text for text in texts)
    assert any("ERROR" in text and "RuntimeError: boom" in text for text in texts)
