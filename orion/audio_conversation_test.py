from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from orion.audio_device_config import audio_device_config
from orion.faster_whisper_stt import recognize_wav
from orion.native_wasapi_player import NativeWasapiPlayer
from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.whisper_cpp_stt import runtime_ready
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


class VoiceTranscriptionTestResult(BaseModel):
    ok: bool
    recognized_text: str = ""
    input_samplerate: int | None = None
    message: str = ""


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


def capture_and_recognize_for_test() -> VoiceTranscriptionTestResult:
    """Input half of the approved pipeline: microphone -> Whisper -> transcript."""
    if not runtime_ready():
        return VoiceTranscriptionTestResult(ok=False, message="Whisper runtime is not ready")
    state = audio_device_config.state()
    input_endpoint = state.resolved_input
    if input_endpoint is None:
        return VoiceTranscriptionTestResult(ok=False, message="Selected microphone could not be resolved")
    samplerate: int | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="orion-audio-input-") as tmp:
            capture_path = Path(tmp) / "input.wav"
            samplerate = _capture_wav(input_endpoint, capture_path)
            recognized = recognize_wav(capture_path, language="ru")
            return VoiceTranscriptionTestResult(
                ok=True,
                recognized_text=recognized,
                input_samplerate=samplerate,
                message="Whisper transcription completed",
            )
    except Exception as exc:
        return VoiceTranscriptionTestResult(
            ok=False,
            input_samplerate=samplerate,
            message=f"Whisper transcription failed: {exc}",
        )


def play_response_for_test(text: str = RESPONSE) -> tuple[bool, str]:
    """Output half of the approved pipeline: Core text -> Windows SAPI -> speakers."""
    state = audio_device_config.state()
    output_endpoint = state.resolved_output
    if output_endpoint is None:
        return False, "Selected audio output could not be resolved"
    try:
        with tempfile.TemporaryDirectory(prefix="orion-audio-output-") as tmp:
            backend = WindowsSapiBackend(spool_dir=str(Path(tmp) / "tts"))
            request = AudioRenderRequest(
                command_id=f"audio-test-{uuid4()}",
                text=text,
                agent=VoiceAgent.SYSTEM,
                profile=VoiceProfile(
                    profile_id="audio_test_ru",
                    locale="ru-RU",
                    persona="orion",
                    rate=1.0,
                    volume=1.0,
                ),
                backend=TtsBackend.WINDOWS_SAPI,
                output_device=output_endpoint.device_id,
            )
            rendered = backend.render(request)
            if not rendered.accepted or not rendered.output_path:
                return False, rendered.message
            NativeWasapiPlayer().play(Path(rendered.output_path), output_endpoint)
            return True, text
    except Exception as exc:
        return False, f"Windows SAPI/output failed: {exc}"


def run_conversational_audio_test() -> ConversationalAudioTestResult:
    """Legacy in-process composition kept for diagnostics and unit coverage."""
    stages = {
        "core_connected": True,
        "voice_worker_ready": True,
        "whisper_ready": runtime_ready(),
        "input_resolved": False,
        "audio_captured": False,
        "phrase_recognized": False,
        "output_resolved": False,
        "response_played": False,
        "voice_worker_still_ready": False,
    }
    transcription = capture_and_recognize_for_test()
    stages["input_resolved"] = transcription.input_samplerate is not None
    stages["audio_captured"] = transcription.input_samplerate is not None
    if not transcription.ok:
        stages["voice_worker_still_ready"] = runtime_ready()
        return ConversationalAudioTestResult(
            ok=False,
            recognized_text=transcription.recognized_text,
            stages=stages,
            input_samplerate=transcription.input_samplerate,
            message=transcription.message,
        )
    if not _matches_control_phrase(transcription.recognized_text):
        stages["voice_worker_still_ready"] = runtime_ready()
        return ConversationalAudioTestResult(
            ok=False,
            recognized_text=transcription.recognized_text,
            stages=stages,
            input_samplerate=transcription.input_samplerate,
            message=f"Control phrase was not recognized by Whisper: {transcription.recognized_text or '(no speech)'}",
        )
    stages["phrase_recognized"] = True
    stages["output_resolved"] = audio_device_config.state().resolved_output is not None
    played, message = play_response_for_test(RESPONSE)
    stages["response_played"] = played
    stages["voice_worker_still_ready"] = runtime_ready()
    return ConversationalAudioTestResult(
        ok=played and stages["voice_worker_still_ready"],
        recognized_text=transcription.recognized_text,
        stages=stages,
        input_samplerate=transcription.input_samplerate,
        message=message,
    )
