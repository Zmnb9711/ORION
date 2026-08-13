from __future__ import annotations

import json
import subprocess
from pathlib import Path

import orion.windows_wasapi_backend as module
from orion.windows_wasapi_backend import (
    WasapiDirection,
    WasapiEndpoint,
    WasapiEndpointCatalog,
    WasapiPlaybackBackend,
)


class _FakeDefault:
    device = (0, 1)


class _FakeSoundDevice:
    default = _FakeDefault()

    @staticmethod
    def query_hostapis():
        return [{"name": "Windows WASAPI"}, {"name": "MME"}]

    @staticmethod
    def query_devices():
        return [
            {"name": "USB Mic", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
            {"name": "USB Headset", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Legacy Device", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 1},
        ]


def test_fast_sounddevice_discovery_marks_defaults_and_filters_host(monkeypatch) -> None:
    monkeypatch.setattr(module, "sd", _FakeSoundDevice())
    endpoints = WasapiEndpointCatalog._enumerate_sounddevice()
    assert [(item.name, item.direction) for item in endpoints] == [
        ("USB Mic", WasapiDirection.INPUT),
        ("USB Headset", WasapiDirection.OUTPUT),
    ]
    assert endpoints[0].is_default is True
    assert endpoints[1].is_default is True
    assert endpoints[0].device_id == "sounddevice:wasapi:input:0"
    assert endpoints[1].device_id == "sounddevice:wasapi:output:1"


def test_sounddevice_failure_returns_fast_empty_result(monkeypatch) -> None:
    class Broken:
        default = _FakeDefault()

        @staticmethod
        def query_hostapis():
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr(module, "sd", Broken())
    assert WasapiEndpointCatalog._enumerate_sounddevice() == []
    monkeypatch.setattr(module, "sd", None)
    assert WasapiEndpointCatalog._enumerate_sounddevice() == []


def test_catalog_cache_refresh_and_direction_views(monkeypatch) -> None:
    calls = {"count": 0}

    def provider():
        calls["count"] += 1
        return [
            WasapiEndpoint(device_id="mic", name="Mic", direction=WasapiDirection.INPUT, is_default=True),
            WasapiEndpoint(device_id="out", name="Output", direction=WasapiDirection.OUTPUT, is_default=True),
        ]

    catalog = WasapiEndpointCatalog(provider=provider, cache_ttl_s=60)
    assert [x.device_id for x in catalog.inputs()] == ["mic"]
    assert [x.device_id for x in catalog.outputs()] == ["out"]
    assert calls["count"] == 1
    refreshed = catalog.refresh()
    assert len(refreshed) == 2
    assert calls["count"] == 2
    refreshed[0].name = "mutated"
    assert catalog.endpoints()[0].name == "Mic"


def test_choose_uses_supplied_snapshot_without_enumeration() -> None:
    catalog = WasapiEndpointCatalog(provider=lambda: (_ for _ in ()).throw(AssertionError("must not enumerate")))
    snapshot = [
        WasapiEndpoint(device_id="mic-a", name="Desk Microphone", direction=WasapiDirection.INPUT, active=False),
        WasapiEndpoint(device_id="mic-b", name="VR Microphone", direction=WasapiDirection.INPUT, is_default=True),
        WasapiEndpoint(device_id="out-a", name="VR Headset", direction=WasapiDirection.OUTPUT, is_default=True),
    ]
    assert catalog.choose("default", WasapiDirection.INPUT, endpoints=snapshot).device_id == "mic-b"
    assert catalog.choose("MIC-B", WasapiDirection.INPUT, endpoints=snapshot).device_id == "mic-b"
    assert catalog.choose("headset", WasapiDirection.OUTPUT, endpoints=snapshot).device_id == "out-a"
    assert catalog.choose("missing", WasapiDirection.OUTPUT, endpoints=snapshot) is None
    assert catalog.choose("default", WasapiDirection.INPUT, endpoints=[snapshot[0]]) is None


def test_bounded_pnp_fallback_parses_rows(monkeypatch) -> None:
    payload = [
        {"InstanceId": r"SWD\\MMDEVAPI\\{0.0.1.00000000}.{mic}", "FriendlyName": "PnP Mic"},
        {"InstanceId": r"SWD\\MMDEVAPI\\{0.0.0.00000000}.{out}", "FriendlyName": "PnP Output"},
        {"InstanceId": "UNKNOWN", "FriendlyName": "Ignore"},
    ]

    class Completed:
        returncode = 0
        stdout = json.dumps(payload)

    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = WasapiEndpointCatalog._enumerate_pnp_bounded()
    assert [x.direction for x in result] == [WasapiDirection.INPUT, WasapiDirection.OUTPUT]
    assert seen["timeout"] == 0.75
    assert seen["check"] is False


def test_bounded_pnp_fallback_never_blocks_on_errors(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=0.75)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    assert WasapiEndpointCatalog._enumerate_pnp_bounded() == []

    class BadJson:
        returncode = 0
        stdout = "not-json"

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: BadJson())
    assert WasapiEndpointCatalog._enumerate_pnp_bounded() == []

    class Failed:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: Failed())
    assert WasapiEndpointCatalog._enumerate_pnp_bounded() == []


def test_windows_enumeration_prefers_fast_path_then_fallback(monkeypatch) -> None:
    catalog = WasapiEndpointCatalog(cache_ttl_s=0)
    monkeypatch.setattr(module.os, "name", "nt")
    fast = [WasapiEndpoint(device_id="fast", name="Fast", direction=WasapiDirection.OUTPUT)]
    monkeypatch.setattr(catalog, "_enumerate_sounddevice", lambda: fast)
    monkeypatch.setattr(catalog, "_enumerate_pnp_bounded", lambda: (_ for _ in ()).throw(AssertionError("fallback used")))
    assert catalog.endpoints()[0].device_id == "fast"

    monkeypatch.setattr(catalog, "_enumerate_sounddevice", lambda: [])
    monkeypatch.setattr(catalog, "_enumerate_pnp_bounded", lambda: [WasapiEndpoint(device_id="pnp", name="PnP")])
    assert catalog.refresh()[0].device_id == "pnp"


def test_playback_backend_success_stop_and_errors(tmp_path: Path) -> None:
    output = WasapiEndpoint(device_id="out", name="Output", direction=WasapiDirection.OUTPUT, is_default=True)
    catalog = WasapiEndpointCatalog(provider=lambda: [output])
    played = []
    stopped = []
    backend = WasapiPlaybackBackend(catalog, lambda p, e, v: played.append((p, e.device_id, v)), lambda: stopped.append(True))
    wav = tmp_path / "test.wav"
    wav.write_bytes(b"RIFF")
    resolved = backend.play_wav(wav, volume=0.5)
    assert resolved.device_id == "out"
    assert played == [(wav, "out", 0.5)]
    backend.stop()
    assert stopped == [True]

    try:
        backend.play_wav(tmp_path / "missing.wav")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing wav must fail")

    empty = WasapiPlaybackBackend(WasapiEndpointCatalog(provider=lambda: []), lambda *a: None, lambda: None)
    try:
        empty.play_wav(wav)
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing output endpoint must fail")
