"""Offline PyInstaller entry point for Core-owned SRS native dependencies."""

from __future__ import annotations

import json

from orion.srs_opus import OPUS_FRAME_BYTES, OpusDecoder, OpusEncoder, OpusLibrary
from orion.srs_resampler import offline_smoke as resampler_smoke
from orion.yandex_speechkit_stt import speechkit_session_options


def run_smoke() -> dict[str, object]:
    import google.protobuf
    import grpc

    encoder = OpusEncoder()
    decoder = OpusDecoder()
    try:
        encoded = encoder.encode(bytes(OPUS_FRAME_BYTES))
        decoded = decoder.decode(encoded)
    finally:
        encoder.close()
        decoder.close()
    speechkit_options = speechkit_session_options()
    return {
        "ok": True,
        "opus_version": OpusLibrary().version,
        "encoded_bytes": len(encoded),
        "decoded_bytes": len(decoded),
        "resampler": resampler_smoke(),
        "speechkit_stt": {
            "grpc_version": grpc.__version__,
            "protobuf_version": google.protobuf.__version__,
            "model": speechkit_options.recognition_model.model,
            "sample_rate_hz": (
                speechkit_options.recognition_model.audio_format.raw_audio.sample_rate_hertz
            ),
            "external_eou": (
                speechkit_options.eou_classifier.WhichOneof("Classifier")
                == "external_classifier"
            ),
            "network_used": False,
        },
        "network_used": False,
        "audio_devices_opened": False,
    }


def main() -> int:
    print(json.dumps(run_smoke(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
