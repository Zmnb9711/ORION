from __future__ import annotations

from orion.launcher_cloud_voice_sections import CloudVoiceConfig, CloudVoiceConfigStore, LauncherCloudVoiceSectionsMixin
from orion.yandex_live_diagnostics import YandexLiveDiagnostics


def test_folder_id_and_provider_persist_without_either_api_key(tmp_path) -> None:  # noqa: ANN001
    store = CloudVoiceConfigStore(tmp_path)
    config = CloudVoiceConfig(
        cloud_provider="yandex",
        qwen_region="beijing",
        qwen_workspace_id="qwen-workspace",
        qwen_model="qwen-model",
        yandex_folder_id="yandex-folder",
    )
    store.save(config)
    raw = store.path.read_text(encoding="utf-8")
    assert store.load() == config
    assert "yandex-folder" in raw
    assert "api_key" not in raw.casefold()
    assert "authorization" not in raw.casefold()


def test_provider_payloads_keep_keys_and_fields_separate() -> None:
    yandex = CloudVoiceConfig(cloud_provider="yandex", yandex_folder_id="folder")
    qwen = CloudVoiceConfig(qwen_workspace_id="workspace")
    assert LauncherCloudVoiceSectionsMixin._realtime_start_payload(yandex, "qwen-key", "yandex-key") == {
        "provider": "yandex", "transport": "direct", "api_key": "yandex-key", "folder_id": "folder"
    }
    qwen_payload = LauncherCloudVoiceSectionsMixin._realtime_start_payload(qwen, "qwen-key", "yandex-key")
    assert qwen_payload["provider"] == "qwen" and qwen_payload["transport"] == "direct"
    assert qwen_payload["api_key"] == "qwen-key"
    assert "folder_id" not in qwen_payload


def test_yandex_diagnostics_drop_credentials_and_audio_payloads(tmp_path) -> None:  # noqa: ANN001
    diagnostics = YandexLiveDiagnostics("session", "super-secret", tmp_path)
    diagnostics.record(
        "provider_event",
        api_key="super-secret",
        authorization="Api-Key super-secret",
        pcm=b"raw-audio",
        base64="c2VjcmV0",
        latitude=31.505,
        longitude=65.847,
        error="request failed for super-secret",
        byte_count=1764,
        speechkit_pcm_bytes_before_eou=1280,
    )
    text = diagnostics.path.read_text(encoding="utf-8")
    assert "super-secret" not in text
    assert "raw-audio" not in text
    assert "c2VjcmV0" not in text
    assert "31.505" not in text
    assert "65.847" not in text
    assert "[REDACTED]" in text
    assert '"byte_count": 1764' in text
    assert '"speechkit_pcm_bytes_before_eou": 1280' in text
