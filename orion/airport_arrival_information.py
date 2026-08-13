from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from orion.aerodrome_information import AerodromePressureObservation, answer_aerodrome_pressure
from orion.airport_arrival_requests import ArrivalRequestIntent
from orion.airport_arrival_runtime import AirportArrivalRuntime


class ArrivalInformationKind(StrEnum):
    QNH = "qnh"
    ASSIGNED_RUNWAY = "assigned_runway"


class ArrivalInformationAnswer(BaseModel):
    kind: ArrivalInformationKind
    text_en: str = Field(min_length=1)
    text_ru: str = Field(min_length=1)
    data: dict[str, str | float] = Field(default_factory=dict)


class AirportArrivalInformationController:
    """Answers factual arrival queries from current ORION mission/aerodrome state."""

    def __init__(self, runtime: AirportArrivalRuntime) -> None:
        self.runtime = runtime

    def answer(
        self,
        *,
        session_id: UUID,
        intent: ArrivalRequestIntent,
        pressure: AerodromePressureObservation | None = None,
    ) -> ArrivalInformationAnswer:
        session = self.runtime.get(session_id)
        if session is None:
            raise KeyError("Airport arrival session not found")

        if intent is ArrivalRequestIntent.REQUEST_ACTIVE_RUNWAY:
            return ArrivalInformationAnswer(
                kind=ArrivalInformationKind.ASSIGNED_RUNWAY,
                text_en=f"Assigned runway {session.runway_id}.",
                text_ru=f"Назначена полоса {session.runway_id}.",
                data={"runway_id": session.runway_id},
            )

        if intent is ArrivalRequestIntent.REQUEST_QNH:
            if pressure is None or not pressure.usable_for_current_pressure_answer:
                raise ValueError("Current QNH is not positively known")
            answer = answer_aerodrome_pressure(pressure)
            qnh = round(answer.qnh_hpa)
            return ArrivalInformationAnswer(
                kind=ArrivalInformationKind.QNH,
                text_en=f"QNH {qnh} hectopascals.",
                text_ru=f"QNH {qnh} гектопаскалей.",
                data={
                    "qnh_hpa": round(answer.qnh_hpa, 2),
                    "qnh_inhg": round(answer.qnh_inhg, 2),
                    "qnh_mmhg": round(answer.qnh_mmhg, 1),
                    "source": answer.source.value,
                },
            )

        raise ValueError("Arrival intent does not request factual aerodrome information")
