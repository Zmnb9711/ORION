from __future__ import annotations


def pcm_to_mono(frames: bytes, sample_width: int) -> bytes:
    samples = _decode(frames, sample_width)
    if len(samples) % 2:
        raise ValueError("Stereo PCM frame contains an incomplete sample pair")
    mono = [round((samples[i] + samples[i + 1]) / 2) for i in range(0, len(samples), 2)]
    return _encode(mono, sample_width)


def pcm_scale(frames: bytes, sample_width: int, factor: float) -> bytes:
    minimum, maximum = _limits(sample_width)
    scaled = [max(minimum, min(maximum, round(sample * factor))) for sample in _decode(frames, sample_width)]
    return _encode(scaled, sample_width)


def pcm_peak(frames: bytes, sample_width: int) -> int:
    samples = _decode(frames, sample_width)
    return max((abs(sample) for sample in samples), default=0)


def pcm_resample_mono(frames: bytes, sample_width: int, source_rate: int, target_rate: int) -> bytes:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("PCM sample rates must be positive")
    if source_rate == target_rate:
        return frames
    source = _decode(frames, sample_width)
    if len(source) < 2:
        return frames
    output_count = max(1, round(len(source) * target_rate / source_rate))
    if output_count == 1:
        return _encode([source[0]], sample_width)
    scale = (len(source) - 1) / (output_count - 1)
    output: list[int] = []
    for index in range(output_count):
        position = index * scale
        left = int(position)
        right = min(left + 1, len(source) - 1)
        fraction = position - left
        output.append(round(source[left] * (1.0 - fraction) + source[right] * fraction))
    return _encode(output, sample_width)


def _limits(sample_width: int) -> tuple[int, int]:
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError("Unsupported PCM sample width")
    bits = sample_width * 8
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def _decode(frames: bytes, sample_width: int) -> list[int]:
    _limits(sample_width)
    if len(frames) % sample_width:
        raise ValueError("PCM byte stream is not aligned to sample width")
    samples: list[int] = []
    for offset in range(0, len(frames), sample_width):
        raw = frames[offset : offset + sample_width]
        if sample_width == 1:
            samples.append(raw[0] - 128)
        else:
            samples.append(int.from_bytes(raw, "little", signed=True))
    return samples


def _encode(samples: list[int], sample_width: int) -> bytes:
    minimum, maximum = _limits(sample_width)
    output = bytearray()
    for sample in samples:
        value = max(minimum, min(maximum, int(sample)))
        if sample_width == 1:
            output.append(value + 128)
        else:
            output.extend(value.to_bytes(sample_width, "little", signed=True))
    return bytes(output)
