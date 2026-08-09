from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from orion.atc_operations import FreshnessClass


HPA_PER_INHG = 33.8638866667
HPA_PER_MMHG = 1.33322387415
STANDARD_PRESSURE_HPA = 1013.25


class AerodromeInformationSource(StrEnum):
    DCS = "dcs"
    MISSION = "mission"
    ATIS = "atis"
    METAR = "metar"
    EXTERNAL = "external"


class AerodromePressureObservation(BaseModel):
    """Dynamic aerodrome pressure observation used across Ground/Tower/Approach."""

    facility_id: str = Field(min_length=1, max_length=160)
    qnh_hpa: float = Field(gt=800.0, lt=1100.0)
    qfe_hpa: float | None = Field(default=None, gt=700.0, lt=1100.0)
    runway_designator: str | None = Field(default=None, min_length=2, max_length=3)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    freshness: FreshnessClass = FreshnessClass.UNKNOWN
    source: AerodromeInformationSource
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_runway_specific_qfe(self) -> "AerodromePressureObservation":
        if self.runway_designator is not None and self.qfe_hpa is None:
            raise ValueError("Runway-specific pressure observation requires QFE")
        return self

    @property
    def usable_for_current_pressure_answer(self) -> bool:
        return self.freshness in {FreshnessClass.FRESH, FreshnessClass.AGING}


class AerodromePressureAnswer(BaseModel):
    facility_id: str
    qnh_hpa: float
    qnh_inhg: float
    qnh_mmhg: float
    qfe_hpa: float | None = None
    qfe_inhg: float | None = None
    qfe_mmhg: float | None = None
    runway_designator: str | None = None
    observed_at: datetime
    freshness: FreshnessClass
    source: AerodromeInformationSource
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def is_current_enough(self) -> bool:
        return self.freshness in {FreshnessClass.FRESH, FreshnessClass.AGING}


def hpa_to_inhg(value_hpa: float) -> float:
    return value_hpa / HPA_PER_INHG


def hpa_to_mmhg(value_hpa: float) -> float:
    return value_hpa / HPA_PER_MMHG


def answer_aerodrome_pressure(observation: AerodromePressureObservation) -> AerodromePressureAnswer:
    """Build the cross-domain answer for 'what is the aerodrome pressure?' queries.

    QNH is the default aerodrome pressure answer. QFE is returned when observed for
    the aerodrome/runway datum. STANDARD is intentionally not substituted for QNH.
    """

    qfe_hpa = observation.qfe_hpa
    return AerodromePressureAnswer(
        facility_id=observation.facility_id,
        qnh_hpa=observation.qnh_hpa,
        qnh_inhg=hpa_to_inhg(observation.qnh_hpa),
        qnh_mmhg=hpa_to_mmhg(observation.qnh_hpa),
        qfe_hpa=qfe_hpa,
        qfe_inhg=hpa_to_inhg(qfe_hpa) if qfe_hpa is not None else None,
        qfe_mmhg=hpa_to_mmhg(qfe_hpa) if qfe_hpa is not None else None,
        runway_designator=observation.runway_designator,
        observed_at=observation.observed_at,
        freshness=observation.freshness,
        source=observation.source,
        confidence=observation.confidence,
    )
