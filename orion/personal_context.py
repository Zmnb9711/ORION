"""Small explicit user-authorized context, separate from simulator/recent state."""
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class UserProvidedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=300, repr=False)
    authority: Literal["USER_PROVIDED"]
    source: Literal["EXPLICIT_USER_AUTHORIZATION"]


class PersonalContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["orion.user-context.v1"] = "orion.user-context.v1"
    facts: tuple[UserProvidedFact, ...] = Field(default=(), max_length=4)


def load_personal_context(path: Path | None = None) -> PersonalContext:
    """Missing/invalid storage is empty; never derive/invent a substitute fact.

    This is not a provider memory file. Runtime reads only; user authorization
    is required to create/update facts. No production transcript recorder.
    """
    target = path or Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")) / "personal-context.json"
    try:
        with target.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return PersonalContext()
        return PersonalContext.model_validate_json(raw, strict=True)
    except (OSError, ValueError, ValidationError):
        return PersonalContext()
