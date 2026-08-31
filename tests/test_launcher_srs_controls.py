from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_launcher_field_fixed import FieldFixedAudioLauncher
from orion.launcher_cloud_voice_sections import (
    SRS_CONNECT_INSTRUCTION,
    CloudVoiceConfig,
    CloudVoiceConfigStore,
    LauncherCloudVoiceSectionsMixin,
    format_live_golden_status,
    format_orion_srs_status,
    format_srs_process_status,
    format_test_evidence_status,
)
from orion.srs_process_control import (
    SrsProcessKind,
    SrsProcessState,
    SrsProcessStatus,
    launcher_srs_offline_smoke,
)
from orion.windows_credentials import MemoryCredentialBackend, VoiceCredentialStore


def test_transport_default_and_supported_payload_matrix() -> None:
    qwen = CloudVoiceConfig(cloud_provider="qwen_realtime")
    yandex = CloudVoiceConfig(cloud_provider="yandex", yandex_folder_id="folder")
    yandex_srs = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        yandex_folder_id="folder",
        srs_host="radio.local",
        srs_port=5002,
    )

    assert qwen.voice_transport == "direct"
    assert LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        qwen, "qwen-key", "yandex-key"
    )["transport"] == "direct"
    assert LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        yandex, "qwen-key", "yandex-key"
    )["transport"] == "direct"
    payload = LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        yandex_srs,
        "qwen-key",
        "yandex-key",
        "eam-memory-only",
    )
    assert payload["provider"] == "yandex" and payload["transport"] == "srs"
    assert payload["radio_stt_provider"] == "yandex_realtime"
    assert payload["tts_output_mode"] == "speechkit_rest"
    assert payload["srs"] == {
        "host": "radio.local",
        "port": 5002,
        "eam_password": "eam-memory-only",
    }


def test_qwen_srs_is_rejected_without_fallback() -> None:
    config = CloudVoiceConfig(cloud_provider="qwen_realtime", voice_transport="srs")
    with pytest.raises(ValueError, match=r"Qwen \+ SRS"):
        LauncherCloudVoiceSectionsMixin._realtime_start_payload(
            config,
            "qwen-key",
            "yandex-key",
            "eam",
        )


def test_eam_password_uses_protected_store_and_never_enters_ordinary_config(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        srs_server_path=r"C:\SRS\Server\SRS-Server.exe",
        srs_client_path=r"C:\SRS\Client\SR-ClientRadio.exe",
    )
    credentials = VoiceCredentialStore(MemoryCredentialBackend())
    credentials.save_all(qwen_api_key="", yandex_api_key="", srs_eam_password="eam-never-persist")
    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    launcher._voice_credential_store = credentials
    store.save(config)
    raw = store.path.read_text(encoding="utf-8")

    assert store.load() == config
    assert launcher._current_srs_eam_password() == "eam-never-persist"
    assert "eam-never-persist" not in raw
    assert "password" not in raw.casefold()
    assert "eam-never-persist" not in repr(config)


def test_hardware_payload_uses_selected_yandex_srs_configuration_and_saved_credentials(tmp_path) -> None:  # noqa: ANN001
    CloudVoiceConfigStore(tmp_path).save(
        CloudVoiceConfig(
            cloud_provider="yandex",
            voice_transport="srs",
            yandex_folder_id="folder",
            srs_host="radio.local",
            srs_port=5002,
        )
    )
    credentials = VoiceCredentialStore(MemoryCredentialBackend())
    credentials.save_all(
        qwen_api_key="qwen-secret",
        yandex_api_key="yandex-secret",
        srs_eam_password="eam-secret",
    )
    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    launcher.runtime_dir = tmp_path
    launcher._voice_credential_store = credentials

    assert launcher._hardware_start_payload() == {
        "provider": "yandex",
        "transport": "srs",
        "api_key": "yandex-secret",
        "folder_id": "folder",
        "radio_stt_provider": "yandex_realtime",
        "tts_output_mode": "speechkit_rest",
        "srs": {"host": "radio.local", "port": 5002, "eam_password": "eam-secret"},
    }


def test_speechkit_v3_radio_stt_selection_is_explicit_and_reuses_yandex_credential() -> None:
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        radio_stt_provider="speechkit_v3",
        yandex_folder_id="folder",
        srs_host="radio.local",
    )

    payload = LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        config,
        "unused-qwen",
        "same-yandex-key",
        "eam-memory-only",
    )

    assert payload["api_key"] == "same-yandex-key"
    assert payload["radio_stt_provider"] == "speechkit_v3"
    assert "speechkit_api_key" not in payload


