"""Differential execution against the immutable field-validated Git tree.

No real provider/UDP/audio hardware. Optional recorded PCM is a byte replay,
paired with explicit FINAL fixtures, not a new recognition of the recording.
"""
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

GOLDEN = "57a563a067c980c3ff8057172aa6f5fefb33a5b0"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def replays(tmp_path_factory):
    root = tmp_path_factory.mktemp("golden-differential")
    golden = root / "golden"
    archive = subprocess.check_output(["git", "archive", "--format=zip", GOLDEN], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        source.extractall(golden)
    pairs = []
    inputs: list[str | None] = [None]
    if os.environ.get("ORION_GOLDEN_RX_WAV"):
        inputs.append(os.environ["ORION_GOLDEN_RX_WAV"])
    cases = [(wav, coalition, metadata) for wav in inputs for coalition in (2, 0)
             for metadata in ("full", "missing", "lost-after-arm")]
    for index, (wav, coalition, metadata) in enumerate(cases):
        pair = []
        for tree, host in ((golden, "field"), (ROOT, "runtime")):
            directory = root / f"replay-{index}-{len(pair)}"
            command = [sys.executable, str(ROOT / "tests/fallback_voice_replay.py"),
                       "--tree", str(tree), "--host", host, "--output", str(directory),
                       "--human-coalition", str(coalition), "--peer-metadata", metadata]
            if wav:
                command += ["--wav", wav]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=45)
            pair.append(json.loads((directory / "result.json").read_text(encoding="utf-8")))
        pairs.append(pair)
    return root, pairs


def test_actual_field_and_launcher_hosts_preserve_golden_turn_results(replays):
    _, pairs = replays
    for golden, launcher in pairs:
        for candidate in (launcher,):
            assert candidate["stt_options"] == golden["stt_options"]
            assert candidate["tts_requests"] == golden["tts_requests"]
            assert candidate["pcm_sha256"] == golden["pcm_sha256"]
            assert candidate["provider_calls"] == candidate["physical_ptt"] == 0
            assert len(candidate["rows"]) == len(golden["rows"]) == 7
            for expected, actual in zip(golden["rows"], candidate["rows"]):
                # The only host adaptation here is who already owns live DCS.
                # All other captured control/data-path fields compare exactly.
                expected = {**expected, "trace": [t for t in expected["trace"] if not t.startswith("world_")]}
                actual = {**actual, "trace": [t for t in actual["trace"] if not t.startswith("world_")]}
                assert actual == expected


def test_golden_supported_and_unsupported_gates_are_not_widened(replays):
    _, pairs = replays
    for _, launcher in pairs:
        for index, row in enumerate(launcher["rows"]):
            supported = index in (0, 2, 4)
            assert row["core_status"] == ["completed" if supported else "unsupported"]
            assert row["terminal"] == ("completed" if supported else "unsupported")
            assert row["tx_count"] == len(row["tts_texts"]) == int(supported)
            assert row["eou_count"] == 1
            if supported:
                assert row["tts_texts"] == [row["finalized"][0]["text"]]
                assert row["finalized"][0]["tool_count"] == 1
                assert len(row["finalized"][0]["values"]) == 3
            else:
                assert row["finalized"][0]["tool_count"] == 0


def test_replayed_final_fixtures_match_saved_successful_field_hashes(replays):
    _, pairs = replays
    # Exact FINAL spellings verified against the archived successful reports,
    # not inferred from the failed installed turn's 27-character FINAL.
    expected = {2: "6220749b546b383afba5f11b7d4e8d35a96bb4aa70c935722c66ce866a7f1d9c",
                3: "1c7329d38a21b94b9a7eadd042cb8980a1b677ffcc9de95e9faab0478b8c4ba9"}
    for golden, _ in pairs:
        for index, digest in expected.items():
            text = golden["rows"][index]["finalized_utterances"][0]["text"]
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest


