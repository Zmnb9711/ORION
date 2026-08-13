from __future__ import annotations

import wave
from pathlib import Path

import pytest

from orion.native_wasapi_player import NativeWasapiPlayer
from orion.windows_wasapi_backend import WasapiEndpoint


class FakeStream:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.aborted = False
        self.writes = 0
        self.payloads: list[bytes] = []

    def __enter__(self):
        self.owner.last_stream = self
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, data: bytes) -> None:
        self.writes += 1
        self.payloads.append(data)
        if self.owner.stop_after_first_write and self.writes == 1:
            self.owner.player.stop()

    def abort(self) -> None:
        self.aborted = True


class FakeSoundDevice:
    def __init__(self, native_rate: int = 16000) -> None:
        self.player = None
        self.last_stream = None
        self.stop_after_first_write = False
        self.kwargs = None
        self.native_rate = native_rate

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}, {"name": "MME"}]

    def query_devices(self, device=None):
        devices = [
            {"name": "Speakers (Realtek)", "max_output_channels": 2, "hostapi": 0, "default_samplerate": self.native_rate},
            {"name": "Pimax Dream Air Audio", "max_output_channels": 2, "hostapi": 0, "default_samplerate": self.native_rate},
            {"name": "Legacy Output", "max_output_channels": 2, "hostapi": 1, "default_samplerate": self.native_rate},
        ]
        return devices if device is None else devices[device]

    class WasapiSettings:
        def __init__(self, exclusive=False) -> None:
            self.exclusive = exclusive

    def RawOutputStream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self)


def _wav(path: Path, frames: int = 5000, sample: int = 0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(sample.to_bytes(2, "little", signed=True) * frames)


def test_resolves_vr_endpoint_to_wasapi_output_device(tmp_path: Path) -> None:
    sd = FakeSoundDevice()
    player = NativeWasapiPlayer(sd, chunk_frames=1024)
    sd.player = player
    path = tmp_path / "voice.wav"
    _wav(path)

    player.play(path, WasapiEndpoint(device_id="pnp-1", name="Pimax Dream Air Audio"))

    assert sd.kwargs["device"] == 1
    assert sd.kwargs["channels"] == 1
    assert sd.kwargs["samplerate"] == 16000
    assert sd.kwargs["extra_settings"].exclusive is False
    assert sd.last_stream.writes > 0


def test_resamples_wav_to_native_output_samplerate(tmp_path: Path) -> None:
    sd = FakeSoundDevice(native_rate=48000)
    player = NativeWasapiPlayer(sd, chunk_frames=1024)
    sd.player = player
    path = tmp_path / "voice.wav"
    _wav(path, frames=1600, sample=1000, rate=16000)

    player.play(path, WasapiEndpoint(device_id="realtek", name="Speakers (Realtek)"))

    assert sd.kwargs["samplerate"] == 48000
    written = b"".join(sd.last_stream.payloads)
    assert len(written) == 1600 * 3 * 2
    first_sample = int.from_bytes(written[:2], "little", signed=True)
    assert first_sample == 1000


def test_stop_aborts_active_stream_and_ends_chunked_playback(tmp_path: Path) -> None:
    sd = FakeSoundDevice()
    player = NativeWasapiPlayer(sd, chunk_frames=256)
    sd.player = player
    sd.stop_after_first_write = True
    path = tmp_path / "voice.wav"
    _wav(path, frames=4000)

    player.play(path, WasapiEndpoint(device_id="pnp-1", name="Pimax Dream Air Audio"))

    assert sd.last_stream.aborted is True
    assert sd.last_stream.writes == 1


def test_volume_scales_pcm_samples(tmp_path: Path) -> None:
    sd = FakeSoundDevice()
    player = NativeWasapiPlayer(sd, chunk_frames=4)
    sd.player = player
    path = tmp_path / "voice.wav"
    _wav(path, frames=4, sample=10000)

    player.play(path, WasapiEndpoint(device_id="pnp-1", name="Pimax Dream Air Audio"), volume=0.5)

    assert sd.last_stream.payloads
    first_sample = int.from_bytes(sd.last_stream.payloads[0][:2], "little", signed=True)
    assert first_sample == 5000


def test_volume_outside_supported_range_is_rejected(tmp_path: Path) -> None:
    sd = FakeSoundDevice()
    player = NativeWasapiPlayer(sd)
    path = tmp_path / "voice.wav"
    _wav(path)

    with pytest.raises(ValueError, match="volume"):
        player.play(path, WasapiEndpoint(device_id="pnp-1", name="Pimax Dream Air Audio"), volume=1.1)


def test_missing_matching_wasapi_device_is_rejected(tmp_path: Path) -> None:
    sd = FakeSoundDevice()
    player = NativeWasapiPlayer(sd)
    path = tmp_path / "voice.wav"
    _wav(path)

    with pytest.raises(RuntimeError, match="device not found"):
        player.play(path, WasapiEndpoint(device_id="x", name="Unknown VR headset"))
