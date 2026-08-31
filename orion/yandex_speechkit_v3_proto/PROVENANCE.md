# Yandex SpeechKit v3 protobuf provenance

`stt_pb2.py` is generated code derived from the official Yandex Cloud API
definition `yandex/cloud/ai/stt/v3/stt.proto` at cloudapi commit
`b34a789f450b5812153344e377c1a2ed74e6790b`.

Only the streaming request/response message definitions are bundled. ORION
constructs the documented `speechkit.stt.v3.Recognizer/RecognizeStreaming`
method directly, so unrelated asynchronous-service protobuf dependencies are
not shipped.

Source: https://github.com/yandex-cloud/cloudapi

The upstream repository is distributed under the Apache License 2.0.
