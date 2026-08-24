"""Offline PyInstaller entry point for Core-owned SRS native dependencies."""

from __future__ import annotations

import json

from orion.srs_opus import OPUS_FRAME_BYTES, OpusDecoder, OpusEncoder, OpusLibrary
from orion.srs_resampler import offline_smoke as resampler_smoke


def run_smoke() -> dict[str, object]:
    encoder = OpusEncoder()
    decoder = OpusDecoder()
    try:
        encoded = encoder.encode(bytes(OPUS_FRAME_BYTES))
        decoded = decoder.decode(encoded)
    finally:
        encoder.close()
        decoder.close()
    return {
        "ok": True,
        "opus_version": OpusLibrary().version,
        "encoded_bytes": len(encoded),
        "decoded_bytes": len(decoded),
        "resampler": resampler_smoke(),
        "network_used": False,
        "audio_devices_opened": False,
    }


def main() -> int:
    print(json.dumps(run_smoke(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
