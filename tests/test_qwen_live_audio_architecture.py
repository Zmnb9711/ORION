from pathlib import Path


def test_qwen_live_must_not_open_two_independent_portaudio_streams_in_core() -> None:
    """Regression contract for ADR-004.

    Qwen Live must not own independent RawInputStream + RawOutputStream objects
    inside ORION Core. PortAudio documents simultaneous multi-stream device use
    as implementation-defined; a native PortAudio/WASAPI failure must not be
    allowed to take down the stable Core process.
    """
    source = Path("orion/qwen_live_audio_core.py").read_text(encoding="utf-8")

    assert not (
        "sd.RawInputStream(" in source and "sd.RawOutputStream(" in source
    ), "Qwen Live still opens independent input/output PortAudio streams inside Core"
