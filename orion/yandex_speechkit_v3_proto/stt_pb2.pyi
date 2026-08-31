from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CodeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CODE_TYPE_UNSPECIFIED: _ClassVar[CodeType]
    WORKING: _ClassVar[CodeType]
    WARNING: _ClassVar[CodeType]
    CLOSED: _ClassVar[CodeType]
CODE_TYPE_UNSPECIFIED: CodeType
WORKING: CodeType
WARNING: CodeType
CLOSED: CodeType

class TextNormalizationOptions(_message.Message):
    __slots__ = ("text_normalization", "profanity_filter", "literature_text", "phone_formatting_mode")
    class TextNormalization(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TEXT_NORMALIZATION_UNSPECIFIED: _ClassVar[TextNormalizationOptions.TextNormalization]
        TEXT_NORMALIZATION_ENABLED: _ClassVar[TextNormalizationOptions.TextNormalization]
        TEXT_NORMALIZATION_DISABLED: _ClassVar[TextNormalizationOptions.TextNormalization]
    TEXT_NORMALIZATION_UNSPECIFIED: TextNormalizationOptions.TextNormalization
    TEXT_NORMALIZATION_ENABLED: TextNormalizationOptions.TextNormalization
    TEXT_NORMALIZATION_DISABLED: TextNormalizationOptions.TextNormalization
    class PhoneFormattingMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PHONE_FORMATTING_MODE_UNSPECIFIED: _ClassVar[TextNormalizationOptions.PhoneFormattingMode]
        PHONE_FORMATTING_MODE_DISABLED: _ClassVar[TextNormalizationOptions.PhoneFormattingMode]
    PHONE_FORMATTING_MODE_UNSPECIFIED: TextNormalizationOptions.PhoneFormattingMode
    PHONE_FORMATTING_MODE_DISABLED: TextNormalizationOptions.PhoneFormattingMode
    TEXT_NORMALIZATION_FIELD_NUMBER: _ClassVar[int]
    PROFANITY_FILTER_FIELD_NUMBER: _ClassVar[int]
    LITERATURE_TEXT_FIELD_NUMBER: _ClassVar[int]
    PHONE_FORMATTING_MODE_FIELD_NUMBER: _ClassVar[int]
    text_normalization: TextNormalizationOptions.TextNormalization
    profanity_filter: bool
    literature_text: bool
    phone_formatting_mode: TextNormalizationOptions.PhoneFormattingMode
    def __init__(self, text_normalization: _Optional[_Union[TextNormalizationOptions.TextNormalization, str]] = ..., profanity_filter: _Optional[bool] = ..., literature_text: _Optional[bool] = ..., phone_formatting_mode: _Optional[_Union[TextNormalizationOptions.PhoneFormattingMode, str]] = ...) -> None: ...

class DefaultEouClassifier(_message.Message):
    __slots__ = ("type", "max_pause_between_words_hint_ms")
    class EouSensitivity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        EOU_SENSITIVITY_UNSPECIFIED: _ClassVar[DefaultEouClassifier.EouSensitivity]
        DEFAULT: _ClassVar[DefaultEouClassifier.EouSensitivity]
        HIGH: _ClassVar[DefaultEouClassifier.EouSensitivity]
    EOU_SENSITIVITY_UNSPECIFIED: DefaultEouClassifier.EouSensitivity
    DEFAULT: DefaultEouClassifier.EouSensitivity
    HIGH: DefaultEouClassifier.EouSensitivity
    TYPE_FIELD_NUMBER: _ClassVar[int]
    MAX_PAUSE_BETWEEN_WORDS_HINT_MS_FIELD_NUMBER: _ClassVar[int]
    type: DefaultEouClassifier.EouSensitivity
    max_pause_between_words_hint_ms: int
    def __init__(self, type: _Optional[_Union[DefaultEouClassifier.EouSensitivity, str]] = ..., max_pause_between_words_hint_ms: _Optional[int] = ...) -> None: ...

class ExternalEouClassifier(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class EouClassifierOptions(_message.Message):
    __slots__ = ("default_classifier", "external_classifier")
    DEFAULT_CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    default_classifier: DefaultEouClassifier
    external_classifier: ExternalEouClassifier
    def __init__(self, default_classifier: _Optional[_Union[DefaultEouClassifier, _Mapping]] = ..., external_classifier: _Optional[_Union[ExternalEouClassifier, _Mapping]] = ...) -> None: ...

class RecognitionClassifier(_message.Message):
    __slots__ = ("classifier", "triggers")
    class TriggerType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TRIGGER_TYPE_UNSPECIFIED: _ClassVar[RecognitionClassifier.TriggerType]
        ON_UTTERANCE: _ClassVar[RecognitionClassifier.TriggerType]
        ON_FINAL: _ClassVar[RecognitionClassifier.TriggerType]
        ON_PARTIAL: _ClassVar[RecognitionClassifier.TriggerType]
    TRIGGER_TYPE_UNSPECIFIED: RecognitionClassifier.TriggerType
    ON_UTTERANCE: RecognitionClassifier.TriggerType
    ON_FINAL: RecognitionClassifier.TriggerType
    ON_PARTIAL: RecognitionClassifier.TriggerType
    CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    TRIGGERS_FIELD_NUMBER: _ClassVar[int]
    classifier: str
    triggers: _containers.RepeatedScalarFieldContainer[RecognitionClassifier.TriggerType]
    def __init__(self, classifier: _Optional[str] = ..., triggers: _Optional[_Iterable[_Union[RecognitionClassifier.TriggerType, str]]] = ...) -> None: ...

class RecognitionClassifierOptions(_message.Message):
    __slots__ = ("classifiers",)
    CLASSIFIERS_FIELD_NUMBER: _ClassVar[int]
    classifiers: _containers.RepeatedCompositeFieldContainer[RecognitionClassifier]
    def __init__(self, classifiers: _Optional[_Iterable[_Union[RecognitionClassifier, _Mapping]]] = ...) -> None: ...

class SpeakerAnalysisOptions(_message.Message):
    __slots__ = ("silence_threshold_ms",)
    SILENCE_THRESHOLD_MS_FIELD_NUMBER: _ClassVar[int]
    silence_threshold_ms: int
    def __init__(self, silence_threshold_ms: _Optional[int] = ...) -> None: ...

class ConversationAnalysisOptions(_message.Message):
    __slots__ = ("simultaneous_silence_threshold_ms", "simultaneous_speech_threshold_ms")
    SIMULTANEOUS_SILENCE_THRESHOLD_MS_FIELD_NUMBER: _ClassVar[int]
    SIMULTANEOUS_SPEECH_THRESHOLD_MS_FIELD_NUMBER: _ClassVar[int]
    simultaneous_silence_threshold_ms: int
    simultaneous_speech_threshold_ms: int
    def __init__(self, simultaneous_silence_threshold_ms: _Optional[int] = ..., simultaneous_speech_threshold_ms: _Optional[int] = ...) -> None: ...

class SpeechAnalysisOptions(_message.Message):
    __slots__ = ("enable_speaker_analysis", "enable_conversation_analysis", "descriptive_statistics_quantiles", "speaker_options", "converstation_options")
    ENABLE_SPEAKER_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    ENABLE_CONVERSATION_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTIVE_STATISTICS_QUANTILES_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    CONVERSTATION_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    enable_speaker_analysis: bool
    enable_conversation_analysis: bool
    descriptive_statistics_quantiles: _containers.RepeatedScalarFieldContainer[float]
    speaker_options: SpeakerAnalysisOptions
    converstation_options: ConversationAnalysisOptions
    def __init__(self, enable_speaker_analysis: _Optional[bool] = ..., enable_conversation_analysis: _Optional[bool] = ..., descriptive_statistics_quantiles: _Optional[_Iterable[float]] = ..., speaker_options: _Optional[_Union[SpeakerAnalysisOptions, _Mapping]] = ..., converstation_options: _Optional[_Union[ConversationAnalysisOptions, _Mapping]] = ...) -> None: ...

class RawAudio(_message.Message):
    __slots__ = ("audio_encoding", "sample_rate_hertz", "audio_channel_count")
    class AudioEncoding(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        AUDIO_ENCODING_UNSPECIFIED: _ClassVar[RawAudio.AudioEncoding]
        LINEAR16_PCM: _ClassVar[RawAudio.AudioEncoding]
    AUDIO_ENCODING_UNSPECIFIED: RawAudio.AudioEncoding
    LINEAR16_PCM: RawAudio.AudioEncoding
    AUDIO_ENCODING_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_HERTZ_FIELD_NUMBER: _ClassVar[int]
    AUDIO_CHANNEL_COUNT_FIELD_NUMBER: _ClassVar[int]
    audio_encoding: RawAudio.AudioEncoding
    sample_rate_hertz: int
    audio_channel_count: int
    def __init__(self, audio_encoding: _Optional[_Union[RawAudio.AudioEncoding, str]] = ..., sample_rate_hertz: _Optional[int] = ..., audio_channel_count: _Optional[int] = ...) -> None: ...

class ContainerAudio(_message.Message):
    __slots__ = ("container_audio_type",)
    class ContainerAudioType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CONTAINER_AUDIO_TYPE_UNSPECIFIED: _ClassVar[ContainerAudio.ContainerAudioType]
        WAV: _ClassVar[ContainerAudio.ContainerAudioType]
        OGG_OPUS: _ClassVar[ContainerAudio.ContainerAudioType]
        MP3: _ClassVar[ContainerAudio.ContainerAudioType]
    CONTAINER_AUDIO_TYPE_UNSPECIFIED: ContainerAudio.ContainerAudioType
    WAV: ContainerAudio.ContainerAudioType
    OGG_OPUS: ContainerAudio.ContainerAudioType
    MP3: ContainerAudio.ContainerAudioType
    CONTAINER_AUDIO_TYPE_FIELD_NUMBER: _ClassVar[int]
    container_audio_type: ContainerAudio.ContainerAudioType
    def __init__(self, container_audio_type: _Optional[_Union[ContainerAudio.ContainerAudioType, str]] = ...) -> None: ...

class AudioFormatOptions(_message.Message):
    __slots__ = ("raw_audio", "container_audio")
    RAW_AUDIO_FIELD_NUMBER: _ClassVar[int]
    CONTAINER_AUDIO_FIELD_NUMBER: _ClassVar[int]
    raw_audio: RawAudio
    container_audio: ContainerAudio
    def __init__(self, raw_audio: _Optional[_Union[RawAudio, _Mapping]] = ..., container_audio: _Optional[_Union[ContainerAudio, _Mapping]] = ...) -> None: ...

class LanguageRestrictionOptions(_message.Message):
    __slots__ = ("restriction_type", "language_code")
    class LanguageRestrictionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        LANGUAGE_RESTRICTION_TYPE_UNSPECIFIED: _ClassVar[LanguageRestrictionOptions.LanguageRestrictionType]
        WHITELIST: _ClassVar[LanguageRestrictionOptions.LanguageRestrictionType]
        BLACKLIST: _ClassVar[LanguageRestrictionOptions.LanguageRestrictionType]
    LANGUAGE_RESTRICTION_TYPE_UNSPECIFIED: LanguageRestrictionOptions.LanguageRestrictionType
    WHITELIST: LanguageRestrictionOptions.LanguageRestrictionType
    BLACKLIST: LanguageRestrictionOptions.LanguageRestrictionType
    RESTRICTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_CODE_FIELD_NUMBER: _ClassVar[int]
    restriction_type: LanguageRestrictionOptions.LanguageRestrictionType
    language_code: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, restriction_type: _Optional[_Union[LanguageRestrictionOptions.LanguageRestrictionType, str]] = ..., language_code: _Optional[_Iterable[str]] = ...) -> None: ...

class JsonSchema(_message.Message):
    __slots__ = ("schema",)
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    schema: _struct_pb2.Struct
    def __init__(self, schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class SummarizationProperty(_message.Message):
    __slots__ = ("instruction", "json_object", "json_schema")
    INSTRUCTION_FIELD_NUMBER: _ClassVar[int]
    JSON_OBJECT_FIELD_NUMBER: _ClassVar[int]
    JSON_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    instruction: str
    json_object: bool
    json_schema: JsonSchema
    def __init__(self, instruction: _Optional[str] = ..., json_object: _Optional[bool] = ..., json_schema: _Optional[_Union[JsonSchema, _Mapping]] = ...) -> None: ...

class SummarizationOptions(_message.Message):
    __slots__ = ("model_uri", "properties")
    MODEL_URI_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    model_uri: str
    properties: _containers.RepeatedCompositeFieldContainer[SummarizationProperty]
    def __init__(self, model_uri: _Optional[str] = ..., properties: _Optional[_Iterable[_Union[SummarizationProperty, _Mapping]]] = ...) -> None: ...

class SummarizationPropertyResult(_message.Message):
    __slots__ = ("response",)
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    response: str
    def __init__(self, response: _Optional[str] = ...) -> None: ...

class RecognitionModelOptions(_message.Message):
    __slots__ = ("model", "audio_format", "text_normalization", "language_restriction", "audio_processing_type")
    class AudioProcessingType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        AUDIO_PROCESSING_TYPE_UNSPECIFIED: _ClassVar[RecognitionModelOptions.AudioProcessingType]
        REAL_TIME: _ClassVar[RecognitionModelOptions.AudioProcessingType]
        FULL_DATA: _ClassVar[RecognitionModelOptions.AudioProcessingType]
    AUDIO_PROCESSING_TYPE_UNSPECIFIED: RecognitionModelOptions.AudioProcessingType
    REAL_TIME: RecognitionModelOptions.AudioProcessingType
    FULL_DATA: RecognitionModelOptions.AudioProcessingType
    MODEL_FIELD_NUMBER: _ClassVar[int]
    AUDIO_FORMAT_FIELD_NUMBER: _ClassVar[int]
    TEXT_NORMALIZATION_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_RESTRICTION_FIELD_NUMBER: _ClassVar[int]
    AUDIO_PROCESSING_TYPE_FIELD_NUMBER: _ClassVar[int]
    model: str
    audio_format: AudioFormatOptions
    text_normalization: TextNormalizationOptions
    language_restriction: LanguageRestrictionOptions
    audio_processing_type: RecognitionModelOptions.AudioProcessingType
    def __init__(self, model: _Optional[str] = ..., audio_format: _Optional[_Union[AudioFormatOptions, _Mapping]] = ..., text_normalization: _Optional[_Union[TextNormalizationOptions, _Mapping]] = ..., language_restriction: _Optional[_Union[LanguageRestrictionOptions, _Mapping]] = ..., audio_processing_type: _Optional[_Union[RecognitionModelOptions.AudioProcessingType, str]] = ...) -> None: ...

class SpeakerLabelingOptions(_message.Message):
    __slots__ = ("speaker_labeling",)
    class SpeakerLabeling(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SPEAKER_LABELING_UNSPECIFIED: _ClassVar[SpeakerLabelingOptions.SpeakerLabeling]
        SPEAKER_LABELING_ENABLED: _ClassVar[SpeakerLabelingOptions.SpeakerLabeling]
        SPEAKER_LABELING_DISABLED: _ClassVar[SpeakerLabelingOptions.SpeakerLabeling]
    SPEAKER_LABELING_UNSPECIFIED: SpeakerLabelingOptions.SpeakerLabeling
    SPEAKER_LABELING_ENABLED: SpeakerLabelingOptions.SpeakerLabeling
    SPEAKER_LABELING_DISABLED: SpeakerLabelingOptions.SpeakerLabeling
    SPEAKER_LABELING_FIELD_NUMBER: _ClassVar[int]
    speaker_labeling: SpeakerLabelingOptions.SpeakerLabeling
    def __init__(self, speaker_labeling: _Optional[_Union[SpeakerLabelingOptions.SpeakerLabeling, str]] = ...) -> None: ...

class StreamingOptions(_message.Message):
    __slots__ = ("recognition_model", "eou_classifier", "recognition_classifier", "speech_analysis", "speaker_labeling", "summarization")
    RECOGNITION_MODEL_FIELD_NUMBER: _ClassVar[int]
    EOU_CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    RECOGNITION_CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    SPEECH_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_LABELING_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZATION_FIELD_NUMBER: _ClassVar[int]
    recognition_model: RecognitionModelOptions
    eou_classifier: EouClassifierOptions
    recognition_classifier: RecognitionClassifierOptions
    speech_analysis: SpeechAnalysisOptions
    speaker_labeling: SpeakerLabelingOptions
    summarization: SummarizationOptions
    def __init__(self, recognition_model: _Optional[_Union[RecognitionModelOptions, _Mapping]] = ..., eou_classifier: _Optional[_Union[EouClassifierOptions, _Mapping]] = ..., recognition_classifier: _Optional[_Union[RecognitionClassifierOptions, _Mapping]] = ..., speech_analysis: _Optional[_Union[SpeechAnalysisOptions, _Mapping]] = ..., speaker_labeling: _Optional[_Union[SpeakerLabelingOptions, _Mapping]] = ..., summarization: _Optional[_Union[SummarizationOptions, _Mapping]] = ...) -> None: ...

class AudioChunk(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    def __init__(self, data: _Optional[bytes] = ...) -> None: ...

class SilenceChunk(_message.Message):
    __slots__ = ("duration_ms",)
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    duration_ms: int
    def __init__(self, duration_ms: _Optional[int] = ...) -> None: ...

class Eou(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StreamingRequest(_message.Message):
    __slots__ = ("session_options", "chunk", "silence_chunk", "eou")
    SESSION_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    SILENCE_CHUNK_FIELD_NUMBER: _ClassVar[int]
    EOU_FIELD_NUMBER: _ClassVar[int]
    session_options: StreamingOptions
    chunk: AudioChunk
    silence_chunk: SilenceChunk
    eou: Eou
    def __init__(self, session_options: _Optional[_Union[StreamingOptions, _Mapping]] = ..., chunk: _Optional[_Union[AudioChunk, _Mapping]] = ..., silence_chunk: _Optional[_Union[SilenceChunk, _Mapping]] = ..., eou: _Optional[_Union[Eou, _Mapping]] = ...) -> None: ...

class RecognizeFileRequest(_message.Message):
    __slots__ = ("content", "uri", "recognition_model", "recognition_classifier", "speech_analysis", "speaker_labeling", "summarization")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    URI_FIELD_NUMBER: _ClassVar[int]
    RECOGNITION_MODEL_FIELD_NUMBER: _ClassVar[int]
    RECOGNITION_CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    SPEECH_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_LABELING_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZATION_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    uri: str
    recognition_model: RecognitionModelOptions
    recognition_classifier: RecognitionClassifierOptions
    speech_analysis: SpeechAnalysisOptions
    speaker_labeling: SpeakerLabelingOptions
    summarization: SummarizationOptions
    def __init__(self, content: _Optional[bytes] = ..., uri: _Optional[str] = ..., recognition_model: _Optional[_Union[RecognitionModelOptions, _Mapping]] = ..., recognition_classifier: _Optional[_Union[RecognitionClassifierOptions, _Mapping]] = ..., speech_analysis: _Optional[_Union[SpeechAnalysisOptions, _Mapping]] = ..., speaker_labeling: _Optional[_Union[SpeakerLabelingOptions, _Mapping]] = ..., summarization: _Optional[_Union[SummarizationOptions, _Mapping]] = ...) -> None: ...

class Word(_message.Message):
    __slots__ = ("text", "start_time_ms", "end_time_ms")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    START_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    text: str
    start_time_ms: int
    end_time_ms: int
    def __init__(self, text: _Optional[str] = ..., start_time_ms: _Optional[int] = ..., end_time_ms: _Optional[int] = ...) -> None: ...

class LanguageEstimation(_message.Message):
    __slots__ = ("language_code", "probability")
    LANGUAGE_CODE_FIELD_NUMBER: _ClassVar[int]
    PROBABILITY_FIELD_NUMBER: _ClassVar[int]
    language_code: str
    probability: float
    def __init__(self, language_code: _Optional[str] = ..., probability: _Optional[float] = ...) -> None: ...

class Alternative(_message.Message):
    __slots__ = ("words", "text", "start_time_ms", "end_time_ms", "confidence", "languages")
    WORDS_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    START_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    LANGUAGES_FIELD_NUMBER: _ClassVar[int]
    words: _containers.RepeatedCompositeFieldContainer[Word]
    text: str
    start_time_ms: int
    end_time_ms: int
    confidence: float
    languages: _containers.RepeatedCompositeFieldContainer[LanguageEstimation]
    def __init__(self, words: _Optional[_Iterable[_Union[Word, _Mapping]]] = ..., text: _Optional[str] = ..., start_time_ms: _Optional[int] = ..., end_time_ms: _Optional[int] = ..., confidence: _Optional[float] = ..., languages: _Optional[_Iterable[_Union[LanguageEstimation, _Mapping]]] = ...) -> None: ...

class EouUpdate(_message.Message):
    __slots__ = ("time_ms",)
    TIME_MS_FIELD_NUMBER: _ClassVar[int]
    time_ms: int
    def __init__(self, time_ms: _Optional[int] = ...) -> None: ...

class AlternativeUpdate(_message.Message):
    __slots__ = ("alternatives", "channel_tag")
    ALTERNATIVES_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TAG_FIELD_NUMBER: _ClassVar[int]
    alternatives: _containers.RepeatedCompositeFieldContainer[Alternative]
    channel_tag: str
    def __init__(self, alternatives: _Optional[_Iterable[_Union[Alternative, _Mapping]]] = ..., channel_tag: _Optional[str] = ...) -> None: ...

class AudioCursors(_message.Message):
    __slots__ = ("received_data_ms", "reset_time_ms", "partial_time_ms", "final_time_ms", "final_index", "eou_time_ms")
    RECEIVED_DATA_MS_FIELD_NUMBER: _ClassVar[int]
    RESET_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    FINAL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    FINAL_INDEX_FIELD_NUMBER: _ClassVar[int]
    EOU_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    received_data_ms: int
    reset_time_ms: int
    partial_time_ms: int
    final_time_ms: int
    final_index: int
    eou_time_ms: int
    def __init__(self, received_data_ms: _Optional[int] = ..., reset_time_ms: _Optional[int] = ..., partial_time_ms: _Optional[int] = ..., final_time_ms: _Optional[int] = ..., final_index: _Optional[int] = ..., eou_time_ms: _Optional[int] = ...) -> None: ...

class FinalRefinement(_message.Message):
    __slots__ = ("final_index", "normalized_text")
    FINAL_INDEX_FIELD_NUMBER: _ClassVar[int]
    NORMALIZED_TEXT_FIELD_NUMBER: _ClassVar[int]
    final_index: int
    normalized_text: AlternativeUpdate
    def __init__(self, final_index: _Optional[int] = ..., normalized_text: _Optional[_Union[AlternativeUpdate, _Mapping]] = ...) -> None: ...

class StatusCode(_message.Message):
    __slots__ = ("code_type", "message")
    CODE_TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code_type: CodeType
    message: str
    def __init__(self, code_type: _Optional[_Union[CodeType, str]] = ..., message: _Optional[str] = ...) -> None: ...

class SessionUuid(_message.Message):
    __slots__ = ("uuid", "user_request_id")
    UUID_FIELD_NUMBER: _ClassVar[int]
    USER_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    uuid: str
    user_request_id: str
    def __init__(self, uuid: _Optional[str] = ..., user_request_id: _Optional[str] = ...) -> None: ...

class PhraseHighlight(_message.Message):
    __slots__ = ("text", "start_time_ms", "end_time_ms")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    START_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    text: str
    start_time_ms: int
    end_time_ms: int
    def __init__(self, text: _Optional[str] = ..., start_time_ms: _Optional[int] = ..., end_time_ms: _Optional[int] = ...) -> None: ...

class RecognitionClassifierLabel(_message.Message):
    __slots__ = ("label", "confidence")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    label: str
    confidence: float
    def __init__(self, label: _Optional[str] = ..., confidence: _Optional[float] = ...) -> None: ...

class RecognitionClassifierResult(_message.Message):
    __slots__ = ("classifier", "highlights", "labels")
    CLASSIFIER_FIELD_NUMBER: _ClassVar[int]
    HIGHLIGHTS_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    classifier: str
    highlights: _containers.RepeatedCompositeFieldContainer[PhraseHighlight]
    labels: _containers.RepeatedCompositeFieldContainer[RecognitionClassifierLabel]
    def __init__(self, classifier: _Optional[str] = ..., highlights: _Optional[_Iterable[_Union[PhraseHighlight, _Mapping]]] = ..., labels: _Optional[_Iterable[_Union[RecognitionClassifierLabel, _Mapping]]] = ...) -> None: ...

class RecognitionClassifierUpdate(_message.Message):
    __slots__ = ("window_type", "start_time_ms", "end_time_ms", "classifier_result")
    class WindowType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        WINDOW_TYPE_UNSPECIFIED: _ClassVar[RecognitionClassifierUpdate.WindowType]
        LAST_UTTERANCE: _ClassVar[RecognitionClassifierUpdate.WindowType]
        LAST_FINAL: _ClassVar[RecognitionClassifierUpdate.WindowType]
        LAST_PARTIAL: _ClassVar[RecognitionClassifierUpdate.WindowType]
    WINDOW_TYPE_UNSPECIFIED: RecognitionClassifierUpdate.WindowType
    LAST_UTTERANCE: RecognitionClassifierUpdate.WindowType
    LAST_FINAL: RecognitionClassifierUpdate.WindowType
    LAST_PARTIAL: RecognitionClassifierUpdate.WindowType
    WINDOW_TYPE_FIELD_NUMBER: _ClassVar[int]
    START_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    CLASSIFIER_RESULT_FIELD_NUMBER: _ClassVar[int]
    window_type: RecognitionClassifierUpdate.WindowType
    start_time_ms: int
    end_time_ms: int
    classifier_result: RecognitionClassifierResult
    def __init__(self, window_type: _Optional[_Union[RecognitionClassifierUpdate.WindowType, str]] = ..., start_time_ms: _Optional[int] = ..., end_time_ms: _Optional[int] = ..., classifier_result: _Optional[_Union[RecognitionClassifierResult, _Mapping]] = ...) -> None: ...

class DescriptiveStatistics(_message.Message):
    __slots__ = ("min", "max", "mean", "std", "quantiles")
    class Quantile(_message.Message):
        __slots__ = ("level", "value")
        LEVEL_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        level: float
        value: float
        def __init__(self, level: _Optional[float] = ..., value: _Optional[float] = ...) -> None: ...
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    MEAN_FIELD_NUMBER: _ClassVar[int]
    STD_FIELD_NUMBER: _ClassVar[int]
    QUANTILES_FIELD_NUMBER: _ClassVar[int]
    min: float
    max: float
    mean: float
    std: float
    quantiles: _containers.RepeatedCompositeFieldContainer[DescriptiveStatistics.Quantile]
    def __init__(self, min: _Optional[float] = ..., max: _Optional[float] = ..., mean: _Optional[float] = ..., std: _Optional[float] = ..., quantiles: _Optional[_Iterable[_Union[DescriptiveStatistics.Quantile, _Mapping]]] = ...) -> None: ...

class AudioSegmentBoundaries(_message.Message):
    __slots__ = ("start_time_ms", "end_time_ms")
    START_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    start_time_ms: int
    end_time_ms: int
    def __init__(self, start_time_ms: _Optional[int] = ..., end_time_ms: _Optional[int] = ...) -> None: ...

class SpeakerAnalysis(_message.Message):
    __slots__ = ("speaker_tag", "window_type", "speech_boundaries", "total_speech_ms", "speech_ratio", "total_silence_ms", "silence_ratio", "words_count", "letters_count", "words_per_second", "letters_per_second", "words_per_utterance", "letters_per_utterance", "utterance_count", "utterance_duration_estimation")
    class WindowType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        WINDOW_TYPE_UNSPECIFIED: _ClassVar[SpeakerAnalysis.WindowType]
        TOTAL: _ClassVar[SpeakerAnalysis.WindowType]
        LAST_UTTERANCE: _ClassVar[SpeakerAnalysis.WindowType]
    WINDOW_TYPE_UNSPECIFIED: SpeakerAnalysis.WindowType
    TOTAL: SpeakerAnalysis.WindowType
    LAST_UTTERANCE: SpeakerAnalysis.WindowType
    SPEAKER_TAG_FIELD_NUMBER: _ClassVar[int]
    WINDOW_TYPE_FIELD_NUMBER: _ClassVar[int]
    SPEECH_BOUNDARIES_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SPEECH_MS_FIELD_NUMBER: _ClassVar[int]
    SPEECH_RATIO_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SILENCE_MS_FIELD_NUMBER: _ClassVar[int]
    SILENCE_RATIO_FIELD_NUMBER: _ClassVar[int]
    WORDS_COUNT_FIELD_NUMBER: _ClassVar[int]
    LETTERS_COUNT_FIELD_NUMBER: _ClassVar[int]
    WORDS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    LETTERS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    WORDS_PER_UTTERANCE_FIELD_NUMBER: _ClassVar[int]
    LETTERS_PER_UTTERANCE_FIELD_NUMBER: _ClassVar[int]
    UTTERANCE_COUNT_FIELD_NUMBER: _ClassVar[int]
    UTTERANCE_DURATION_ESTIMATION_FIELD_NUMBER: _ClassVar[int]
    speaker_tag: str
    window_type: SpeakerAnalysis.WindowType
    speech_boundaries: AudioSegmentBoundaries
    total_speech_ms: int
    speech_ratio: float
    total_silence_ms: int
    silence_ratio: float
    words_count: int
    letters_count: int
    words_per_second: DescriptiveStatistics
    letters_per_second: DescriptiveStatistics
    words_per_utterance: DescriptiveStatistics
    letters_per_utterance: DescriptiveStatistics
    utterance_count: int
    utterance_duration_estimation: DescriptiveStatistics
    def __init__(self, speaker_tag: _Optional[str] = ..., window_type: _Optional[_Union[SpeakerAnalysis.WindowType, str]] = ..., speech_boundaries: _Optional[_Union[AudioSegmentBoundaries, _Mapping]] = ..., total_speech_ms: _Optional[int] = ..., speech_ratio: _Optional[float] = ..., total_silence_ms: _Optional[int] = ..., silence_ratio: _Optional[float] = ..., words_count: _Optional[int] = ..., letters_count: _Optional[int] = ..., words_per_second: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., letters_per_second: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., words_per_utterance: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., letters_per_utterance: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., utterance_count: _Optional[int] = ..., utterance_duration_estimation: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ...) -> None: ...

class ConversationAnalysis(_message.Message):
    __slots__ = ("conversation_boundaries", "total_simultaneous_silence_duration_ms", "total_simultaneous_silence_ratio", "simultaneous_silence_duration_estimation", "total_simultaneous_speech_duration_ms", "total_simultaneous_speech_ratio", "simultaneous_speech_duration_estimation", "speaker_interrupts", "total_speech_duration_ms", "total_speech_ratio")
    class InterruptsEvaluation(_message.Message):
        __slots__ = ("speaker_tag", "interrupts_count", "interrupts_duration_ms", "interrupts")
        SPEAKER_TAG_FIELD_NUMBER: _ClassVar[int]
        INTERRUPTS_COUNT_FIELD_NUMBER: _ClassVar[int]
        INTERRUPTS_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
        INTERRUPTS_FIELD_NUMBER: _ClassVar[int]
        speaker_tag: str
        interrupts_count: int
        interrupts_duration_ms: int
        interrupts: _containers.RepeatedCompositeFieldContainer[AudioSegmentBoundaries]
        def __init__(self, speaker_tag: _Optional[str] = ..., interrupts_count: _Optional[int] = ..., interrupts_duration_ms: _Optional[int] = ..., interrupts: _Optional[_Iterable[_Union[AudioSegmentBoundaries, _Mapping]]] = ...) -> None: ...
    CONVERSATION_BOUNDARIES_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIMULTANEOUS_SILENCE_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIMULTANEOUS_SILENCE_RATIO_FIELD_NUMBER: _ClassVar[int]
    SIMULTANEOUS_SILENCE_DURATION_ESTIMATION_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIMULTANEOUS_SPEECH_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIMULTANEOUS_SPEECH_RATIO_FIELD_NUMBER: _ClassVar[int]
    SIMULTANEOUS_SPEECH_DURATION_ESTIMATION_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_INTERRUPTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SPEECH_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SPEECH_RATIO_FIELD_NUMBER: _ClassVar[int]
    conversation_boundaries: AudioSegmentBoundaries
    total_simultaneous_silence_duration_ms: int
    total_simultaneous_silence_ratio: float
    simultaneous_silence_duration_estimation: DescriptiveStatistics
    total_simultaneous_speech_duration_ms: int
    total_simultaneous_speech_ratio: float
    simultaneous_speech_duration_estimation: DescriptiveStatistics
    speaker_interrupts: _containers.RepeatedCompositeFieldContainer[ConversationAnalysis.InterruptsEvaluation]
    total_speech_duration_ms: int
    total_speech_ratio: float
    def __init__(self, conversation_boundaries: _Optional[_Union[AudioSegmentBoundaries, _Mapping]] = ..., total_simultaneous_silence_duration_ms: _Optional[int] = ..., total_simultaneous_silence_ratio: _Optional[float] = ..., simultaneous_silence_duration_estimation: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., total_simultaneous_speech_duration_ms: _Optional[int] = ..., total_simultaneous_speech_ratio: _Optional[float] = ..., simultaneous_speech_duration_estimation: _Optional[_Union[DescriptiveStatistics, _Mapping]] = ..., speaker_interrupts: _Optional[_Iterable[_Union[ConversationAnalysis.InterruptsEvaluation, _Mapping]]] = ..., total_speech_duration_ms: _Optional[int] = ..., total_speech_ratio: _Optional[float] = ...) -> None: ...

class ContentUsage(_message.Message):
    __slots__ = ("input_text_tokens", "completion_tokens", "total_tokens")
    INPUT_TEXT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TOKENS_FIELD_NUMBER: _ClassVar[int]
    input_text_tokens: int
    completion_tokens: int
    total_tokens: int
    def __init__(self, input_text_tokens: _Optional[int] = ..., completion_tokens: _Optional[int] = ..., total_tokens: _Optional[int] = ...) -> None: ...

class Summarization(_message.Message):
    __slots__ = ("results", "content_usage")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    CONTENT_USAGE_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[SummarizationPropertyResult]
    content_usage: ContentUsage
    def __init__(self, results: _Optional[_Iterable[_Union[SummarizationPropertyResult, _Mapping]]] = ..., content_usage: _Optional[_Union[ContentUsage, _Mapping]] = ...) -> None: ...

class StreamingResponse(_message.Message):
    __slots__ = ("session_uuid", "audio_cursors", "response_wall_time_ms", "partial", "final", "eou_update", "final_refinement", "status_code", "classifier_update", "speaker_analysis", "conversation_analysis", "summarization", "channel_tag")
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    AUDIO_CURSORS_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_WALL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_FIELD_NUMBER: _ClassVar[int]
    FINAL_FIELD_NUMBER: _ClassVar[int]
    EOU_UPDATE_FIELD_NUMBER: _ClassVar[int]
    FINAL_REFINEMENT_FIELD_NUMBER: _ClassVar[int]
    STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    CLASSIFIER_UPDATE_FIELD_NUMBER: _ClassVar[int]
    SPEAKER_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ANALYSIS_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZATION_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TAG_FIELD_NUMBER: _ClassVar[int]
    session_uuid: SessionUuid
    audio_cursors: AudioCursors
    response_wall_time_ms: int
    partial: AlternativeUpdate
    final: AlternativeUpdate
    eou_update: EouUpdate
    final_refinement: FinalRefinement
    status_code: StatusCode
    classifier_update: RecognitionClassifierUpdate
    speaker_analysis: SpeakerAnalysis
    conversation_analysis: ConversationAnalysis
    summarization: Summarization
    channel_tag: str
    def __init__(self, session_uuid: _Optional[_Union[SessionUuid, _Mapping]] = ..., audio_cursors: _Optional[_Union[AudioCursors, _Mapping]] = ..., response_wall_time_ms: _Optional[int] = ..., partial: _Optional[_Union[AlternativeUpdate, _Mapping]] = ..., final: _Optional[_Union[AlternativeUpdate, _Mapping]] = ..., eou_update: _Optional[_Union[EouUpdate, _Mapping]] = ..., final_refinement: _Optional[_Union[FinalRefinement, _Mapping]] = ..., status_code: _Optional[_Union[StatusCode, _Mapping]] = ..., classifier_update: _Optional[_Union[RecognitionClassifierUpdate, _Mapping]] = ..., speaker_analysis: _Optional[_Union[SpeakerAnalysis, _Mapping]] = ..., conversation_analysis: _Optional[_Union[ConversationAnalysis, _Mapping]] = ..., summarization: _Optional[_Union[Summarization, _Mapping]] = ..., channel_tag: _Optional[str] = ...) -> None: ...

class DeleteRecognitionRequest(_message.Message):
    __slots__ = ("operation_id",)
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    operation_id: str
    def __init__(self, operation_id: _Optional[str] = ...) -> None: ...

class StreamingResponseList(_message.Message):
    __slots__ = ("streaming_responses",)
    STREAMING_RESPONSES_FIELD_NUMBER: _ClassVar[int]
    streaming_responses: _containers.RepeatedCompositeFieldContainer[StreamingResponse]
    def __init__(self, streaming_responses: _Optional[_Iterable[_Union[StreamingResponse, _Mapping]]] = ...) -> None: ...
