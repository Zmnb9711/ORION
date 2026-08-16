from __future__ import annotations

"""Compatibility shim preserving the PR #104 production STT contract.

The abandoned faster-whisper experiment is not active. Existing imports remain
stable while production recognition is routed to the field-validated direct
whisper.cpp path: original captured WAV, CPU-only Medium model, runtime cwd.
"""

from orion.whisper_cpp_direct_stt import recognize_wav
from orion.whisper_cpp_stt import WHISPER_MODEL_NAME, ensure_runtime, runtime_ready

__all__ = ["WHISPER_MODEL_NAME", "ensure_runtime", "recognize_wav", "runtime_ready"]
