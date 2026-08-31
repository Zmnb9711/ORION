# Yandex SpeechKit v3 protobuf provenance

`stt_pb2.py` and `tts_pb2.py` are generated code derived from the official
Yandex Cloud API definitions `yandex/cloud/ai/stt/v3/stt.proto` and
`yandex/cloud/ai/tts/v3/tts.proto` at cloudapi commit
`b34a789f450b5812153344e377c1a2ed74e6790b`.

Only the streaming request/response message definitions are bundled. ORION
constructs the documented `speechkit.stt.v3.Recognizer/RecognizeStreaming` and
`speechkit.tts.v3.Synthesizer/StreamSynthesis` methods directly, so unrelated
service protobuf dependencies are not shipped.

Source: https://github.com/yandex-cloud/cloudapi

The upstream repository is distributed under the Apache License 2.0.
