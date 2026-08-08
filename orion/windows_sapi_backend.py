from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path

from orion.pcm_dsp import pcm_peak, pcm_resample_mono, pcm_scale, pcm_to_mono
from orion.tts_audio import AudioRenderRequest, AudioRenderResult, TtsBackend


class WindowsSapiBackend:
    """Native Windows implementation using PowerShell/System.Speech and winsound.

    SAPI synthesis writes a WAV file. Playback uses Python's winsound module, which
    targets the Windows default output endpoint. Exact endpoint selection is kept as
    a future WASAPI backend rather than pretending winsound can route by device id.

    Radio DSP is applied only to ORION-owned WAV copies. It never changes the DCS or
    Windows game-audio session volume.
    """

    def __init__(self, spool_dir: str = "runtime/tts") -> None:
        self._spool_dir = Path(spool_dir)

    @property
    def available(self) -> bool:
        return os.name == "nt"

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        target = self._spool_dir / f"{request.command_id}.wav"
        if not self.available:
            return AudioRenderResult(
                accepted=False,
                backend=TtsBackend.WINDOWS_SAPI,
                command_id=request.command_id,
                output_path=str(target),
                message="Windows SAPI backend is only available on Windows",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        rate = max(-10, min(10, round((request.profile.rate - 1.0) * 10)))
        volume = max(0, min(100, round(request.profile.volume * 100)))
        voice_name = request.profile.voice_name or ""
        script = _powershell_sapi_script(text=request.text, target=str(target.resolve()), rate=rate, volume=volume, voice_name=voice_name)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not target.exists():
            detail = completed.stderr.strip() or completed.stdout.strip() or "SAPI synthesis failed"
            return AudioRenderResult(accepted=False, backend=TtsBackend.WINDOWS_SAPI, command_id=request.command_id, output_path=str(target), message=detail)
        return AudioRenderResult(accepted=True, backend=TtsBackend.WINDOWS_SAPI, command_id=request.command_id, output_path=str(target), message="Windows SAPI synthesis completed")

    def prepare_radio(self, path: Path) -> Path:
        """Create an ORION-only narrow-band radio rendition of a PCM WAV file."""
        if not path.exists():
            raise FileNotFoundError(path)
        target = path.with_name(f"{path.stem}.radio.wav")
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())

        if width not in {1, 2, 3, 4}:
            raise ValueError("Unsupported PCM sample width for radio DSP")
        if channels == 2:
            frames = pcm_to_mono(frames, width)
            channels = 1
        elif channels != 1:
            raise ValueError("Radio DSP supports mono or stereo PCM WAV only")

        radio_rate = min(rate, 8000)
        if radio_rate != rate:
            frames = pcm_resample_mono(frames, width, rate, radio_rate)
            frames = pcm_resample_mono(frames, width, radio_rate, rate)

        frames = pcm_scale(frames, width, 1.35)
        peak = pcm_peak(frames, width)
        max_peak = (1 << (width * 8 - 1)) - 1
        if peak > max_peak * 0.92:
            frames = pcm_scale(frames, width, (max_peak * 0.92) / peak)

        with wave.open(str(target), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(width)
            output.setframerate(rate)
            output.writeframes(frames)
        return target

    def play_wav(self, path: Path, device_id: str = "default", volume: float = 1.0) -> None:
        if not self.available:
            raise RuntimeError("Native Windows playback is only available on Windows")
        if device_id not in {"", "default"}:
            raise RuntimeError("Native winsound backend supports the Windows default output only; use a WASAPI backend for explicit device routing")
        if not path.exists():
            raise FileNotFoundError(path)
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def stop(self) -> None:
        if not self.available:
            return
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)


def _powershell_sapi_script(*, text: str, target: str, rate: int, volume: int, voice_name: str) -> str:
    escaped_text = text.replace("'", "''")
    escaped_target = target.replace("'", "''")
    escaped_voice = voice_name.replace("'", "''")
    select_voice = f"$s.SelectVoice('{escaped_voice}');" if escaped_voice else ""
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"{select_voice}"
        f"$s.Rate = {rate}; $s.Volume = {volume}; "
        f"$s.SetOutputToWaveFile('{escaped_target}'); "
        f"$s.Speak('{escaped_text}'); "
        "$s.Dispose();"
    )
