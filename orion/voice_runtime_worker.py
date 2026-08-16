from __future__ import annotations

import json
import sys
from typing import Any

from orion.audio_conversation_test import run_conversational_audio_test
from orion.whisper_cpp_stt import ensure_runtime, runtime_ready


def _reply(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        ensure_runtime()
    except Exception as exc:
        _reply({"ok": False, "event": "startup", "error": str(exc)})
        return 2

    _reply({"ok": True, "event": "ready", "whisper_ready": runtime_ready()})
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            action = str(request.get("action", "")).casefold()
            if action == "ping":
                response = {"ok": True, "state": "ready", "whisper_ready": runtime_ready()}
            elif action == "conversation_test":
                result = run_conversational_audio_test()
                response = {"ok": True, "result": result.model_dump(mode="json")}
            elif action == "shutdown":
                _reply({"ok": True, "state": "stopping"})
                return 0
            else:
                raise ValueError(f"Unsupported Voice worker action: {action or '<empty>'}")
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        _reply(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
