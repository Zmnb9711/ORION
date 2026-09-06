"""Real Core/Router/SRS worker integration with offline HTTP/codec/socket seams."""

import argparse
import asyncio
from copy import deepcopy
import json
import sys

import pytest

from orion import protected_presentation_probe as probe
from orion import yandex_srs_live_core as live
from orion.srs_radio_transport import SrsState


class OfflineRadio:
    client_guid = "OOOOOOOOOOOOOOOOOOOOOO"
    server_version = "2.4.0.0"
    coalition = 2
    radio_registered = False
    udp_registered = False
    udp_packets_received = 0
    udp_packets_sent = 0
    state = SrsState.DISCONNECTED

    def connect(self):
        self.state = SrsState.READY
        self.radio_registered = self.udp_registered = True

    def send_voice(self, datagram):
        self.udp_packets_sent += 1

    def close(self):
        self.state = SrsState.STOPPED


class OfflineCodec:
    def encode(self, pcm):
        return b"offline-opus"

    def decode(self, packet):
        raise AssertionError("No RX in synthetic test")

    def close(self):
        pass


class OfflineTts:
    def __init__(self, key):
        self.closed = False
        self.calls = []

    async def synthesize(self, text, language, tx_id, observer=None):
        self.calls.append((text, language, tx_id))
        assert language == "en-US"
        if observer:
            observer("speechkit_attempt_started", {"attempt_number": 1})
            observer(
                "speechkit_attempt_succeeded", {"attempt_number": 1, "pcm_bytes": 960}
            )
        return bytes(960)

    async def aclose(self):
        self.closed = True


def test_six_cases_real_endpoint_adapter_router_and_machine_gate(monkeypatch, tmp_path):
    real_endpoint = live.SrsYandexPcmEndpoint
    radios = []
    adapters = []

    def offline_endpoint(*args):
        radio = OfflineRadio()
        radios.append(radio)
        return real_endpoint(
            *args,
            radio_factory=lambda *_: radio,  # type: ignore[arg-type]
            encoder_factory=OfflineCodec,  # type: ignore[arg-type]
            decoder_factory=OfflineCodec,  # type: ignore[arg-type]
        )

    def tts_factory(key):
        adapter = OfflineTts(key)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr(live, "SrsYandexPcmEndpoint", offline_endpoint)
    monkeypatch.setattr(probe, "SpeechKitTtsAdapter", tts_factory)
    args = argparse.Namespace(
        host="offline.invalid",
        port=5002,
        callsign="ORION TEST",
        frequency_hz=251000000,
        capture_synthetic_audio=True,
    )
    report = asyncio.run(probe._field(args, tmp_path, "SECRET_KEY", "SECRET_PASSWORD"))
    assert report["machine_pass"] is True, report
    assert report["human_review"] == "REQUIRED"
    assert report["presentation_shutdown_clean"] is True
    assert radios[0].udp_packets_sent == 6 and radios[0].state == SrsState.STOPPED
    assert adapters[0].closed and len(adapters[0].calls) == 6
    assert len(list(tmp_path.glob("*.wav"))) == 6
    serialized = json.dumps(report)
    assert "SECRET" not in serialized
    diagnostic = json.dumps(
        [
            report["presentation_events"],
            report["transport_events"],
            report["radio_events"],
        ]
    )
    assert all(text not in diagnostic for text in probe.EXPECTED)
    assert not list(tmp_path.glob("*.jsonl"))  # Never writes legacy IA evidence.

    for mutation in (
        "duplicate",
        "missing",
        "wrong_text",
        "wrong_voice",
        "retry_after_submit",
        "order",
        "endpoint_error",
    ):
        changed = deepcopy(report)
        rows = changed["cases"]
        transport = changed["transport_events"]
        presentation = changed["presentation_events"]
        tts = changed["tts"]
        assert isinstance(rows, list) and isinstance(tts, dict)
        assert isinstance(transport, (list, tuple)) and isinstance(
            presentation, (list, tuple)
        )
        if mutation == "duplicate":
            changed["transport_events"] = [*transport, transport[-1]]
        elif mutation == "missing":
            changed["transport_events"] = transport[:-1]
        elif mutation == "wrong_text":
            rows[0]["expected_text"] = "Rewritten."
        elif mutation == "wrong_voice":
            tts[rows[0]["tx_id"]]["voice"] = "jane"
        elif mutation == "retry_after_submit":
            changed["presentation_events"] = [
                *presentation,
                {"event": "speechkit_attempt_started", "tx_id": rows[0]["tx_id"]},
            ]
        elif mutation == "order":
            changed["transport_events"] = list(reversed(transport))
        else:
            changed["transport_events"] = [*transport, {"event": "endpoint_error"}]
        assert not probe.field_machine_gate(changed), mutation


def test_cli_requires_explicit_field_confirmation_before_credentials(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe", "--field"])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2


def test_list_cases_has_no_credentials_or_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe", "--list-cases"])
    assert probe.main() == 0
    output = capsys.readouterr().out
    assert all(text in output for text in probe.EXPECTED)


@pytest.mark.parametrize(
    "report", [{}, {"cases": []}, {"cases": [None] * 6, "tts": {}}]
)
def test_incomplete_evidence_is_never_pass(report):
    assert not probe.field_machine_gate(report)
