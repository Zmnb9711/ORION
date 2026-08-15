from __future__ import annotations

"""Compatibility shim for the abandoned faster-whisper experiment.

The target Windows machine has now validated whisper.cpp end-to-end manually:
whisper-cli.exe, ggml-medium.bin, the ORION-captured WAV and the production CLI
flags all work. Keep existing imports stable while routing production STT back
to whisper.cpp. The direct recognizer deliberately skips ORION's former WAV
pre-conversion and launches from the whisper runtime directory, matching the
successful manual test.
"""

from orion.whisper_cpp_direct_stt import recognize_wav
from orion.whisper_cpp_stt import WHISPER_MODEL_NAME, ensure_runtime, runtime_ready

__all__ = ["WHISPER_MODEL_NAME", "ensure_runtime", "recognize_wav", "runtime_ready"]
