from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from enum import StrEnum
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """A credential operation failed without exposing credential material."""


class VoiceCredential(StrEnum):
    QWEN_API_KEY = "qwen_api_key"
    YANDEX_API_KEY = "yandex_api_key"
    SRS_EAM_PASSWORD = "srs_eam_password"


class CredentialBackend(Protocol):
    def read(self, target: str) -> str | None: ...

    def write(self, target: str, value: str) -> None: ...

    def delete(self, target: str) -> None: ...


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialBackend:
    """Minimal user-scoped wrapper over the native Windows Credential Manager."""

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _MAX_BLOB_BYTES = 5 * 512

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialStoreError("Windows Credential Manager is unavailable on this platform")
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise CredentialStoreError("Windows Credential Manager API is unavailable")
        self._advapi32 = loader("Advapi32.dll", use_last_error=True)
        self._cred_write = self._advapi32.CredWriteW
        self._cred_write.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
        self._cred_write.restype = wintypes.BOOL
        self._cred_read = self._advapi32.CredReadW
        self._cred_read.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CredentialW)),
        ]
        self._cred_read.restype = wintypes.BOOL
        self._cred_delete = self._advapi32.CredDeleteW
        self._cred_delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._cred_delete.restype = wintypes.BOOL
        self._cred_free = self._advapi32.CredFree
        self._cred_free.argtypes = [ctypes.c_void_p]
        self._cred_free.restype = None

    def read(self, target: str) -> str | None:
        pointer = ctypes.POINTER(_CredentialW)()
        if not self._cred_read(
            target,
            self._CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            error = ctypes.get_last_error()
            if error == self._ERROR_NOT_FOUND:
                return None
            raise self._error("read", error)
        try:
            credential = pointer.contents
            if not credential.CredentialBlobSize:
                return ""
            encoded = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            try:
                return encoded.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CredentialStoreError("Credential Manager returned invalid credential data") from exc
        finally:
            self._cred_free(pointer)

    def write(self, target: str, value: str) -> None:
        encoded = value.encode("utf-8")
        if not encoded:
            self.delete(target)
            return
        if len(encoded) > self._MAX_BLOB_BYTES:
            raise CredentialStoreError("Credential exceeds the Windows Credential Manager size limit")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _CredentialW()
        credential.Type = self._CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self._CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "ORION"
        if not self._cred_write(ctypes.byref(credential), 0):
            raise self._error("write", ctypes.get_last_error())

    def delete(self, target: str) -> None:
        if self._cred_delete(target, self._CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self._ERROR_NOT_FOUND:
            raise self._error("delete", error)

    @staticmethod
    def _error(operation: str, error: int) -> CredentialStoreError:
        return CredentialStoreError(
            f"Windows Credential Manager {operation} failed (Windows error {error})"
        )


class MemoryCredentialBackend:
    """Deterministic backend for tests; never selected by the product runtime."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self._values.get(target)

    def write(self, target: str, value: str) -> None:
        self._values[target] = value

    def delete(self, target: str) -> None:
        self._values.pop(target, None)


class VoiceCredentialStore:
    _TARGETS = {
        VoiceCredential.QWEN_API_KEY: "ORION/Voice/v1/QwenApiKey",
        VoiceCredential.YANDEX_API_KEY: "ORION/Voice/v1/YandexApiKey",
        VoiceCredential.SRS_EAM_PASSWORD: "ORION/Voice/v1/SrsEamPassword",
    }

    def __init__(self, backend: CredentialBackend) -> None:
        self._backend = backend

    def load(self, credential: VoiceCredential) -> str:
        return self._backend.read(self._TARGETS[credential]) or ""

    def save(self, credential: VoiceCredential, value: str) -> None:
        normalized = value.strip()
        target = self._TARGETS[credential]
        if normalized:
            self._backend.write(target, normalized)
        else:
            self._backend.delete(target)

    def save_all(self, *, qwen_api_key: str, yandex_api_key: str, srs_eam_password: str) -> None:
        self.save(VoiceCredential.QWEN_API_KEY, qwen_api_key)
        self.save(VoiceCredential.YANDEX_API_KEY, yandex_api_key)
        self.save(VoiceCredential.SRS_EAM_PASSWORD, srs_eam_password)

    def clear_all(self) -> None:
        for target in self._TARGETS.values():
            self._backend.delete(target)


def default_voice_credential_store() -> VoiceCredentialStore:
    return VoiceCredentialStore(WindowsCredentialBackend())


def clear_saved_voice_credentials() -> None:
    default_voice_credential_store().clear_all()


def frozen_credential_store_smoke() -> dict[str, object]:
    """Round-trip an ephemeral generic credential and always remove it."""

    target = f"ORION/Smoke/{uuid.uuid4()}"
    backend = WindowsCredentialBackend()
    try:
        backend.write(target, "orion-credential-smoke")
        return {
            "ok": backend.read(target) == "orion-credential-smoke",
            "credential_persisted_after_smoke": False,
            "secret_exposed": False,
        }
    finally:
        backend.delete(target)
