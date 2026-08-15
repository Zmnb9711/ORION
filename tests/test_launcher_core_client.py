from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import orion.launcher_core_client as subject


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_request_uses_single_path_first_contract(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["timeout"] = timeout
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(subject.urllib.request, "urlopen", fake_urlopen)
    client = subject.LauncherCoreClient("http://127.0.0.1:8000/")
    result = client.request(
        "v1/test",
        method="POST",
        payload={"value": 7},
        timeout=12.5,
    )

    assert result == {"ok": True}
    assert captured["url"] == "http://127.0.0.1:8000/v1/test"
    assert captured["method"] == "POST"
    assert json.loads(captured["data"].decode("utf-8")) == {"value": 7}
    assert captured["timeout"] == 12.5


def test_invalid_json_is_reported_as_core_boundary_failure(monkeypatch) -> None:
    monkeypatch.setattr(subject.urllib.request, "urlopen", lambda request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        subject.LauncherCoreClient("http://127.0.0.1:8000").request("/health")
