from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

WHISPER_MODEL_NAME = "medium"
DEFAULT_THREADS = 4
ENGINE_VERSION = "faster-whisper-1.2"
RUNTIME_VERSION_MARKER = "ORION_FASTER_WHISPER_VERSION.txt"
ProgressCallback = Callable[[str, int, int | None], None]

_model_lock = threading.RLock()
_model: Any | None = None
_model_path: Path | None = None


def stt_root() -> Path:
    override = os.environ.get("ORION_FASTER_WHISPER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
    return runtime / "stt" / "faster-whisper"


def model_dir() -> Path:
    return stt_root() / WHISPER_MODEL_NAME


def configured_threads() -> int:
    raw = os.environ.get("ORION_WHISPER_THREADS", str(DEFAULT_THREADS))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_THREADS
    return max(1, min(value, 16))


def _required_model_files(root: Path) -> tuple[Path, ...]:
    return (
        root / "config.json",
        root / "model.bin",
        root / "tokenizer.json",
        root / "preprocessor_config.json",
    )


def runtime_ready() -> bool:
    root = model_dir()
    marker = stt_root() / RUNTIME_VERSION_MARKER
    try:
        version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return version == ENGINE_VERSION and all(path.is_file() for path in _required_model_files(root))


def _import_engine():
    try:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
    except Exception as exc:  # pragma: no cover - exercised by frozen Windows smoke
        raise RuntimeError(f"faster-whisper runtime is unavailable: {type(exc).__name__}: {exc}") from exc
    return WhisperModel, download_model


def ensure_runtime(progress: ProgressCallback | None = None) -> Path:
    """Download the CTranslate2 medium model used by faster-whisper once."""
    root = model_dir()
    if runtime_ready():
        if progress is not None:
            progress("ready", 1, 1)
        return root

    root.mkdir(parents=True, exist_ok=True)
    _WhisperModel, download_model = _import_engine()
    if progress is not None:
        progress("model", 0, None)
    try:
        resolved = Path(download_model(WHISPER_MODEL_NAME, output_dir=str(root)))
    except Exception as exc:
        raise RuntimeError(f"faster-whisper medium download failed: {type(exc).__name__}: {exc}") from exc

    if resolved.resolve() != root.resolve() and resolved.is_dir():
        root = resolved
    missing = [path.name for path in _required_model_files(root) if not path.is_file()]
    if missing:
        raise RuntimeError(f"faster-whisper medium model is incomplete: missing {', '.join(missing)}")

    stt_root().mkdir(parents=True, exist_ok=True)
    (stt_root() / RUNTIME_VERSION_MARKER).write_text(ENGINE_VERSION + "\n", encoding="utf-8")
    if progress is not None:
        progress("ready", 1, 1)
    return root


def _load_model():
    global _model, _model_path
    root = model_dir()
    if not runtime_ready():
        raise RuntimeError("Faster Whisper medium is not prepared. Use Prepare Speech Recognition in Launcher first.")
    with _model_lock:
        if _model is not None and _model_path == root:
            return _model
        WhisperModel, _download_model = _import_engine()
        try:
            loaded = WhisperModel(
                str(root),
                device="cpu",
                compute_type="int8",
                cpu_threads=configured_threads(),
                num_workers=1,
                local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(f"faster-whisper model initialization failed: {type(exc).__name__}: {exc}") from exc
        _model = loaded
        _model_path = root
        return loaded


def recognize_wav(path: Path, *, language: str = "auto") -> str:
    model = _load_model()
    selected_language = None if language == "auto" else language
    try:
        segments, _info = model.transcribe(
            str(path),
            language=selected_language,
            task="transcribe",
            beam_size=1,
            best_of=1,
            vad_filter=False,
            word_timestamps=False,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    except Exception as exc:
        raise RuntimeError(f"faster-whisper transcription failed: {type(exc).__name__}: {exc}") from exc
    return " ".join(text.split())
