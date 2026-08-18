from __future__ import annotations

from orion.launcher_cloud_voice_sections import CloudVoiceConfig, CloudVoiceConfigStore


def test_cloud_voice_config_round_trip_contains_only_non_secret_settings(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    config = CloudVoiceConfig(
        voice_backend="cloud_realtime",
        cloud_provider="qwen_realtime",
        fallback_backend="local_whisper",
        qwen_region="singapore",
        qwen_workspace_id="workspace-123",
        qwen_model="qwen3.5-omni-flash-realtime",
    )

    store.save(config)
    raw = store.path.read_text(encoding="utf-8")
    restored = store.load()

    assert restored == config
    assert "api_key" not in raw.casefold()
    assert "bearer" not in raw.casefold()


def test_cloud_voice_config_invalid_json_falls_back_to_local_whisper(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    store.path.write_text("{broken", encoding="utf-8")

    config = store.load()

    assert config.voice_backend == "local_whisper"
    assert config.fallback_backend == "local_whisper"
    assert config.cloud_provider == "qwen_realtime"
