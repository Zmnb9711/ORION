from __future__ import annotations

import inspect
from tkinter import Tk
from tkinter import ttk

import pytest

from orion.launcher_cloud_voice_sections import (
    CloudVoiceConfig,
    CloudVoiceConfigStore,
    LauncherCloudVoiceSectionsMixin,
    apply_informational_backend_selection,
    informational_backend_display_value,
)
from orion.windows_credentials import (
    MemoryCredentialBackend,
    VoiceCredential,
    VoiceCredentialStore,
)


def test_cloud_voice_config_round_trip_contains_only_non_secret_settings(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        qwen_region="singapore",
        qwen_workspace_id="workspace-123",
        qwen_model="qwen3.5-omni-flash-realtime",
        yandex_folder_id="folder-123",
        radio_stt_provider="speechkit_v3",
        tts_output_mode="speechkit_v3_streaming",
        informational_backend="REALTIME_D75_CANDIDATE",
        srs_host="radio.local",
        srs_port=5003,
        srs_server_path=r"C:\SRS\Server\SRS-Server.exe",
        srs_client_path=r"C:\SRS\Client\SR-ClientRadio.exe",
    )

    store.save(config)
    raw = store.path.read_text(encoding="utf-8")
    restored = store.load()

    assert restored == config
    assert "api_key" not in raw.casefold()
    assert "bearer" not in raw.casefold()


def test_cloud_voice_config_invalid_json_falls_back_to_qwen_defaults(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    store.path.write_text("{broken", encoding="utf-8")

    config = store.load()

    assert config.cloud_provider == "qwen_realtime"


def test_legacy_backend_fields_are_ignored(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    store.path.write_text(
        '{"voice_backend":"local_whisper","fallback_backend":"local_whisper","qwen_region":"beijing"}',
        encoding="utf-8",
    )

    config = store.load()

    assert config.cloud_provider == "qwen_realtime"
    assert config.qwen_region == "beijing"
    assert not hasattr(config, "voice_backend")
    assert not hasattr(config, "fallback_backend")


def test_config_without_radio_selector_migrates_to_explicit_legacy_default(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    store.path.write_text(
        '{"cloud_provider":"yandex","voice_transport":"srs"}',
        encoding="utf-8",
    )

    config = store.load()

    assert config.radio_stt_provider == "yandex_realtime"
    assert config.tts_output_mode == "speechkit_rest"
    assert config.informational_backend == "CURRENT_QWEN"


@pytest.mark.parametrize(
    ("stored", "displayed"),
    [
        (None, "Current / Qwen"),
        ("CURRENT_QWEN", "Current / Qwen"),
        ("REALTIME_D75_CANDIDATE", "Realtime D75 Candidate"),
        ("UNSUPPORTED_BACKEND", "Current / Qwen"),
    ],
)
def test_informational_backend_display_is_bounded_and_fail_safe(
    stored: str | None,
    displayed: str,
) -> None:
    assert informational_backend_display_value(stored) == displayed


@pytest.mark.parametrize(
    ("displayed", "stored"),
    [
        ("Current / Qwen", "CURRENT_QWEN"),
        ("Realtime D75 Candidate", "REALTIME_D75_CANDIDATE"),
    ],
)
def test_informational_backend_selection_round_trips_through_existing_store(
    tmp_path,  # noqa: ANN001
    displayed: str,
    stored: str,
) -> None:
    store = CloudVoiceConfigStore(tmp_path)
    original = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        qwen_region="beijing",
        qwen_workspace_id="workspace",
        qwen_model="model",
        yandex_folder_id="folder",
        radio_stt_provider="speechkit_v3",
        tts_output_mode="speechkit_v3_streaming",
        srs_host="radio.local",
        srs_port=5003,
        srs_server_path="server.exe",
        srs_client_path="client.exe",
    )

    selected = apply_informational_backend_selection(original, displayed)
    store.save(selected)
    restored = store.load()

    assert restored.informational_backend == stored
    assert restored == selected
    assert restored.cloud_provider == original.cloud_provider
    assert restored.voice_transport == original.voice_transport
    assert restored.radio_stt_provider == original.radio_stt_provider
    assert restored.tts_output_mode == original.tts_output_mode


def test_invalid_stored_informational_backend_loads_as_current_default(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    store.path.write_text(
        '{"cloud_provider":"yandex","voice_transport":"srs",'
        '"informational_backend":"INVALID"}',
        encoding="utf-8",
    )

    restored = store.load()

    assert restored.informational_backend == "CURRENT_QWEN"
    assert restored.cloud_provider == "yandex"
    assert restored.voice_transport == "srs"


def test_backend_config_save_does_not_touch_protected_credentials(tmp_path) -> None:  # noqa: ANN001
    credentials = VoiceCredentialStore(MemoryCredentialBackend())
    credentials.save_all(
        qwen_api_key="qwen-memory-only",
        yandex_api_key="yandex-memory-only",
        srs_eam_password="eam-memory-only",
    )
    before = tuple(credentials.load(item) for item in VoiceCredential)
    store = CloudVoiceConfigStore(tmp_path)

    store.save(
        apply_informational_backend_selection(
            CloudVoiceConfig(),
            "Realtime D75 Candidate",
        )
    )

    assert tuple(credentials.load(item) for item in VoiceCredential) == before
    raw = store.path.read_text(encoding="utf-8")
    assert "memory-only" not in raw


def test_launcher_voice_page_exposes_existing_backend_selector_and_runtime_boundary() -> None:
    source = inspect.getsource(
        LauncherCloudVoiceSectionsMixin._build_informational_backend_selector
    )

    assert "INFORMATIONAL RESPONSE BACKEND" in source
    assert "tuple(INFORMATIONAL_BACKEND_LABELS)" in source
    assert "applies when Live Golden starts" in source
    assert "restart" not in source.casefold()


@pytest.mark.parametrize(
    ("stored", "displayed"),
    [
        ("CURRENT_QWEN", "Current / Qwen"),
        ("REALTIME_D75_CANDIDATE", "Realtime D75 Candidate"),
    ],
)
def test_real_tk_backend_selector_displays_and_selects_both_choices(
    stored: str,
    displayed: str,
) -> None:
    root = Tk()
    root.withdraw()
    try:
        parent = ttk.Frame(root)
        variable = LauncherCloudVoiceSectionsMixin._build_informational_backend_selector(
            parent,
            CloudVoiceConfig(informational_backend=stored),
        )
        widgets = parent.winfo_children()
        combobox = next(widget for widget in widgets if isinstance(widget, ttk.Combobox))

        assert variable.get() == displayed
        assert tuple(combobox.cget("values")) == (
            "Current / Qwen",
            "Realtime D75 Candidate",
        )
        combobox.set("Realtime D75 Candidate")
        assert variable.get() == "Realtime D75 Candidate"
    finally:
        root.destroy()
