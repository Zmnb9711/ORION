from __future__ import annotations

from types import SimpleNamespace

import orion.launcher_field_ui_fix as field_ui
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


class _Widget:
    created: list["_Widget"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.config = {}
        self.__class__.created.append(self)

    def pack(self, *args, **kwargs):
        return self

    def grid(self, *args, **kwargs):
        return self

    def configure(self, **kwargs):
        self.config.update(kwargs)
        return self


class _Button(_Widget):
    created: list["_Button"] = []


class _Progressbar(_Widget):
    created: list["_Progressbar"] = []


class _Root:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))


class _Core:
    def __init__(self, healthy: bool = True):
        self._healthy = healthy

    def healthy(self):
        return self._healthy


class _Launcher(LauncherFieldUiFixMixin):
    def __init__(self, *, healthy: bool = True, snapshot_error: bool = False):
        self.content = object()
        self.root = _Root()
        self.core = _Core(healthy)
        self.health = None
        self.snapshot_error = snapshot_error
        self.render_count = 0
        self.conversation_runs = 0
        self.physical_runs: list[tuple[str, object]] = []
        self.prepare_runs = 0

    def _render_status_strip(self):
        self.render_count += 1

    def _audio_snapshot(self):
        if self.snapshot_error:
            raise RuntimeError("audio unavailable")
        return (
            [{"device_id": "mic-1", "name": "Microphone"}],
            [{"device_id": "out-1", "name": "Speakers"}],
            {
                "selection": {"input_device_id": "mic-1", "output_device_id": "out-1"},
                "resolved_input": {"device_id": "mic-1", "name": "Microphone"},
                "resolved_output": {"device_id": "out-1", "name": "Speakers"},
            },
        )

    def _selection_text(self, selected, resolved):
        return f"PASS {resolved['name']}" if resolved else f"WARN {selected}"

    def _card(self, *args, **kwargs):
        return _Widget()

    def _prepare_speech_recognition(self):
        self.prepare_runs += 1

    def _poll_stt_status(self):
        return None

    def _run_conversational_audio_test(self):
        self.conversation_runs += 1

    def _run_physical_audio_test(self, direction, endpoint):
        self.physical_runs.append((direction, endpoint))


def _patch_widgets(monkeypatch):
    _Widget.created.clear()
    _Button.created.clear()
    _Progressbar.created.clear()
    for name in ("Frame", "Label"):
        monkeypatch.setattr(field_ui.ttk, name, _Widget)
    monkeypatch.setattr(field_ui.ttk, "Progressbar", _Progressbar)
    monkeypatch.setattr(field_ui.tk, "Frame", _Widget)
    monkeypatch.setattr(field_ui.tk, "Button", _Button)


def test_apply_health_updates_state_without_page_rebuild():
    launcher = _Launcher()
    report = object()
    launcher._apply_health(report)
    assert launcher.health is report
    assert launcher.render_count == 1


def test_action_button_has_visible_text_and_disabled_state(monkeypatch):
    _patch_widgets(monkeypatch)
    enabled = LauncherFieldUiFixMixin._action_button(object(), "START AUDIO TEST", lambda: None, primary=True)
    assert enabled.kwargs["text"] == "START AUDIO TEST"
    assert enabled.kwargs["fg"] == "#031014"
    disabled = LauncherFieldUiFixMixin._action_button(object(), "TEST OUTPUT", lambda: None, enabled=False)
    assert disabled.kwargs["text"] == "TEST OUTPUT"
    assert disabled.config["state"] == "disabled"


def test_page_test_renders_stt_install_and_blocks_conversation_until_ready(monkeypatch):
    _patch_widgets(monkeypatch)
    launcher = _Launcher()
    launcher._page_test()
    texts = [button.kwargs.get("text") for button in _Button.created]
    assert texts == ["DOWNLOAD & INSTALL STT", "START AUDIO TEST", "TEST MICROPHONE", "TEST OUTPUT"]
    assert len(_Progressbar.created) == 1
    assert launcher._stt_progress is _Progressbar.created[0]
    assert launcher._stt_prepare_button.kwargs["text"] == "DOWNLOAD & INSTALL STT"
    assert launcher._conversation_button.config.get("state") == "disabled"
    assert launcher._stt_prepare_button.config.get("state") != "disabled"
    assert launcher.root.after_calls and launcher.root.after_calls[0][0] == 50
    assert _Button.created[2].config.get("state") != "disabled"
    assert _Button.created[3].config.get("state") != "disabled"


def test_page_test_disables_stt_and_audio_actions_when_core_or_api_unavailable(monkeypatch):
    _patch_widgets(monkeypatch)
    launcher = _Launcher(healthy=False)
    launcher._page_test()
    assert [button.config.get("state") for button in _Button.created] == ["disabled", "disabled", "disabled", "disabled"]

    _patch_widgets(monkeypatch)
    launcher = _Launcher(healthy=True, snapshot_error=True)
    launcher._page_test()
    assert launcher._conversation_button.config.get("state") == "disabled"
    assert launcher._stt_prepare_button.config.get("state") != "disabled"
    assert _Button.created[2].config.get("state") == "disabled"
    assert _Button.created[3].config.get("state") == "disabled"
