from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from orion.audio_device_config import audio_device_config
from orion.native_wasapi_player import NativeWasapiPlayer
from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.whisper_cpp_stt import recognize_wav
from orion.windows_sapi_backend import WindowsSapiBackend
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint

PROMPT = "Привет, как дела?"
RESPONSE = "Дела отлично. Связь установлена."


class ConversationalAudioTestResult(BaseModel):
    ok: bool
    recognized_text: str = ""
    prompt: str = PROMPT
    response: str = RESPONSE
    stages: dict[str, bool]
    message: str
    input_samplerate: int | None = None


def _resolve_sounddevice_index(endpoint: WasapiEndpoint, direction: WasapiDirection) -> int:
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    wasapi = {i for i, item in enumerate(hostapis) if "wasapi" in str(item.get("name", "")).casefold()}
    channel_key = "max_input_channels" if direction is WasapiDirection.INPUT else "max_output_channels"
    candidates: list[tuple[int, str]] = []
    for index, item in enumerate(sd.query_devices()):
        if int(item.get(channel_key, 0)) <= 0:
            continue
        if wasapi and int(item.get("hostapi", -1)) not in wasapi:
            continue
        candidates.append((index, str(item.get("name", ""))))
    target = endpoint.name.casefold()
    exact = next((i for i, name in candidates if name.casefold() == target), None)
    if exact is not None:
        return exact
    partial = next((i for i, name in candidates if target in name.casefold() or name.casefold() in target), None)
    if partial is not None:
        return partial
    raise RuntimeError(f"WASAPI {direction.value} device not found: {endpoint.name}")


def _native_input_samplerate(device: int, fallback: int = 48000) -> int:
    import sounddevice as sd

    info = sd.query_devices(device)
    try:
        samplerate = int(round(float(info.get("default_samplerate", fallback))))
    except (TypeError, ValueError):
        samplerate = fallback
    return samplerate if samplerate > 0 else fallback


def _capture_wav(endpoint: WasapiEndpoint, target: Path, duration_seconds: float = 4.0) -> int:
    import sounddevice as sd

    device = _resolve_sounddevice_index(endpoint, WasapiDirection.INPUT)
    samplerate = _native_input_samplerate(device)
    frames = max(1, int(duration_seconds * samplerate))
    try:
        with sd.RawInputStream(samplerate=samplerate, device=device, channels=1, dtype="int16") as stream:
            audio, _overflowed = stream.read(frames)
    except Exception as exc:
        raise RuntimeError(
            f"Microphone capture failed at Windows/WASAPI native sample rate {samplerate} Hz: {exc}"
        ) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(bytes(audio))
    return samplerate


def _matches_control_phrase(text: str) -> bool:
    normalized = "".join(ch for ch in text.casefold() if ch.isalnum() or ch.isspace())
    words = set(normalized.split())
    return {"привет", "как", "дела"}.issubset(words)


def run_conversational_audio_test() -> ConversationalAudioTestResult:
    stages = {
        "core_connected": True,
        "input_resolved": False,
        "audio_captured": False,
        "phrase_recognized": False,
        "output_resolved": False,
        "response_played": False,
    }
    state = audio_device_config.state()
    input_endpoint = state.resolved_input
    output_endpoint = state.resolved_output
    if input_endpoint is None or output_endpoint is None:
        return ConversationalAudioTestResult(ok=False, stages=stages, message="Core could not resolve selected audio endpoints")
    stages["input_resolved"] = True
    stages["output_resolved"] = True

    samplerate: int | None = None
    recognized = ""
    try:
        with tempfile.TemporaryDirectory(prefix="orion-audio-test-") as tmp:
            capture_path = Path(tmp) / "input.wav"
            samplerate = _capture_wav(input_endpoint, capture_path)
            stages["audio_captured"] = True
            recognized = recognize_wav(capture_path, language="ru")
            if not _matches_control_phrase(recognized):
                return ConversationalAudioTestResult(
                    ok=False,
                    recognized_text=recognized,
                    stages=stages,
                    input_samplerate=samplerate,
                    message=f"Control phrase was not recognized: {recognized or '(no speech)'}",
                )
            stages["phrase_recognized"] = True

            backend = WindowsSapiBackend(spool_dir=str(Path(tmp) / "tts"))
            request = AudioRenderRequest(
                command_id=f"audio-test-{uuid4()}",
                text=RESPONSE,
                agent=VoiceAgent.SYSTEM,
                profile=VoiceProfile(profile_id="audio_test_ru", locale="ru-RU", persona="orion", rate=1.0, volume=1.0),
                backend=TtsBackend.WINDOWS_SAPI,
                output_device=output_endpoint.device_id,
            )
            rendered = backend.render(request)
            if not rendered.accepted or not rendered.output_path:
                return ConversationalAudioTestResult(
                    ok=False,
                    recognized_text=recognized,
                    stages=stages,
                    input_samplerate=samplerate,
                    message=rendered.message,
                )
            NativeWasapiPlayer().play(Path(rendered.output_path), output_endpoint)
            stages["response_played"] = True
            return ConversationalAudioTestResult(
                ok=True,
                recognized_text=recognized,
                stages=stages,
                input_samplerate=samplerate,
                message=RESPONSE,
            )
    except Exception as exc:
        return ConversationalAudioTestResult(
            ok=False,
            recognized_text=recognized,
            stages=stages,
            input_samplerate=samplerate,
            message=f"Audio test failed: {exc}",
        )
