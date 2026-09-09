"""Test-only Hybrid privacy surfaces, derived from contracts/recorder schema.

Metadata exemptions apply ONLY at event roots or inside validated typed models.
Unknown fields are inspected, never silently treated as metadata. No global
serialized-substring search; typed factual projections forbid extra fields.
"""
from orion.hybrid_aircraft_contracts import (
    AircraftIdentityQueryResult, FinalizedInformationalText,
    HybridAircraftDecomposition, InformationalResponsePlan,
)

# record_aircraft_slice + the generic tx_completed record used by these tests.
EVENT_METADATA = {
    "timestamp", "test_session_id", "realtime_session_id", "turn_id", "tx_id",
    "response_id", "call_id", "monotonic", "frames", "provider_call_count",
    "pure_aircraft", "radio_first_frame", "radio_completed", "tts_started",
    "tts_first_pcm", "tts_completed", "tts_pcm_bytes",
}
AIRCRAFT_METADATA = {
    "interaction_id", "receipt", "observed_at", "age_seconds", "generation", "expires_at",
}
MODELS = {"aircraft": AircraftIdentityQueryResult, "plan": InformationalResponsePlan,
          "decomposition": HybridAircraftDecomposition, "finalized": FinalizedInformationalText}
FORBIDDEN_KEYS = {"fuel", "extra_fuel", "heading", "position", "secret", "tool_result"}


def assert_content_private(value, *, forbidden_strings=("9876", "not allowed", "heading"),
                           forbidden_numbers=(9876,), forbidden_keys=FORBIDDEN_KEYS):
    """Inspect content leaves/keys, not JSON syntax or unrelated metadata."""
    if isinstance(value, dict):
        assert not (set(value) & forbidden_keys), "Unauthorized factual/content field"
        for key, child in value.items():
            assert_content_private(key, forbidden_strings=forbidden_strings,
                                   forbidden_numbers=forbidden_numbers, forbidden_keys=forbidden_keys)
            assert_content_private(child, forbidden_strings=forbidden_strings,
                                   forbidden_numbers=forbidden_numbers, forbidden_keys=forbidden_keys)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_content_private(child, forbidden_strings=forbidden_strings,
                                   forbidden_numbers=forbidden_numbers, forbidden_keys=forbidden_keys)
    elif isinstance(value, str):
        assert not any(term in value for term in forbidden_strings), "Unauthorized content text"
    elif type(value) in (int, float):
        assert value not in forbidden_numbers, "Unauthorized factual value"


def model_content(kind, value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        MODELS[kind].model_validate(value)  # extra=forbid, including nested facts/receipt.
    except (ValueError, TypeError):
        raise AssertionError("Invalid/expanded typed privacy surface") from None
    if kind == "aircraft":
        return {k: v for k, v in value.items() if k not in AIRCRAFT_METADATA}
    if kind == "plan":
        return {"language": value.get("language"), "social_acts": value.get("social_acts"),
                "aircraft": model_content("aircraft", value["aircraft"]) if value.get("aircraft") else None}
    if kind == "finalized":
        return {"plan": model_content("plan", value["plan"]), "text": value["text"]}
    # Validated span offsets are source-position metadata, not received telemetry.
    return {"language": value["language"], "acts": [span["act"] for span in value["spans"]]}


def assert_aircraft_privacy(*, finalized=None, events=(), **policy):
    if finalized is not None:
        assert_content_private(model_content("finalized", finalized), **policy)
    for event in events:
        if isinstance(event, tuple):
            name, fields = event
            event = {"event": name, **fields}
        assert isinstance(event, dict)
        for key, value in event.items():
            if key in EVENT_METADATA:
                # A dictionary hidden under a timestamp/ID is not metadata.
                assert value is None or isinstance(value, (str, int, float, bool)), "Malformed event metadata"
                continue
            if key in MODELS:
                value = model_content(key, value)
            # Unknown semantic, prompt/context or tool-projection surfaces are
            # checked recursively, with NO metadata exemptions at nested paths.
            assert_content_private({key: value}, **policy)
