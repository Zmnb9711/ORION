from types import SimpleNamespace

import orion.launcher_conversation_test as subject


class FakeWidget:
    def __init__(self) -> None:
        self.values = {}
        self.manager = "pack"
        self.pack_calls = []
        self.pack_forget_calls = 0

    def configure(self, **kwargs) -> None:
        self.values.update(kwargs)

    def winfo_manager(self) -> str:
        return self.manager

    def pack(self, **kwargs) -> None:
        self.manager = "pack"
        self.pack_calls.append(kwargs)

    def pack_forget(self) -> None:
        self.manager = ""
        self.pack_forget_calls += 1


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls = []

    def after(self, delay, callback) -> None:
        self.after_calls.append((delay, callback))


class Harness(subject.LauncherConversationTestMixin):
    def __init__(self, tmp_path, responder=None, *, stt_status=None) -> None:
        self.root = FakeRoot()
        self.runtime_dir = tmp_path
        self.core = SimpleNamespace(base_url="http://127.0.0.1:8000")
        self._responder = responder
        self._test_stt_status = stt_status or {
            "ready": True,
            "running": False,
            "stage": "ready",
            "percent": 100.0,
        }

    def _conversation_core_json(self):
        assert self._responder is not None
        return self._responder()

    def _core_json(self, path, *, method="GET", payload=None, timeout=5.0):
        if path == "/v1/windows-audio/stt/status":
            return dict(self._test_stt_status)
        if path == "/v1/windows-audio/stt/prepare":
            return {
                "ready": False,
                "running": True,
                "stage": "starting",
                "percent": 0.0,
            }
        return super()._core_json(path, method=method, payload=payload, timeout=timeout)


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
    assert "timeout_s=120.0" in text
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


def test_conversation_is_blocked_until_stt_ready(tmp_path) -> None:
    launcher = Harness(
        tmp_path,
        lambda: {"ok": True},
        stt_status={"ready": False, "running": False, "stage": "not_installed", "percent": 0.0},
    )
    launcher._stt_status_label = FakeWidget()
    launcher._stt_progress = FakeWidget()
    launcher._stt_prepare_button = FakeWidget()
    launcher._conversation_button = FakeWidget()
    launcher._run_conversational_audio_test()
    _, text = _single_log(tmp_path)
    assert "stt_not_ready" in text
    assert "END status=FAIL" in text
    assert launcher._conversation_button.values["state"] == "disabled"
    assert launcher._stt_prepare_button.values["state"] == "normal"


def test_stt_status_text_reports_model_download_progress(tmp_path) -> None:
    launcher = Harness(tmp_path)
    text = launcher._stt_status_text(
        {
            "ready": False,
            "running": True,
            "stage": "model",
            "percent": 37.5,
            "downloaded_bytes": 512 * 1024 * 1024,
            "total_bytes": 1536 * 1024 * 1024,
        }
    )
    assert "Whisper medium" in text
    assert "37.5%" in text
    assert "512/1536 MiB" in text
    assert "READY" in launcher._stt_status_text({"ready": True})
    assert "FAILED" in launcher._stt_status_text({"ready": False, "error": "checksum"})


def test_apply_stt_status_enables_conversation_only_when_ready(tmp_path) -> None:
    launcher = Harness(tmp_path)
    launcher._stt_status_label = FakeWidget()
    launcher._stt_progress = FakeWidget()
    launcher._stt_prepare_button = FakeWidget()
    launcher._conversation_button = FakeWidget()

    launcher._apply_stt_status({"ready": False, "running": True, "stage": "model", "percent": 48.0})
    assert launcher._stt_progress.values["value"] == 48.0
    assert launcher._stt_progress.manager == "pack"
    assert launcher._stt_prepare_button.values["state"] == "disabled"
    assert launcher._conversation_button.values["state"] == "disabled"

    launcher._apply_stt_status({"ready": True, "running": False, "stage": "ready", "percent": 100.0})
    assert launcher._stt_prepare_button.values["state"] == "disabled"
    assert launcher._conversation_button.values["state"] == "normal"
    assert launcher._stt_progress.manager == ""
    assert launcher._stt_progress.pack_forget_calls == 1


def test_stt_progress_reappears_for_later_repair_and_hides_on_failure(tmp_path) -> None:
    launcher = Harness(tmp_path)
    launcher._stt_status_label = FakeWidget()
    launcher._stt_progress = FakeWidget()
    launcher._stt_prepare_button = FakeWidget()
    launcher._conversation_button = FakeWidget()

    launcher._apply_stt_status({"ready": True, "running": False, "stage": "ready", "percent": 100.0})
    assert launcher._stt_progress.manager == ""

    launcher._apply_stt_status({"ready": False, "running": True, "stage": "runtime", "percent": 12.0})
    assert launcher._stt_progress.manager == "pack"
    assert launcher._stt_progress.pack_calls

    launcher._apply_stt_status({"ready": False, "running": False, "stage": "failed", "error": "checksum"})
    assert launcher._stt_progress.manager == ""
    assert launcher._stt_prepare_button.values["state"] == "normal"
    assert launcher._conversation_button.values["state"] == "disabled"


def test_prepare_stt_starts_background_poll_and_logs(tmp_path) -> None:
    launcher = Harness(tmp_path)
    launcher._stt_status_label = FakeWidget()
    launcher._stt_progress = FakeWidget()
    launcher._stt_prepare_button = FakeWidget()
    launcher._conversation_button = FakeWidget()
    launcher._prepare_speech_recognition()
    _, text = _single_log(tmp_path)
    assert "START test=stt-prepare" in text
    assert "/v1/windows-audio/stt/prepare" in text
    assert "STARTED stage=starting running=True" in text
    assert launcher.root.after_calls
    assert launcher._stt_prepare_button.values["state"] == "disabled"


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
