from __future__ import annotations

from orion.launcher_cloud_voice_sections import CloudVoiceConfig, CloudVoiceConfigStore


def test_cloud_voice_config_round_trip_contains_only_non_secret_settings(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        voice_transport="srs",
        qwen_region="singapore",
        qwen_workspace_id="workspace-123",
        qwen_model="qwen3.5-omni-flash-realtime",
        yandex_folder_id="folder-123",
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