def test_experimental_streaming_tts_selector_is_explicit_and_persisted_in_payload() -> None:
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        tts_output_mode="speechkit_v3_streaming",
        yandex_folder_id="folder",
        srs_host="radio.local",
    )
    payload = LauncherCloudVoiceSectionsMixin._realtime_start_payload(
        config,
        "unused-qwen",
        "same-yandex-key",
        "eam-memory-only",
    )
    assert payload["tts_output_mode"] == "speechkit_v3_streaming"


def test_unknown_tts_output_mode_is_rejected_without_fallback() -> None:
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        tts_output_mode="unknown",
        yandex_folder_id="folder",
    )
    with pytest.raises(ValueError, match="Unsupported SRS TTS output mode"):
        LauncherCloudVoiceSectionsMixin._realtime_start_payload(
            config,
            "unused-qwen",
            "yandex-key",
            "eam-memory-only",
        )


def test_official_process_and_orion_radio_statuses_cannot_be_confused() -> None:
    client = SrsProcessStatus(
        SrsProcessKind.CLIENT,
        SrsProcessState.RUNNING,
        executable_path=r"C:\SRS\Client\SR-ClientRadio.exe",
        pid=42,
    )
    assert format_srs_process_status(client).startswith("SRS CLIENT: RUNNING")
    assert format_orion_srs_status({"transport": "srs", "state": "stopped", "phase": "idle"}) == (
        "ORION SRS: NOT CONNECTED"
    )
    assert format_orion_srs_status(
        {"transport": "srs", "state": "starting", "phase": "registering_radio"}
    ) == (
        "ORION SRS: REGISTERING RADIO"
    )
    assert format_orion_srs_status(
        {"transport": "srs", "state": "starting", "phase": "registering_udp"}
    ) == (
        "ORION SRS: REGISTERING UDP"
    )
    assert format_orion_srs_status(
        {"transport": "srs", "state": "streaming", "phase": "listening"}
    ) == (
        "ORION SRS: READY"
    )
    assert format_orion_srs_status(
        {
            "transport": "srs",
            "state": "streaming",
            "phase": "listening",
            "message": "SpeechKit v3 SRS voice is running | SRS TX STATE: READY",
        }
    ) == "ORION SRS: READY | SRS TX STATE: READY"
    assert format_orion_srs_status(
        {"transport": "direct", "state": "streaming", "phase": "listening"}
    ) == "ORION SRS: NOT CONNECTED"


def test_launcher_ui_contains_ordered_commands_and_manual_connect_instruction() -> None:
    source = Path(LauncherCloudVoiceSectionsMixin.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[1] / source).read_text(encoding="utf-8")
    assert text.index("START SRS SERVER") < text.index("START SRS CLIENT")
    assert SRS_CONNECT_INSTRUCTION in text
    assert "AI SESSION TOGGLE" in text
    assert "QWEN SESSION TOGGLE" not in text
    assert "START LIVE" in text and "STOP LIVE" in text
    assert text.index("START LIVE") < text.index("START TEST SESSION")
    assert "STOP & EXPORT TEST SESSION" in text
    assert "Include SpeechKit STT input WAV in Test Evidence" in text
    assert "SpeechKit v3 External EOU" in text
    assert "Yandex Realtime (legacy)" in text
    assert "OPEN EXPORT FOLDER" in text
    assert "CLEAR SAVED CREDENTIALS" in text
    for forbidden_control in (
        "RADIO 1 FREQUENCY",
        "RADIO 2",
        "SRS AUDIO DEVICE",
        "SRS PTT",
        "ENCRYPTION CONTROL",
    ):
        assert forbidden_control not in text


