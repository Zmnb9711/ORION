from __future__ import annotations

import os
from typing import Any, cast

import pytest

from orion import launcher_main
from orion.launcher_cloud_voice_sections import LauncherCloudVoiceSectionsMixin
from orion.qwen_live_audio_core import QwenLiveStartRequest
from orion.qwen_realtime_provider import QwenRealtimeConfig
from orion.realtime_tool_api import YandexConnectionTestRequest
from orion.windows_credentials import (
    CredentialStoreError,
    MemoryCredentialBackend,
    VoiceCredential,
    VoiceCredentialStore,
    WindowsCredentialBackend,
    frozen_credential_store_smoke,
)
from orion.yandex_live_audio_core import YandexLiveStartRequest
from orion.yandex_realtime_provider import YandexRealtimeConfig


def _saved_store(backend: MemoryCredentialBackend) -> VoiceCredentialStore:
    store = VoiceCredentialStore(backend)
    store.save_all(
        qwen_api_key="qwen-secret",
        yandex_api_key="yandex-secret",
        srs_eam_password="eam-secret",
    )
    return store


def test_voice_credentials_survive_simulated_launcher_restart_and_clear() -> None:
    backend = MemoryCredentialBackend()
    _saved_store(backend)
    restarted = VoiceCredentialStore(backend)

    assert restarted.load(VoiceCredential.QWEN_API_KEY) == "qwen-secret"
    assert restarted.load(VoiceCredential.YANDEX_API_KEY) == "yandex-secret"
    assert restarted.load(VoiceCredential.SRS_EAM_PASSWORD) == "eam-secret"

    restarted.clear_all()
    for credential in VoiceCredential:
        assert restarted.load(credential) == ""


def test_launcher_loads_each_saved_credential_without_placing_it_in_config() -> None:
    backend = MemoryCredentialBackend()
    store = _saved_store(backend)
    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    launcher._voice_credential_store = store

    assert launcher._current_qwen_api_key() == "qwen-secret"
    assert launcher._current_yandex_api_key() == "yandex-secret"
    assert launcher._current_srs_eam_password() == "eam-secret"


def test_secret_models_and_credential_store_repr_are_redacted() -> None:
    secrets = ("qwen-secret", "yandex-secret")
    values = (
        QwenRealtimeConfig(api_key=secrets[0], workspace_id="workspace"),
        YandexRealtimeConfig(api_key=secrets[1], folder_id="folder"),
        QwenLiveStartRequest(api_key=secrets[0], workspace_id="workspace"),
        YandexLiveStartRequest(api_key=secrets[1], folder_id="folder"),
        YandexConnectionTestRequest(api_key=secrets[1], folder_id="folder"),
    )
    store = _saved_store(MemoryCredentialBackend())

    rendered = "\n".join(repr(value) for value in (*values, store))
    assert all(secret not in rendered for secret in secrets)


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager is Windows-only")
def test_native_windows_credential_manager_ephemeral_round_trip() -> None:
    result = frozen_credential_store_smoke()
    assert result == {
        "ok": True,
        "credential_persisted_after_smoke": False,
        "secret_exposed": False,
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager is Windows-only")
def test_native_credential_error_does_not_echo_secret() -> None:
    secret = "sensitive-value-" * 300
    with pytest.raises(CredentialStoreError) as captured:
        WindowsCredentialBackend().write("ORION/Voice/TestTooLarge", secret)
    assert secret not in str(captured.value)


def test_uninstall_cli_clears_only_orion_voice_credentials(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []
    monkeypatch.setattr(
        "orion.windows_credentials.clear_saved_voice_credentials",
        lambda: calls.append("voice_credentials_cleared"),
    )

    assert launcher_main.main(["--clear-voice-credentials"]) == 0
    assert calls == ["voice_credentials_cleared"]
