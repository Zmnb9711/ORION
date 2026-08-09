from __future__ import annotations

from enum import StrEnum
from math import floor

from pydantic import BaseModel, Field, model_validator


class RunwayIdentitySource(StrEnum):
    PUBLISHED = "published"
    DCS = "dcs"
    MISSION = "mission"
    DERIVED_MAGNETIC = "derived_magnetic"


def normalize_heading_deg(course_deg: float) -> float:
    return course_deg % 360.0


def runway_number_from_magnetic_course(course_deg: float) -> int:
    """Derive the conventional numeric runway designator from magnetic course."""
    normalized = normalize_heading_deg(course_deg)
    rounded_tens = int(floor((normalized + 5.0) / 10.0)) % 36
    return 36 if rounded_tens == 0 else rounded_tens


def reciprocal_course_deg(course_deg: float) -> float:
    return normalize_heading_deg(course_deg + 180.0)


def numeric_designator(course_deg: float) -> str:
    return f"{runway_number_from_magnetic_course(course_deg):02d}"


class RunwayEndIdentity(BaseModel):
    facility_id: str = Field(min_length=1, max_length=160)
    runway_id: str = Field(min_length=1, max_length=160)
    magnetic_course_deg: float = Field(ge=0.0, lt=360.0)
    designator: str | None = Field(default=None, min_length=2, max_length=3)
    source: RunwayIdentitySource = RunwayIdentitySource.DERIVED_MAGNETIC
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    true_course_deg: float | None = Field(default=None, ge=0.0, lt=360.0)

    @model_validator(mode="after")
    def derive_or_validate_designator(self) -> "RunwayEndIdentity":
        derived = numeric_designator(self.magnetic_course_deg)
        if self.designator is None:
            self.designator = derived
            self.source = RunwayIdentitySource.DERIVED_MAGNETIC
            return self

        suffix = self.designator[2:] if len(self.designator) > 2 else ""
        if suffix and suffix not in {"L", "C", "R"}:
            raise ValueError("Runway suffix must be L, C or R")
        if not self.designator[:2].isdigit() or not 1 <= int(self.designator[:2]) <= 36:
            raise ValueError("Runway numeric designator must be 01..36")
        return self

    @property
    def numeric_designator(self) -> str:
        return self.designator[:2]

    @property
    def reciprocal_magnetic_course_deg(self) -> float:
        return reciprocal_course_deg(self.magnetic_course_deg)

    @property
    def reciprocal_numeric_designator(self) -> str:
        return numeric_designator(self.reciprocal_magnetic_course_deg)


class RunwayCourseAnswer(BaseModel):
    facility_id: str
    runway_designator: str
    magnetic_course_deg: float
    reciprocal_numeric_designator: str
    source: RunwayIdentitySource
    confidence: float = Field(ge=0.0, le=1.0)
    true_course_deg: float | None = None


def answer_runway_course(identity: RunwayEndIdentity) -> RunwayCourseAnswer:
    """Cross-domain answer object for 'what is the runway heading/course?' queries."""
    return RunwayCourseAnswer(
        facility_id=identity.facility_id,
        runway_designator=identity.designator,
        magnetic_course_deg=identity.magnetic_course_deg,
        reciprocal_numeric_designator=identity.reciprocal_numeric_designator,
        source=identity.source,
        confidence=identity.confidence,
        true_course_deg=identity.true_course_deg,
    )
