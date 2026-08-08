from pathlib import Path
import struct
import wave

from orion.windows_sapi_backend import WindowsSapiBackend


def _write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        frames = bytearray()
        for i in range(1600):
            sample = 12000 if (i // 20) % 2 == 0 else -12000
            frames.extend(struct.pack("<hh", sample, sample))
        wav.writeframes(bytes(frames))


def test_prepare_radio_creates_mono_wav_copy(tmp_path: Path) -> None:
    source = tmp_path / "speech.wav"
    _write_test_wav(source)
    backend = WindowsSapiBackend(spool_dir=str(tmp_path))

    target = backend.prepare_radio(source)

    assert target != source
    assert target.name == "speech.radio.wav"
    assert source.exists()
    assert target.exists()
    with wave.open(str(target), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        assert wav.getnframes() > 0


def test_prepare_radio_does_not_modify_source_file(tmp_path: Path) -> None:
    source = tmp_path / "speech.wav"
    _write_test_wav(source)
    before = source.read_bytes()

    WindowsSapiBackend(spool_dir=str(tmp_path)).prepare_radio(source)

    assert source.read_bytes() == before
