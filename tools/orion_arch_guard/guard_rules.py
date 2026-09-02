from __future__ import annotations

from typing import Any

AG3_RULESET_VERSION = "1"

# The values below were recovered from exact field-evidence archives and their
# historical differential.  Boundaries remain explicit because the historical
# Realtime and current Planner measurements are not directly interchangeable.
PERFORMANCE_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "id": "STAGE6A_REALTIME_FIRST_AUDIO_MEDIAN_A",
        "name": "Stage 6A.1 warm Realtime response-created to first audio median",
        "capability": "NATURAL_INFORMATIONAL_PRESENTATION",
        "implementation": "STAGE6A_FLIGHTCONTEXT_REALTIME",
        "metric": "provider_first_audio_latency",
        "value": 938.0,
        "unit": "ms",
        "boundary": "response.created -> first provider audio",
        "statistic": "MEDIAN",
        "sample_count": 17,
        "comparability": "DIFFERENT_BOUNDARY",
        "evidence": "STAGE6A_FIELD_20260825",
        "preferred_source_item": "source:item:runtime_artifact:9f1d828bc61b64abe960654056fe28041fe11ffc485d3e0dbdd81e4fb2a605f9",
    },
    {
        "id": "STAGE6A_REALTIME_FIRST_AUDIO_MEDIAN_B",
        "name": "Stage 6A.1 second warm Realtime response-created to first audio median",
        "capability": "NATURAL_INFORMATIONAL_PRESENTATION",
        "implementation": "STAGE6A_FLIGHTCONTEXT_REALTIME",
        "metric": "provider_first_audio_latency",
        "value": 758.0,
        "unit": "ms",
        "boundary": "response.created -> first provider audio",
        "statistic": "MEDIAN",
        "sample_count": 10,
        "comparability": "DIFFERENT_BOUNDARY",
        "evidence": "STAGE6A_FIELD_20260825",
        "preferred_source_item": "source:item:runtime_artifact:8d9552bb45f6d32fb689f6c0291a9c7df7902ec1b30b1557c279af5ce2b49540",
    },
    {
        "id": "CURRENT_QWEN_FORMULATION_FA18",
        "name": "Current F/A-18 aircraft identity Qwen formulation latency",
        "capability": "NATURAL_INFORMATIONAL_PRESENTATION",
        "implementation": "CURRENT_QWEN_INFORMATIONAL_FORMULATION",
        "metric": "formulation_latency",
        "value": 17233.793,
        "unit": "ms",
        "boundary": "Planner formulation request -> completed structured formulation",
        "statistic": "OBSERVATION",
        "sample_count": 1,
        "comparability": "CURRENT_BASELINE",
        "evidence": "AIRCRAFT_FA18_FIELD",
    },
    {
        "id": "CURRENT_QWEN_FORMULATION_F5",
        "name": "Current F-5 aircraft identity Qwen formulation latency",
        "capability": "NATURAL_INFORMATIONAL_PRESENTATION",
        "implementation": "CURRENT_QWEN_INFORMATIONAL_FORMULATION",
        "metric": "formulation_latency",
        "value": 14516.470,
        "unit": "ms",
        "boundary": "Planner formulation request -> completed structured formulation",
        "statistic": "OBSERVATION",
        "sample_count": 1,
        "comparability": "CURRENT_BASELINE",
        "evidence": "AIRCRAFT_F5_FIELD",
    },
)

RULE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "natural_information": (
        "AIRCRAFT_IDENTITY",
        "LIVE_DCS_FACT_PRESENTATION",
        "NATURAL_INFORMATIONAL_PRESENTATION",
        "QWEN_PLANNER",
        "YANDEX_REALTIME",
        "SPEECHKIT_TTS",
        "SRS",
    ),
    "packet_gap": ("PTT", "EOU", "UDP7082", "SRS", "RADIO_SCHEDULING"),
    "hard_language_modes": ("LANGUAGE_POLICY", "COMMUNICATION_PROFILE"),
    "whisper": ("STT", "SPEECHKIT_STT", "AUDIO_IO", "LIFECYCLE"),
    "protected_qwen": (
        "PHRASEOLOGY",
        "OSU",
        "PROTECTED_OPERATIONAL_COMMUNICATION",
        "QWEN_PLANNER",
    ),
    "phraseology_limit": ("PHRASEOLOGY", "MIXED_COMMUNICATION"),
    "manual_callsign": ("CALLSIGN", "MISSION_TRUTH", "DCS_TELEMETRY", "LAUNCHER"),
    "rebuild_srs": ("SRS", "RADIO_ROUTER", "PTT", "EOU", "UDP7082"),
}

ARCHITECTURE_SENSITIVE_CAPABILITIES = frozenset(
    {
        "MISSION_TRUTH",
        "AIRCRAFT_IDENTITY",
        "CALLSIGN",
        "NATURAL_INFORMATIONAL_PRESENTATION",
        "LIVE_DCS_FACT_PRESENTATION",
        "PROTECTED_OPERATIONAL_COMMUNICATION",
        "INTERACTION_ROUTING",
        "QWEN_PLANNER",
        "YANDEX_REALTIME",
        "STT",
        "SPEECHKIT_STT",
        "SRS",
        "RADIO_ROUTER",
        "PTT",
        "EOU",
        "UDP7082",
        "PHRASEOLOGY",
        "OSU",
        "SECURITY",
        "CREDENTIALS",
        "PERSISTENT_STATE",
        "LIFECYCLE",
    }
)

MODE_ESCALATION_TERMS = (
    "replace",
    "restore",
    "rebuild",
    "new provider",
    "authoritative",
    "ownership",
    "owner",
    "session model",
    "persistent session",
    "fallback",
    "rewrite",
    "transport",
    "fact authority",
    "замен",
    "восстанов",
    "владел",
    "авторитет",
)
