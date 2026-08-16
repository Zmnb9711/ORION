from __future__ import annotations

from types import SimpleNamespace

from orion import whisper_cpp_stt as stt


def test_whisper_process_console_decode_cannot_raise_on_native_bytes(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        # This models the native Windows byte that produced the field failure:
        # 0xCF is invalid at this position for UTF-8, but diagnostics must not
        # be allowed to abort recognition before the transcript file is read.
        raw = b"native diagnostic: \xcf\xff"
        encoding = str(kwargs.get("encoding", "utf-8"))
        errors = str(kwargs.get("errors", "strict"))
        return SimpleNamespace(
            returncode=0,
            stdout=raw.decode(encoding, errors=errors),
            stderr="",
        )

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    completed = stt._run_whisper(["whisper-cli.exe", "--help"])

    assert completed.returncode == 0
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert "\ufffd" in completed.stdout
