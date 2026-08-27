from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.interaction_contracts import ContextReference
from orion.radio_contracts import (
    MAX_FINALIZED_PCM_BYTES,
    REQUIRED_TX_CAPABILITIES,
    FinalizedPcmAudio,
    PcmSampleFormat,
    RadioContext,
    RadioEntityRef,
    RadioModulation,
    RadioTransportCapability,
)


def _context(**updates: object) -> RadioContext:
    values: dict[str, object] = {
        "tx_correlation_id": "radio-contract-1",
        "source_domain": CommunicationDomain.AWACS_GCI,
        "radio_entity": RadioEntityRef(
            entity_id="awacs.magic-1",
            operational_callsign="Magic 1",
            coalition="blue",
        ),
        "target_frequency_hz": 251_000_000,
        "modulation": RadioModulation.AM,
        "communication_priority": CommunicationPriority.IMPORTANT,
        "interaction_id": uuid4(),
        "session_id": "session-1",
        "turn_id": "turn-1",
        "provenance": (
            ContextReference(context_type="world.radio", reference_id="comm1-42"),
        ),
    }
    values.update(updates)
    return RadioContext(**values)


def test_radio_context_represents_the_current_srs_use_case_and_is_immutable() -> None:
    context = _context()

    assert context.target_frequency_hz == 251_000_000
    assert context.modulation is RadioModulation.AM
    assert context.radio_entity.operational_callsign == "Magic 1"
    assert context.radio_entity.coalition == "blue"
    assert REQUIRED_TX_CAPABILITIES == {
        RadioTransportCapability.TX_AUDIO,
        RadioTransportCapability.TX_COMPLETION,
        RadioTransportCapability.FREQUENCY,
        RadioTransportCapability.MODULATION,
    }
    with pytest.raises(ValidationError):
        context.target_frequency_hz = 264_500_000  # type: ignore[misc]


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"target_frequency_hz": 0}, "greater than 0"),
        ({"target_frequency_hz": float("nan")}, "finite number"),
        ({"modulation": "ssb"}, "Input should be 'am' or 'fm'"),
        ({"source_domain": "weather"}, "Input should be"),
        ({"tx_correlation_id": "contains whitespace"}, "string_pattern_mismatch"),
    ],
)
def test_radio_context_rejects_invalid_resolved_values(
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        _context(**updates)
    assert message in str(error.value)


@pytest.mark.parametrize(
    "entity",
    [
        {"entity_id": "", "operational_callsign": "Magic 1"},
        {"entity_id": "bad entity", "operational_callsign": "Magic 1"},
        {"entity_id": "magic-1", "operational_callsign": ""},
        {
            "entity_id": "magic-1",
            "operational_callsign": "Magic 1",
            "coalition": "BLUE",
        },
    ],
)
def test_radio_entity_reference_is_minimal_and_validated(
    entity: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        RadioEntityRef(**entity)


def test_radio_context_provenance_is_bounded_and_unique() -> None:
    duplicate = ContextReference(context_type="world.radio", reference_id="comm1")
    with pytest.raises(ValidationError, match="must be unique"):
        _context(provenance=(duplicate, duplicate))

    excessive = tuple(
        ContextReference(context_type="world.radio", reference_id=f"comm-{index}")
        for index in range(17)
    )
    with pytest.raises(ValidationError, match="bounded limit"):
        _context(provenance=excessive)


def test_finalized_audio_is_bounded_mono_pcm16_and_immutable() -> None:
    audio = FinalizedPcmAudio(pcm=b"\x00\x01" * 441, sample_rate_hz=44_100)

    assert audio.sample_format is PcmSampleFormat.SIGNED_16_LE
    assert audio.channels == 1
    with pytest.raises(ValidationError):
        audio.sample_rate_hz = 16_000  # type: ignore[misc]
    with pytest.raises(ValidationError, match="complete signed-16 sample frames"):
        FinalizedPcmAudio(pcm=b"\x00\x01\x02", sample_rate_hz=44_100)
    with pytest.raises(ValidationError):
        FinalizedPcmAudio(
            pcm=b"\x00\x00" * ((MAX_FINALIZED_PCM_BYTES // 2) + 1),
            sample_rate_hz=44_100,
        )
    with pytest.raises(ValidationError):
        FinalizedPcmAudio(pcm=b"\x00\x00", sample_rate_hz=44_100, channels=2)


def test_generic_contracts_do_not_duplicate_transport_or_world_state() -> None:
    fields = set(RadioContext.model_fields)
    forbidden = {
        "srs_guid",
        "srs_radio_index",
        "radio_info",
        "udp_registration_state",
        "cockpit_payload",
        "world_model_snapshot",
        "communication_profile_id",
        "provider_configuration",
        "api_key",
        "srs_password",
    }

    assert fields.isdisjoint(forbidden)
    assert set(RadioEntityRef.model_fields) == {
        "entity_id",
        "operational_callsign",
        "coalition",
    }


def test_generic_radio_modules_have_no_srs_provider_or_phraseology_imports() -> None:
    repository = Path(__file__).resolve().parents[1]
    source = "\n".join(
        (repository / "orion" / name).read_text(encoding="utf-8").lower()
        for name in ("radio_contracts.py", "radio_router.py")
    )

    for forbidden in (
        "srs_protocol",
        "srs_transport",
        "yandex",
        "qwen",
        "world_model",
        "phraseology",
        "operationalsemanticunit",
    ):
        assert forbidden not in source


def test_adapter_result_requires_aware_ordered_timestamps() -> None:
    from orion.radio_contracts import RadioAdapterOutcome, RadioAdapterTxResult

    now = datetime.now(UTC)
    result = RadioAdapterTxResult(
        tx_correlation_id="radio-contract-1",
        outcome=RadioAdapterOutcome.COMPLETED,
        started_at=now,
        completed_at=now,
    )
    assert result.completed_at == now
    with pytest.raises(ValidationError, match="timezone-aware"):
        RadioAdapterTxResult(
            tx_correlation_id="radio-contract-1",
            outcome=RadioAdapterOutcome.COMPLETED,
            completed_at=datetime.now(),
        )
