from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from orion.audio_device_config import audio_device_config
from orion.native_wasapi_player import NativeWasapiPlayer
from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.whisper_cpp_stt import configured_threads, stt_root, whisper_model_path
from orion.windows_sapi_backend import WindowsSapiBackend


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CORE_URL = os.environ.get("ORION_CORE_URL", "http://127.0.0.1:8765").rstrip("/")
VOICE_ENDPOINT = "/v1/voice/text"


@dataclass(frozen=True)
class VoiceBridgeReply:
    heard: str
    reply: str
    matched: bool
    tts_requested: bool


def whisper_stream_path() -> Path:
    override = os.environ.get("ORION_WHISPER_STREAM")
    if override:
        return Path(override).expanduser().resolve()
    name = "whisper-stream.exe" if os.name == "nt" else "whisper-stream"
    return stt_root() / name


def _normalize_transcript_line(line: str) -> str:
    text = ANSI_RE.sub("", line).strip()
    if not text:
        return ""
    lowered = text.casefold()
    ignored_prefixes = (
        "whisper_",
        "ggml_",
        "main:",
        "system_info:",
        "init:",
        "capture:",
        "processing",
        "[start speaking]",
    )
    if lowered.startswith(ignored_prefixes):
        return ""
    if text.startswith("[") and "]" in text and "-->" in text:
        text = text.split("]", 1)[-1].strip()
    return " ".join(text.split())


def _post_text(text: str, *, core_url: str = CORE_URL, timeout: float = 5.0) -> VoiceBridgeReply:
    body = json.dumps({"text": text, "source": "whisper", "language": "ru"}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        core_url + VOICE_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ORION Core voice bridge unavailable: {exc}") from exc
    return VoiceBridgeReply(
        heard=str(payload.get("heard", text)),
        reply=str(payload.get("reply", "")),
        matched=bool(payload.get("matched", False)),
        tts_requested=bool(payload.get("tts_requested", False)),
    )


def _speak(reply: str) -> None:
    state = audio_device_config.state()
    output = state.resolved_output
    if output is None:
        raise RuntimeError("ORION Voice has no resolved Windows output endpoint")
    spool = Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")) / "voice" / "tts"
    backend = WindowsSapiBackend(spool_dir=str(spool))
    request = AudioRenderRequest(
        command_id=f"voice-{uuid4()}",
        text=reply,
        agent=VoiceAgent.SYSTEM,
        profile=VoiceProfile(profile_id="voice_v01_ru", locale="ru-RU", persona="orion"),
        backend=TtsBackend.WINDOWS_SAPI,
        output_device=output.device_id,
    )
    rendered = backend.render(request)
    if not rendered.accepted or not rendered.output_path:
        raise RuntimeError(rendered.message)
    NativeWasapiPlayer().play(Path(rendered.output_path), output)


def build_stream_command() -> list[str]:
    stream = whisper_stream_path()
    model = whisper_model_path()
    if not stream.is_file():
        raise RuntimeError(
            f"Whisper live microphone component is missing: {stream}. "
            "ORION requires whisper-stream in addition to whisper-cli."
        )
    if not model.is_file():
        raise RuntimeError(f"Whisper model is missing: {model}")
    return [
        str(stream),
        "--model",
        str(model),
        "--threads",
        str(configured_threads()),
        "--language",
        "ru",
        "--step",
        "0",
        "--length",
        "8000",
        "--keep",
        "0",
        "--vad-thold",
        "0.60",
        "--freq-thold",
        "100.0",
        "--no-gpu",
    ]


def run_forever(*, core_url: str = CORE_URL) -> int:
    """Own microphone/STT outside Core and bridge only recognized text into Core."""

    command = build_stream_command()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(whisper_stream_path().parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    if process.stdout is None:
        raise RuntimeError("Whisper stream stdout is unavailable")

    last_text = ""
    try:
        for raw_line in process.stdout:
            text = _normalize_transcript_line(raw_line)
            if not text or text.casefold() == last_text.casefold():
                continue
            last_text = text
            bridge = _post_text(text, core_url=core_url)
            if bridge.tts_requested and bridge.reply:
                _speak(bridge.reply)
    finally:
        if process.poll() is None:
            process.terminate()
    return int(process.wait())


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
