from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

WHISPER_MODEL_NAME = "medium"
WHISPER_MODEL_FILENAME = "ggml-medium.bin"
WHISPER_MODEL_SHA1 = "fd9727b6e1217c2f614f9b698455c4ffd82463b4"
DEFAULT_THREADS = 4
TARGET_SAMPLE_RATE = 16000


def _product_root() -> Path:
    override = os.environ.get("ORION_PRODUCT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.casefold() in {"core", "launcher"}:
            return exe_dir.parent
        return exe_dir
    return Path(__file__).resolve().parents[1]


def whisper_cli_path() -> Path:
    override = os.environ.get("ORION_WHISPER_CLI")
    if override:
        return Path(override).expanduser().resolve()
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    return _product_root() / "VoiceSTT" / name


def whisper_model_path() -> Path:
    override = os.environ.get("ORION_WHISPER_MODEL")
    if override:
        return Path(override).expanduser().resolve()
    return _product_root() / "VoiceSTT" / "models" / WHISPER_MODEL_FILENAME


def configured_threads() -> int:
    raw = os.environ.get("ORION_WHISPER_THREADS", str(DEFAULT_THREADS))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_THREADS
    return max(1, min(value, 16))


def _read_pcm16_mono_16k(source: Path) -> bytes:
    with wave.open(str(source), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise RuntimeError(f"Whisper input must be 16-bit PCM; got sample width {sample_width}")
    if channels < 1:
        raise RuntimeError("Whisper input WAV has no audio channels")

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()

    if channels > 1:
        mono = array("h")
        for index in range(0, len(samples), channels):
            frame = samples[index : index + channels]
            mono.append(int(sum(frame) / len(frame)))
        samples = mono

    if sample_rate != TARGET_SAMPLE_RATE:
        if sample_rate <= 0:
            raise RuntimeError(f"Invalid WAV sample rate: {sample_rate}")
        target_count = max(1, int(round(len(samples) * TARGET_SAMPLE_RATE / sample_rate)))
        resampled = array("h")
        if len(samples) == 1:
            resampled.extend([samples[0]] * target_count)
        else:
            scale = (len(samples) - 1) / max(1, target_count - 1)
            for target_index in range(target_count):
                source_pos = target_index * scale
                left = int(source_pos)
                right = min(left + 1, len(samples) - 1)
                fraction = source_pos - left
                value = round(samples[left] + (samples[right] - samples[left]) * fraction)
                resampled.append(max(-32768, min(32767, int(value))))
        samples = resampled

    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _prepare_input_wav(source: Path, target: Path) -> None:
    pcm = _read_pcm16_mono_16k(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_SAMPLE_RATE)
        wav.writeframes(pcm)


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    cli = whisper_cli_path()
    model = whisper_model_path()
    if not cli.is_file():
        raise RuntimeError(f"ORION Whisper CLI is missing: {cli}")
    if not model.is_file():
        raise RuntimeError(f"ORION Whisper {WHISPER_MODEL_NAME} model is missing: {model}")

    with tempfile.TemporaryDirectory(prefix="orion-whisper-") as tmp:
        tmp_dir = Path(tmp)
        prepared = tmp_dir / "input-16k.wav"
        output_base = tmp_dir / "transcript"
        _prepare_input_wav(path, prepared)

        command = [
            str(cli),
            "--model",
            str(model),
            "--file",
            str(prepared),
            "--threads",
            str(configured_threads()),
            "--processors",
            "1",
            "--no-gpu",
            "--no-timestamps",
            "--no-prints",
            "--output-txt",
            "--output-file",
            str(output_base),
            "--language",
            language,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
            raise RuntimeError(f"Whisper STT failed: {detail}")

        transcript_path = output_base.with_suffix(".txt")
        if transcript_path.is_file():
            text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            text = completed.stdout.strip()
        return " ".join(text.split())


def copy_runtime_payload(source_dir: Path, destination_dir: Path) -> None:
    """Build/packaging helper for copying the CPU-only whisper.cpp runtime payload."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        target = destination_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
