from pathlib import Path


def test_qwen_live_build_402_has_one_blocking_owner_per_audio_direction() -> None:
    source = Path("orion/qwen_live_audio_core.py").read_text(encoding="utf-8")

    assert source.count("sd.RawInputStream(") == 1
    assert source.count("sd.RawOutputStream(") == 1
    assert "sd.RawStream(" not in source
    assert "callback=" not in source
