from __future__ import annotations

import json

from orion.srs_diagnostics import SrsTransportDiagnostics


def test_srs_diagnostics_are_bounded_scalar_only_and_redact_secrets(tmp_path) -> None:  # noqa: ANN001
    api_key = "api-secret-value"
    eam = "eam-secret-value"
    diagnostics = SrsTransportDiagnostics(
        "session",
        secrets=(api_key, eam),
        runtime_dir=tmp_path,
    )
    diagnostics.record(
        "state",
        state="READY",
        radio_registered=True,
        udp_packets_received=5,
        error=f"failed {api_key} {eam}",
        raw_pcm=b"forbidden",
        opus_payload=b"forbidden",
        full_guid="GGGGGGGGGGGGGGGGGGGGGG",
        authorization=f"Bearer {api_key}",
    )
    payload = json.loads(diagnostics.path.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)
    assert payload["state"] == "READY"
    assert payload["radio_registered"] is True
    assert payload["udp_packets_received"] == 5
    assert api_key not in encoded and eam not in encoded
    for forbidden in ("raw_pcm", "opus_payload", "full_guid", "authorization"):
        assert forbidden not in payload
    for index in range(1100):
        diagnostics.record("counter", value=index)
    assert len(diagnostics.snapshot()) == 1000
