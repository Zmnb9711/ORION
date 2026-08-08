from __future__ import annotations

import pytest

from orion.pcm_dsp import _decode, _encode, pcm_peak, pcm_resample_mono, pcm_scale, pcm_to_mono


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_pcm_round_trip_supported_widths(width: int) -> None:
    minimum = -(1 << (width * 8 - 1))
    maximum = (1 << (width * 8 - 1)) - 1
    values = [minimum // 2, -1, 0, 1, maximum // 2]
    assert _decode(_encode(values, width), width) == values


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_stereo_to_mono_averages_channels(width: int) -> None:
    stereo = _encode([100, -100, 100, 20], width)
    mono = pcm_to_mono(stereo, width)
    assert _decode(mono, width) == [0, 60]


def test_scale_clips_to_pcm_limits() -> None:
    frames = _encode([30000, -30000], 2)
    scaled = pcm_scale(frames, 2, 2.0)
    assert _decode(scaled, 2) == [32767, -32768]
    assert pcm_peak(scaled, 2) == 32768


def test_resample_preserves_endpoints_and_expected_length() -> None:
    source = _encode([0, 1000, 2000, 3000], 2)
    down = pcm_resample_mono(source, 2, 16000, 8000)
    assert len(_decode(down, 2)) == 2
    assert _decode(down, 2)[0] == 0
    assert _decode(down, 2)[-1] == 3000

    up = pcm_resample_mono(down, 2, 8000, 16000)
    assert len(_decode(up, 2)) == 4
    assert _decode(up, 2)[0] == 0
    assert _decode(up, 2)[-1] == 3000


def test_invalid_alignment_and_rates_are_rejected() -> None:
    with pytest.raises(ValueError):
        pcm_peak(b"\x00", 2)
    with pytest.raises(ValueError):
        pcm_resample_mono(_encode([0, 1], 2), 2, 0, 8000)
    with pytest.raises(ValueError):
        pcm_to_mono(_encode([1, 2, 3], 2), 2)