def test_launcher_test_session_uses_active_core_provider_transport_and_core_endpoints() -> None:
    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((path, method, payload))
        if path.endswith("/status") and path.startswith("/v1/realtime/test-evidence"):
            return {"active": False}
        if path == "/v1/realtime/live/status":
            return {"state": "streaming", "provider": "yandex", "transport": "srs"}
        if path.endswith("/start"):
            return {"active": True, "provider": "yandex", "transport": "srs"}
        if path.endswith("/stop-export"):
            return {"active": False, "export_path": r"C:\evidence\session.zip"}
        raise AssertionError(path)

    launcher._realtime_core_json = request
    started = launcher._start_test_evidence(
        CloudVoiceConfig(tts_output_mode="speechkit_v3_streaming"),
        True,
    )
    stopped = launcher._stop_test_evidence()
    assert started["active"] is True
    assert stopped["export_path"] == r"C:\evidence\session.zip"
    assert calls == [
        ("/v1/realtime/test-evidence/status", "GET", None),
        ("/v1/realtime/live/status", "GET", None),
        (
            "/v1/realtime/test-evidence/start",
            "POST",
            {
                "provider": "yandex",
                "transport": "srs",
                "capture_speechkit_stt_input_audio": True,
                "configured_tts_output_mode": "speechkit_v3_streaming",
            },
        ),
        ("/v1/realtime/test-evidence/stop-export", "POST", None),
    ]


def test_launcher_duplicate_start_and_status_refresh_never_create_another_recorder() -> None:
    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    calls: list[str] = []

    def request(
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del method, payload
        calls.append(path)
        return {
            "active": True,
            "provider": "yandex",
            "transport": "srs",
            "event_count": 7,
        }

    launcher._realtime_core_json = request
    refreshed = launcher._test_evidence_status()
    duplicate = launcher._start_test_evidence(
        CloudVoiceConfig(cloud_provider="qwen_realtime", voice_transport="direct")
    )
    assert refreshed["active"] is True
    assert duplicate["already_active"] is True
    assert calls == [
        "/v1/realtime/test-evidence/status",
        "/v1/realtime/test-evidence/status",
    ]
    assert format_test_evidence_status(refreshed) == (
        "Test Session: RECORDING — YANDEX / SRS | events=7"
    )
    assert format_test_evidence_status(
        {**refreshed, "speechkit_stt_input_capture_enabled": True}
    ).endswith("| STT WAV=ON")


def test_voice_and_tray_shutdown_do_not_own_external_srs_processes() -> None:
    events: list[str] = []
    launcher = cast(Any, object.__new__(FieldFixedAudioLauncher))
    launcher._really_exiting = False
    launcher._tray = SimpleNamespace(stop=lambda: events.append("tray_stop"))
    launcher._stop_realtime_before_exit = lambda: events.append("realtime_stop")
    launcher.core = SimpleNamespace(
        owns_process=True,
        managed_pid=5151,
        record_lifecycle=lambda event, **fields: events.append(event),
        shutdown=lambda: events.append("core_shutdown"),
    )
    launcher.root = SimpleNamespace(destroy=lambda: events.append("root_destroy"))
    launcher._srs_process_controller = SimpleNamespace(
        terminate=lambda: events.append("forbidden_srs_terminate")
    )

    FieldFixedAudioLauncher.exit_application(launcher)

    assert events == [
        "explicit_tray_exit_requested",
        "realtime_stop",
        "core_shutdown",
        "tray_stop",
        "launcher_exit",
        "root_destroy",
    ]

    tray_launcher = cast(Any, object.__new__(WindowsOrionDesktopLauncher))
    tray_launcher._really_exiting = False
    tray_launcher.config = SimpleNamespace(minimize_to_tray=True)
    tray_launcher._tray = SimpleNamespace(start=lambda: events.append("tray_start"))
    tray_launcher.root = SimpleNamespace(withdraw=lambda: events.append("withdraw"))
    tray_launcher.core = SimpleNamespace(owns_process=True)
    tray_launcher._srs_process_controller = launcher._srs_process_controller
    WindowsOrionDesktopLauncher.close(tray_launcher)
    assert events[-2:] == ["tray_start", "withdraw"]
    assert "forbidden_srs_terminate" not in events


def test_launcher_frozen_smoke_has_no_side_effects() -> None:
    result = launcher_srs_offline_smoke()
    assert result == {
        "ok": True,
        "candidate_count_without_environment": 0,
        "external_process_started": False,
        "network_used": False,
        "audio_devices_opened": False,
    }


def test_live_golden_status_formatter_exposes_case_prompt_and_progress() -> None:
    text = format_live_golden_status(
        {
            "state": "waiting_input",
            "message": "Speak the displayed case through the official SRS Client",
            "case_number": 1,
            "total_cases": 8,
            "next_prompt": "Добрый день! Разрешите взлёт.",
        }
    )
    assert "WAITING_INPUT [1/8]" in text
    assert "SAY: Добрый день! Разрешите взлёт." in text
