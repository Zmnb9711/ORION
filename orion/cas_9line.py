from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.jtac_runtime import JtacDesignationMethod
from orion.mission_control_jtac import MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac


class Cas9LineState(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    READBACK_PENDING = "readback_pending"
    VERIFIED = "verified"
    TASKED = "tasked"
    ABORTED = "aborted"


class Cas9LineBriefCreate(BaseModel):
    target_id: str = Field(min_length=1)
    ip_or_bp: str = Field(min_length=1)
    heading_deg: int = Field(ge=0, le=359)
    distance_nm: float = Field(gt=0)
    target_elevation_ft: int
    target_description: str = Field(min_length=1)
    target_location: str = Field(min_length=1)
    mark: str = Field(min_length=1)
    friendlies: str = Field(min_length=1)
    egress: str = Field(min_length=1)
    remarks: str | None = None
    restrictions: str | None = None
    method: JtacDesignationMethod = JtacDesignationMethod.LASER
    laser_code: int | None = Field(default=1688, ge=1111, le=1788)
    smoke_color: str = "red"
    requested_asset_id: str | None = None
    language: str = "en"


class Cas9LineReadback(BaseModel):
    target_elevation_ft: int
    target_location: str = Field(min_length=1)
    restrictions: str | None = None
    remarks_acknowledged: bool = False


class Cas9LineReadbackResult(BaseModel):
    brief: "Cas9LineBrief"
    verified: bool
    mismatches: list[str] = Field(default_factory=list)


class Cas9LineBrief(BaseModel):
    brief_id: UUID = Field(default_factory=uuid4)
    state: Cas9LineState = Cas9LineState.DRAFT
    target_id: str
    ip_or_bp: str
    heading_deg: int
    distance_nm: float
    target_elevation_ft: int
    target_description: str
    target_location: str
    mark: str
    friendlies: str
    egress: str
    remarks: str | None = None
    restrictions: str | None = None
    method: JtacDesignationMethod
    laser_code: int | None = None
    smoke_color: str = "red"
    requested_asset_id: str | None = None
    language: str = "en"
    readback_verified: bool = False
    remarks_acknowledged: bool = False
    readback_mismatches: list[str] = Field(default_factory=list)
    jtac_result: MissionControlJtacResult | None = None


class Cas9LineStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._briefs: dict[UUID, Cas9LineBrief] = {}

    def create(self, payload: Cas9LineBriefCreate) -> Cas9LineBrief:
        if payload.method is JtacDesignationMethod.LASER and payload.laser_code is None:
            raise ValueError("laser_code is required for laser CAS marking")
        if payload.method is JtacDesignationMethod.SMOKE and payload.laser_code is not None:
            payload = payload.model_copy(update={"laser_code": None})
        brief = Cas9LineBrief(**payload.model_dump())
        with self._lock:
            self._briefs[brief.brief_id] = brief
        return brief.model_copy(deep=True)

    def issue(self, brief_id: UUID) -> Cas9LineBrief:
        with self._lock:
            brief = self._require(brief_id)
            if brief.state is not Cas9LineState.DRAFT:
                raise ValueError("Only draft CAS briefs can be issued")
            brief.state = Cas9LineState.READBACK_PENDING
            brief.readback_mismatches = []
            brief.remarks_acknowledged = False
            return brief.model_copy(deep=True)

    def verify_readback_result(self, brief_id: UUID, readback: Cas9LineReadback) -> Cas9LineReadbackResult:
        with self._lock:
            brief = self._require(brief_id)
            if brief.state is not Cas9LineState.READBACK_PENDING:
                raise ValueError("CAS brief is not awaiting readback")
            mismatches = self._readback_mismatches(brief, readback)
            brief.remarks_acknowledged = readback.remarks_acknowledged or not bool(brief.remarks)
            brief.readback_mismatches = mismatches
            if mismatches:
                brief.readback_verified = False
                return Cas9LineReadbackResult(brief=brief.model_copy(deep=True), verified=False, mismatches=mismatches)
            brief.readback_verified = True
            brief.readback_mismatches = []
            brief.state = Cas9LineState.VERIFIED
            return Cas9LineReadbackResult(brief=brief.model_copy(deep=True), verified=True)

    def verify_readback(self, brief_id: UUID, readback: Cas9LineReadback) -> Cas9LineBrief:
        result = self.verify_readback_result(brief_id, readback)
        if not result.verified:
            raise ValueError("Readback mismatch: " + ", ".join(result.mismatches))
        return result.brief

    def task(self, brief_id: UUID) -> Cas9LineBrief:
        with self._lock:
            brief = self._require(brief_id)
            if brief.state is not Cas9LineState.VERIFIED:
                raise ValueError("CAS 9-line must have a verified readback before tasking")
            request = MissionControlJtacRequest(
                target_id=brief.target_id,
                method=brief.method,
                laser_code=brief.laser_code,
                smoke_color=brief.smoke_color,
                requested_asset_id=brief.requested_asset_id,
                language=brief.language,
            )
        result = orchestrate_jtac(request)
        with self._lock:
            brief = self._require(brief_id)
            brief.jtac_result = result
            brief.state = Cas9LineState.TASKED if result.accepted else Cas9LineState.ABORTED
            return brief.model_copy(deep=True)

    def abort(self, brief_id: UUID) -> Cas9LineBrief:
        with self._lock:
            brief = self._require(brief_id)
            if brief.state in {Cas9LineState.TASKED, Cas9LineState.ABORTED}:
                raise ValueError("CAS brief is already finalized")
            brief.state = Cas9LineState.ABORTED
            return brief.model_copy(deep=True)

    def get(self, brief_id: UUID) -> Cas9LineBrief | None:
        with self._lock:
            brief = self._briefs.get(brief_id)
            return brief.model_copy(deep=True) if brief else None

    def list(self) -> list[Cas9LineBrief]:
        with self._lock:
            return [brief.model_copy(deep=True) for brief in self._briefs.values()]

    def reset(self) -> None:
        with self._lock:
            self._briefs.clear()

    def _readback_mismatches(self, brief: Cas9LineBrief, readback: Cas9LineReadback) -> list[str]:
        mismatches: list[str] = []
        if readback.target_elevation_ft != brief.target_elevation_ft:
            mismatches.append("target elevation")
        if _norm(readback.target_location) != _norm(brief.target_location):
            mismatches.append("target location")
        if brief.restrictions and _norm(readback.restrictions or "") != _norm(brief.restrictions):
            mismatches.append("restrictions")
        if brief.remarks and not readback.remarks_acknowledged:
            mismatches.append("remarks acknowledgement")
        return mismatches

    def _require(self, brief_id: UUID) -> Cas9LineBrief:
        brief = self._briefs.get(brief_id)
        if brief is None:
            raise KeyError("CAS 9-line brief not found")
        return brief


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


cas_9line_store = Cas9LineStore()
