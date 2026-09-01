"""Provider-neutral, fail-closed communication profile pack infrastructure.

The V1 bootstrap packs intentionally contain metadata only.  Operational
phraseology is accepted only from a validated pack and is never synthesized or
silently recovered from the legacy Pilot catalogue.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orion import __version__
from orion.communication_contracts import (
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
)


PACK_SCHEMA_VERSION = "1.0.0"
MAX_PACK_BYTES = 4 * 1024 * 1024
MAX_PACK_FILES = 128
MAX_FILE_BYTES = 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,239}$")
_EXECUTABLE_SUFFIXES = {
    ".bat", ".cmd", ".com", ".dll", ".exe", ".js", ".msi", ".ps1", ".py",
    ".scr", ".vbs",
}


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SourceRegistryStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"


class PackVerificationStatus(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    PARTIAL = "PARTIAL"
    VERIFIED = "VERIFIED"
    DEPRECATED = "DEPRECATED"
    SUPERSEDED = "SUPERSEDED"
    INVALID = "INVALID"


class PackRuntimeReadiness(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class PackLifecycleStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    PREVIOUS_KNOWN_GOOD = "PREVIOUS_KNOWN_GOOD"
    REJECTED = "REJECTED"


class CoverageStatus(StrEnum):
    PLANNED = "PLANNED"
    SOURCE_READY = "SOURCE_READY"
    SOURCE_PARTIAL = "SOURCE_PARTIAL"
    CONTENT_NOT_INSTALLED = "CONTENT_NOT_INSTALLED"
    VERIFIED = "VERIFIED"


class UpdateState(StrEnum):
    NO_REGISTRY = "NO_REGISTRY"
    UP_TO_DATE = "UP_TO_DATE"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    INCOMPATIBLE_UPDATE = "INCOMPATIBLE_UPDATE"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    INVALID_HASH = "INVALID_HASH"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    FAILED = "FAILED"


class ResolutionFailureCode(StrEnum):
    PROFILE_NOT_SELECTED = "PROFILE_NOT_SELECTED"
    PACK_NOT_INSTALLED = "PACK_NOT_INSTALLED"
    PACK_INVALID = "PACK_INVALID"
    PACK_INCOMPATIBLE = "PACK_INCOMPATIBLE"
    DOMAIN_NOT_COVERED = "DOMAIN_NOT_COVERED"
    ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"
    REALIZATION_NOT_AVAILABLE = "REALIZATION_NOT_AVAILABLE"
    ENTRY_NOT_VERIFIED = "ENTRY_NOT_VERIFIED"


class PackError(ValueError):
    def __init__(self, code: ResolutionFailureCode | str, message: str) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, ResolutionFailureCode) else code


class CoreCompatibility(_ClosedModel):
    minimum: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
    maximum_exclusive: str = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$"
    )


class PackFile(_ClosedModel):
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_FILE_BYTES)


class PackSignature(_ClosedModel):
    algorithm: str = Field(min_length=1, max_length=40)
    key_id: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=512)


class PublisherMetadata(_ClosedModel):
    publisher_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    signature: PackSignature


class SourceSummary(_ClosedModel):
    source_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    edition: str | None = Field(default=None, max_length=120)
    locator: str = Field(min_length=1, max_length=500)
    licensing_note: str | None = Field(default=None, max_length=300)


class DomainCoverage(_ClosedModel):
    domain: str = Field(min_length=1, max_length=80)
    status: CoverageStatus


class CommunicationPackManifest(_ClosedModel):
    profile_id: CommunicationProfileId
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    pack_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
    schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_registry_version: str = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$"
    )
    published_at: datetime
    verification: PackVerificationStatus
    readiness: PackRuntimeReadiness
    supported_core_versions: CoreCompatibility
    domains: tuple[str, ...]
    language_realizations: tuple[str, ...]
    coverage: tuple[DomainCoverage, ...]
    files: tuple[PackFile, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    publisher: PublisherMetadata
    source_summary: tuple[SourceSummary, ...]

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        for label, values in (
            ("domains", self.domains),
            ("language_realizations", self.language_realizations),
            ("files", tuple(item.path for item in self.files)),
            ("coverage", tuple(item.domain for item in self.coverage)),
            ("source_summary", tuple(item.source_id for item in self.source_summary)),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label} values are forbidden")
        if not self.domains:
            raise ValueError("At least one planned domain is required")
        if not self.files:
            raise ValueError("At least one content file is required")
        return self


class SourcePublication(_ClosedModel):
    source_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    publisher: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    edition: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=300)


class ProfileSourceRegistryEntry(_ClosedModel):
    profile_id: CommunicationProfileId
    status: SourceRegistryStatus
    limitation: str | None = Field(default=None, max_length=300)
    sources: tuple[SourcePublication, ...]


class CommunicationSourceRegistry(_ClosedModel):
    registry_version: str = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$"
    )
    published_at: datetime
    profiles: tuple[ProfileSourceRegistryEntry, ...]

    @model_validator(mode="after")
    def require_each_profile_once(self) -> Self:
        values = [item.profile_id for item in self.profiles]
        if len(values) != len(set(values)):
            raise ValueError("Source registry profile IDs must be unique")
        if set(values) != set(CommunicationProfileId):
            raise ValueError("Source registry must describe all communication profiles")
        return self


class SemanticSelector(_ClosedModel):
    unit_type: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,119}$")
    domain: str = Field(min_length=1, max_length=80)
    status: str | None = Field(default=None, max_length=80)
    polarity: str | None = Field(default=None, max_length=40)
    roles: tuple[str, ...] = ()


class SlotContract(_ClosedModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    value_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    required: bool = True


class RuleKind(StrEnum):
    REQUIRE_SLOT = "REQUIRE_SLOT"
    OMIT_IF_ABSENT = "OMIT_IF_ABSENT"
    REQUIRE_READBACK = "REQUIRE_READBACK"
    FORBID_VALUE = "FORBID_VALUE"


class SemanticRule(_ClosedModel):
    kind: RuleKind
    slot: str | None = Field(default=None, max_length=80)
    value: str | None = Field(default=None, max_length=160)


class LanguageRealization(_ClosedModel):
    language: str = Field(pattern=r"^[A-Za-z0-9-]{2,35}$")
    text: str = Field(min_length=1, max_length=1000)


class SemanticEntry(_ClosedModel):
    entry_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,119}$")
    selector: SemanticSelector
    slots: tuple[SlotContract, ...] = ()
    rules: tuple[SemanticRule, ...] = ()
    realizations: tuple[LanguageRealization, ...] = ()
    readback_required: bool = False
    acknowledgement_required: bool = False
    priority: CommunicationPriority = CommunicationPriority.ROUTINE
    source_refs: tuple[str, ...] = ()
    verification: PackVerificationStatus
    restrictions: tuple[str, ...] = ()
    test_only: bool = False

    @model_validator(mode="after")
    def reject_duplicate_nested_keys(self) -> Self:
        for label, values in (
            ("slots", tuple(item.name for item in self.slots)),
            ("realizations", tuple(item.language for item in self.realizations)),
            ("roles", self.selector.roles),
            ("source_refs", self.source_refs),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate semantic entry {label} are forbidden")
        return self


class SemanticEntryFile(_ClosedModel):
    entries: tuple[SemanticEntry, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_entries_and_selectors(self) -> Self:
        ids = [item.entry_id for item in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate semantic entry IDs are forbidden")
        selectors = [canonical_json(item.selector.model_dump(mode="json")) for item in self.entries]
        if len(selectors) != len(set(selectors)):
            raise ValueError("Duplicate/conflicting semantic selectors are forbidden")
        return self


class SignatureVerifier(Protocol):
    def verify(self, manifest: CommunicationPackManifest, payload: bytes) -> bool: ...


class RejectUnconfiguredSignatures:
    """Production-safe default until a trusted registry/publisher is configured."""

    def verify(self, manifest: CommunicationPackManifest, payload: bytes) -> bool:
        del manifest, payload
        return False


@dataclass(frozen=True, slots=True)
class PackBundle:
    files: Mapping[str, bytes]
    remote: bool = True
    symlink_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedPack:
    manifest: CommunicationPackManifest
    entries: tuple[SemanticEntry, ...]
    files: Mapping[str, bytes]


class ProfileSelection(_ClosedModel):
    selected_profile_id: CommunicationProfileId | None = None
    updated_at: datetime


class ProfileLifecycleState(_ClosedModel):
    active_version: str | None = None
    candidate_version: str | None = None
    previous_known_good: tuple[str, ...] = ()


class RegistryCheckResult(_ClosedModel):
    profile_id: CommunicationProfileId
    state: UpdateState
    current_version: str | None = None
    candidate_version: str | None = None
    message: str = Field(min_length=1, max_length=300)


class PackRegistryProvider(Protocol):
    def check(
        self, profile_id: CommunicationProfileId, current_version: str | None
    ) -> RegistryCheckResult: ...

    def acquire(self, profile_id: CommunicationProfileId, version: str) -> PackBundle: ...


class NoRegistryProvider:
    def check(
        self, profile_id: CommunicationProfileId, current_version: str | None
    ) -> RegistryCheckResult:
        return RegistryCheckResult(
            profile_id=profile_id,
            state=UpdateState.NO_REGISTRY,
            current_version=current_version,
            message="Update source not configured",
        )

    def acquire(self, profile_id: CommunicationProfileId, version: str) -> PackBundle:
        del profile_id, version
        raise PackError("UPDATE_SOURCE_NOT_CONFIGURED", "Update source not configured")


class ProfileSnapshot(_ClosedModel):
    profile_id: CommunicationProfileId
    pack_id: str
    pack_version: str
    schema_version: str
    source_registry_version: str
    content_hash: str
    verification: PackVerificationStatus
    readiness: PackRuntimeReadiness
    operational_languages: tuple[str, ...]
    captured_at: datetime


class ProfileCard(_ClosedModel):
    profile_id: CommunicationProfileId
    display_name: str
    selected: bool
    configured_profile_id: CommunicationProfileId | None
    effective_profile_id: CommunicationProfileId | None
    active_pack_id: str | None
    active_pack_version: str | None
    source_registry_status: SourceRegistryStatus
    source_limitation: str | None
    verification: PackVerificationStatus | None
    readiness: PackRuntimeReadiness
    coverage: tuple[DomainCoverage, ...]
    operational_languages: tuple[str, ...]
    update_state: UpdateState
    rollback_version: str | None


PROFILE_DISPLAY_NAMES: Mapping[CommunicationProfileId, str] = MappingProxyType({
    CommunicationProfileId.ICAO: "ICAO",
    CommunicationProfileId.FAA_US: "FAA US",
    CommunicationProfileId.NATO_MILITARY: "NATO Military",
    CommunicationProfileId.FAP_RUSSIAN_ATC: "FAP Russian ATC",
})


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _version_key(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise PackError("INVALID_VERSION", f"Invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_core_compatible(contract: CoreCompatibility, version: str = __version__) -> bool:
    current = _version_key(version)
    return _version_key(contract.minimum) <= current < _version_key(contract.maximum_exclusive)


def aggregate_content_hash(files: Sequence[PackFile]) -> str:
    payload = [item.model_dump(mode="json") for item in sorted(files, key=lambda item: item.path)]
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def manifest_signing_bytes(manifest: CommunicationPackManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    publisher = dict(payload["publisher"])
    signature = dict(publisher["signature"])
    signature["value"] = ""
    publisher["signature"] = signature
    payload["publisher"] = publisher
    return canonical_json(payload)


def _safe_relative_path(raw: str) -> str:
    if not _SAFE_FILE.fullmatch(raw) or "\\" in raw:
        raise PackError("UNSAFE_PATH", f"Unsafe pack path: {raw!r}")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
        raise PackError("UNSAFE_PATH", f"Unsafe pack path: {raw!r}")
    if any(part in {"", "."} for part in posix.parts):
        raise PackError("UNSAFE_PATH", f"Unsafe pack path: {raw!r}")
    if posix.suffix.casefold() in _EXECUTABLE_SUFFIXES:
        raise PackError("EXECUTABLE_CONTENT", f"Executable pack content is forbidden: {raw}")
    return posix.as_posix()


def bundle_from_directory(root: Path, *, remote: bool = True) -> PackBundle:
    root = root.resolve()
    if not root.is_dir():
        raise PackError("PACK_NOT_FOUND", f"Pack directory does not exist: {root}")
    files: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PackError("SYMLINK_FORBIDDEN", "Pack symlinks are forbidden")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        _safe_relative_path(relative)
        files[relative] = path.read_bytes()
    return PackBundle(files=files, remote=remote)


def validate_bundle(
    bundle: PackBundle,
    *,
    verifier: SignatureVerifier | None = None,
    core_version: str = __version__,
) -> ValidatedPack:
    raw_files = dict(bundle.files)
    if bundle.symlink_paths:
        raise PackError("SYMLINK_FORBIDDEN", "Pack symlinks are forbidden")
    if len(raw_files) > MAX_PACK_FILES:
        raise PackError("PACK_TOO_MANY_FILES", "Pack file limit exceeded")
    if "manifest.json" not in raw_files:
        raise PackError("MANIFEST_MISSING", "Pack manifest.json is missing")
    total = 0
    for raw_path, content in raw_files.items():
        _safe_relative_path(raw_path)
        if not isinstance(content, bytes):
            raise PackError("INVALID_CONTENT", "Pack files must be bytes")
        if not content or len(content) > MAX_FILE_BYTES:
            raise PackError("INVALID_FILE_SIZE", f"Invalid pack file size: {raw_path}")
        if content.startswith((b"MZ", b"\x7fELF", b"#!")):
            raise PackError("EXECUTABLE_CONTENT", f"Executable pack content is forbidden: {raw_path}")
        total += len(content)
    if total > MAX_PACK_BYTES:
        raise PackError("PACK_TOO_LARGE", "Pack size limit exceeded")
    try:
        manifest_payload = json.loads(raw_files["manifest.json"].decode("utf-8"))
        manifest = CommunicationPackManifest.model_validate(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise PackError("INVALID_MANIFEST", "Pack manifest is malformed or violates schema") from exc
    if manifest.schema_version != PACK_SCHEMA_VERSION:
        raise PackError("INVALID_SCHEMA", "Unsupported pack schema version")
    if not is_core_compatible(manifest.supported_core_versions, core_version):
        raise PackError(ResolutionFailureCode.PACK_INCOMPATIBLE, "Pack is incompatible with this Core")

    declared = {item.path: item for item in manifest.files}
    actual = set(raw_files) - {"manifest.json"}
    if set(declared) != actual:
        raise PackError("FILE_LIST_MISMATCH", "Manifest file list does not match pack contents")
    for path, record in declared.items():
        _safe_relative_path(path)
        content = raw_files[path]
        if len(content) != record.size_bytes or hashlib.sha256(content).hexdigest() != record.sha256:
            raise PackError("INVALID_HASH", f"Pack content hash mismatch: {path}")
    if aggregate_content_hash(manifest.files) != manifest.content_hash:
        raise PackError("INVALID_HASH", "Aggregate pack content hash mismatch")

    if bundle.remote:
        checker = verifier or RejectUnconfiguredSignatures()
        if not checker.verify(manifest, manifest_signing_bytes(manifest)):
            raise PackError("INVALID_SIGNATURE", "Pack signature or publisher is not trusted")
    elif manifest.publisher.signature.algorithm != "LOCAL_BOOTSTRAP":
        raise PackError("INVALID_SIGNATURE", "Unsigned local packs must be explicit bootstrap assets")

    entries: list[SemanticEntry] = []
    for path in sorted(actual):
        if not path.endswith(".json"):
            raise PackError("INVALID_CONTENT_TYPE", "V1 pack content must be canonical JSON")
        try:
            parsed = json.loads(raw_files[path].decode("utf-8"))
            entry_file = SemanticEntryFile.model_validate(parsed)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise PackError("INVALID_CONTENT", f"Invalid semantic content: {path}") from exc
        entries.extend(entry_file.entries)
    combined = SemanticEntryFile(entries=tuple(entries))
    declared_sources = {item.source_id for item in manifest.source_summary}
    declared_languages = set(manifest.language_realizations)
    for entry in combined.entries:
        if entry.selector.domain not in manifest.domains:
            raise PackError("UNDECLARED_DOMAIN", "Semantic entry uses an undeclared domain")
        if not set(entry.source_refs).issubset(declared_sources):
            raise PackError("UNKNOWN_SOURCE_REFERENCE", "Semantic entry provenance is unresolved")
        if not {item.language for item in entry.realizations}.issubset(declared_languages):
            raise PackError("UNDECLARED_LANGUAGE", "Semantic entry uses an undeclared language")
    if manifest.verification is PackVerificationStatus.VERIFIED:
        if not combined.entries or any(
            item.test_only or item.verification is not PackVerificationStatus.VERIFIED
            for item in combined.entries
        ):
            raise PackError("FALSE_VERIFICATION", "Empty/test content cannot be VERIFIED")
    return ValidatedPack(
        manifest=manifest,
        entries=combined.entries,
        files=MappingProxyType(raw_files),
    )


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(canonical_json(payload) + b"\n")
    temp.replace(path)


class CommunicationProfileStore:
    """Bounded, atomic user-data pack store and selection authority."""

    def __init__(
        self,
        root: Path,
        *,
        bootstrap_root: Path | None = None,
        signature_verifier: SignatureVerifier | None = None,
    ) -> None:
        self.root = root.resolve()
        self.bootstrap_root = (
            bootstrap_root.resolve() if bootstrap_root is not None else default_bootstrap_root()
        )
        self._lock = threading.RLock()
        self.signature_verifier = signature_verifier or RejectUnconfiguredSignatures()
        self._cache: dict[tuple[CommunicationProfileId, str], ValidatedPack] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def selection_path(self) -> Path:
        return self.root / "configuration" / "selected-profile.json"

    @property
    def source_registry_path(self) -> Path:
        return self.root / "source-registry.json"

    def initialize(self) -> None:
        with self._lock:
            registry = load_source_registry(self.bootstrap_root / "source-registry.json")
            if not self.source_registry_path.is_file():
                _atomic_json(self.source_registry_path, registry.model_dump(mode="json"))
            if not self.selection_path.is_file():
                self.save_selection(None)
            for profile_id in CommunicationProfileId:
                state = self._load_state(profile_id)
                if state.active_version is not None:
                    continue
                source = self.bootstrap_root / "packs" / profile_id.value
                pack = validate_bundle(bundle_from_directory(source, remote=False))
                self._install_validated(pack, lifecycle=PackLifecycleStatus.ACTIVE)
                self._save_state(profile_id, ProfileLifecycleState(active_version=pack.manifest.pack_version))

    def source_registry(self) -> CommunicationSourceRegistry:
        self.initialize()
        return load_source_registry(self.source_registry_path)

    def load_selection(self) -> ProfileSelection:
        if not self.selection_path.is_file():
            return ProfileSelection(selected_profile_id=None, updated_at=datetime.now(UTC))
        try:
            return ProfileSelection.model_validate_json(self.selection_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise PackError("INVALID_PROFILE_CONFIGURATION", "Selected profile configuration is invalid") from exc

    def save_selection(self, profile_id: CommunicationProfileId | None) -> ProfileSelection:
        selection = ProfileSelection(selected_profile_id=profile_id, updated_at=datetime.now(UTC))
        _atomic_json(self.selection_path, selection.model_dump(mode="json"))
        return selection

    def get_active(self, profile_id: CommunicationProfileId) -> ValidatedPack | None:
        self.initialize()
        state = self._load_state(profile_id)
        if state.active_version is None:
            return None
        return self._load_installed(profile_id, state.active_version)

    def lifecycle(self, profile_id: CommunicationProfileId) -> ProfileLifecycleState:
        self.initialize()
        return self._load_state(profile_id)

    def stage_candidate(self, pack: ValidatedPack) -> Path:
        profile_id = pack.manifest.profile_id
        version = pack.manifest.pack_version
        with self._lock:
            profile_staging = self.root / "staging" / profile_id.value
            if profile_staging.exists():
                shutil.rmtree(profile_staging)
            target = profile_staging / version
            self._write_pack(target, pack.files)
            state = self._load_state(profile_id).model_copy(update={"candidate_version": version})
            self._save_state(profile_id, state)
            return target

    def activate_candidate(
        self,
        profile_id: CommunicationProfileId,
        *,
        verifier: SignatureVerifier,
    ) -> ValidatedPack:
        with self._lock:
            state = self._load_state(profile_id)
            version = state.candidate_version
            if version is None:
                raise PackError("CANDIDATE_MISSING", "No candidate pack is staged")
            staging = self.root / "staging" / profile_id.value / version
            pack = validate_bundle(bundle_from_directory(staging, remote=True), verifier=verifier)
            if pack.manifest.profile_id is not profile_id:
                raise PackError("PROFILE_MISMATCH", "Candidate profile ID does not match")
            self._install_validated(pack, lifecycle=PackLifecycleStatus.ACTIVE)
            previous = list(state.previous_known_good)
            if state.active_version and state.active_version != version:
                previous.insert(0, state.active_version)
            previous = [item for index, item in enumerate(previous) if item not in previous[:index]][:2]
            self._save_state(
                profile_id,
                ProfileLifecycleState(
                    active_version=version,
                    candidate_version=None,
                    previous_known_good=tuple(previous),
                ),
            )
            shutil.rmtree(staging, ignore_errors=True)
            self._cache[(profile_id, version)] = pack
            self._enforce_retention(profile_id)
            return pack

    def rollback(self, profile_id: CommunicationProfileId) -> ValidatedPack:
        with self._lock:
            state = self._load_state(profile_id)
            if not state.previous_known_good:
                raise PackError("ROLLBACK_UNAVAILABLE", "No previous-known-good pack is available")
            target = state.previous_known_good[0]
            pack = self._load_installed(profile_id, target)
            remaining = list(state.previous_known_good[1:])
            if state.active_version:
                remaining.insert(0, state.active_version)
            self._save_state(
                profile_id,
                ProfileLifecycleState(
                    active_version=target,
                    candidate_version=state.candidate_version,
                    previous_known_good=tuple(remaining[:2]),
                ),
            )
            return pack

    def _state_path(self, profile_id: CommunicationProfileId) -> Path:
        return self.root / "state" / f"{profile_id.value}.json"

    def _load_state(self, profile_id: CommunicationProfileId) -> ProfileLifecycleState:
        path = self._state_path(profile_id)
        if not path.is_file():
            return ProfileLifecycleState()
        try:
            return ProfileLifecycleState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise PackError("INVALID_LIFECYCLE_STATE", f"Invalid lifecycle state for {profile_id.value}") from exc

    def _save_state(self, profile_id: CommunicationProfileId, state: ProfileLifecycleState) -> None:
        _atomic_json(self._state_path(profile_id), state.model_dump(mode="json"))

    def _pack_path(self, profile_id: CommunicationProfileId, version: str) -> Path:
        if _VERSION.fullmatch(version) is None:
            raise PackError("INVALID_VERSION", "Pack version is invalid")
        return self.root / "installed" / profile_id.value / version

    def _install_validated(self, pack: ValidatedPack, *, lifecycle: PackLifecycleStatus) -> None:
        del lifecycle
        target = self._pack_path(pack.manifest.profile_id, pack.manifest.pack_version)
        if target.exists():
            existing_manifest = target / "manifest.json"
            try:
                existing_hash = json.loads(existing_manifest.read_text(encoding="utf-8"))[
                    "content_hash"
                ]
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise PackError("VERSION_CONFLICT", "Existing pack version is invalid") from exc
            if existing_hash != pack.manifest.content_hash:
                raise PackError(
                    "VERSION_CONFLICT",
                    "Pack version cannot be replaced with different content",
                )
        else:
            self._write_pack(target, pack.files)
        self._cache[(pack.manifest.profile_id, pack.manifest.pack_version)] = pack

    @staticmethod
    def _write_pack(target: Path, files: Mapping[str, bytes]) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for relative, content in files.items():
            safe = _safe_relative_path(relative)
            destination = target.joinpath(*PurePosixPath(safe).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    def _load_installed(self, profile_id: CommunicationProfileId, version: str) -> ValidatedPack:
        key = (profile_id, version)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        path = self._pack_path(profile_id, version)
        manifest_path = path / "manifest.json"
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            algorithm = str(raw_manifest["publisher"]["signature"]["algorithm"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise PackError("INVALID_MANIFEST", "Installed pack manifest is invalid") from exc
        remote = algorithm != "LOCAL_BOOTSTRAP"
        pack = validate_bundle(
            bundle_from_directory(path, remote=remote),
            verifier=self.signature_verifier,
        )
        if pack.manifest.profile_id is not profile_id:
            raise PackError("PROFILE_MISMATCH", "Installed pack profile ID does not match")
        self._cache[key] = pack
        return pack

    def _enforce_retention(self, profile_id: CommunicationProfileId) -> None:
        state = self._load_state(profile_id)
        keep = {state.active_version, state.candidate_version, *state.previous_known_good}
        parent = self.root / "installed" / profile_id.value
        if not parent.is_dir():
            return
        for child in parent.iterdir():
            if child.is_dir() and child.name not in keep:
                shutil.rmtree(child)
                self._cache.pop((profile_id, child.name), None)


class CommunicationProfileService:
    def __init__(
        self,
        store: CommunicationProfileStore,
        *,
        registry_provider: PackRegistryProvider | None = None,
        signature_verifier: SignatureVerifier | None = None,
    ) -> None:
        self.store = store
        self.registry_provider = registry_provider or NoRegistryProvider()
        self.signature_verifier = signature_verifier or RejectUnconfiguredSignatures()
        self.store.signature_verifier = self.signature_verifier
        self._checks: dict[CommunicationProfileId, RegistryCheckResult] = {}
        self.store.initialize()

    def get_selected_profile(self) -> CommunicationProfileId | None:
        return self.store.load_selection().selected_profile_id

    def select_profile(self, profile_id: CommunicationProfileId) -> ProfileSelection:
        result = self.store.save_selection(profile_id)
        self._emit("communication_profile_selected", profile_id=profile_id.value)
        return result

    def get_active_pack(self, profile_id: CommunicationProfileId) -> ValidatedPack | None:
        return self.store.get_active(profile_id)

    def snapshot_selected_profile(self, *, require_operational: bool = True) -> ProfileSnapshot:
        profile_id = self.get_selected_profile()
        if profile_id is None:
            self._resolution_failed(ResolutionFailureCode.PROFILE_NOT_SELECTED)
        assert profile_id is not None
        pack = self.get_active_pack(profile_id)
        if pack is None:
            self._resolution_failed(ResolutionFailureCode.PACK_NOT_INSTALLED)
        assert pack is not None
        if require_operational and pack.manifest.readiness is not PackRuntimeReadiness.OPERATIONAL:
            self._resolution_failed(ResolutionFailureCode.PACK_INVALID)
        snapshot = ProfileSnapshot(
            profile_id=profile_id,
            pack_id=pack.manifest.pack_id,
            pack_version=pack.manifest.pack_version,
            schema_version=pack.manifest.schema_version,
            source_registry_version=pack.manifest.source_registry_version,
            content_hash=pack.manifest.content_hash,
            verification=pack.manifest.verification,
            readiness=pack.manifest.readiness,
            operational_languages=pack.manifest.language_realizations,
            captured_at=datetime.now(UTC),
        )
        self._emit(
            "communication_profile_snapshot",
            profile_id=profile_id.value,
            pack_id=snapshot.pack_id,
            pack_version=snapshot.pack_version,
            schema_version=snapshot.schema_version,
            source_registry_version=snapshot.source_registry_version,
            content_hash=snapshot.content_hash,
            verification_status=snapshot.verification.value,
        )
        return snapshot

    def resolve_entry(
        self,
        snapshot: ProfileSnapshot,
        selector: SemanticSelector,
        *,
        language: str,
    ) -> SemanticEntry:
        pack = self.get_active_pack(snapshot.profile_id)
        if pack is None or pack.manifest.content_hash != snapshot.content_hash:
            raise PackError(ResolutionFailureCode.PACK_INVALID, "Pinned profile snapshot is unavailable")
        if selector.domain not in pack.manifest.domains:
            raise PackError(ResolutionFailureCode.DOMAIN_NOT_COVERED, "Profile domain is not covered")
        matches = [item for item in pack.entries if item.selector == selector]
        if not matches:
            raise PackError(ResolutionFailureCode.ENTRY_NOT_FOUND, "Semantic entry is not present")
        entry = matches[0]
        if entry.verification is not PackVerificationStatus.VERIFIED or entry.test_only:
            raise PackError(ResolutionFailureCode.ENTRY_NOT_VERIFIED, "Semantic entry is not verified")
        if language not in {item.language for item in entry.realizations}:
            raise PackError(ResolutionFailureCode.REALIZATION_NOT_AVAILABLE, "Language realization is unavailable")
        return entry

    def cards(self) -> tuple[ProfileCard, ...]:
        selected = self.get_selected_profile()
        registry = {item.profile_id: item for item in self.store.source_registry().profiles}
        active_by_profile: dict[CommunicationProfileId, ValidatedPack | None] = {}
        invalid_profiles: set[CommunicationProfileId] = set()
        for profile_id in CommunicationProfileId:
            try:
                active_by_profile[profile_id] = self.get_active_pack(profile_id)
            except PackError as exc:
                active_by_profile[profile_id] = None
                invalid_profiles.add(profile_id)
                self._emit(
                    "communication_pack_resolution_failed",
                    profile_id=profile_id.value,
                    reason=exc.code,
                )
        effective: CommunicationProfileId | None = None
        if selected is not None:
            active = active_by_profile[selected]
            if active is not None and active.manifest.readiness is PackRuntimeReadiness.OPERATIONAL:
                effective = selected
        cards: list[ProfileCard] = []
        for profile_id in CommunicationProfileId:
            active = active_by_profile[profile_id]
            state = self.store.lifecycle(profile_id)
            check = self._checks.get(profile_id)
            source = registry[profile_id]
            cards.append(
                ProfileCard(
                    profile_id=profile_id,
                    display_name=PROFILE_DISPLAY_NAMES[profile_id],
                    selected=profile_id is selected,
                    configured_profile_id=selected,
                    effective_profile_id=effective,
                    active_pack_id=active.manifest.pack_id if active else None,
                    active_pack_version=active.manifest.pack_version if active else None,
                    source_registry_status=source.status,
                    source_limitation=source.limitation,
                    verification=(
                        active.manifest.verification
                        if active
                        else (
                            PackVerificationStatus.INVALID
                            if profile_id in invalid_profiles
                            else None
                        )
                    ),
                    readiness=(
                        active.manifest.readiness
                        if active
                        else (
                            PackRuntimeReadiness.INVALID
                            if profile_id in invalid_profiles
                            else PackRuntimeReadiness.NOT_INSTALLED
                        )
                    ),
                    coverage=active.manifest.coverage if active else (),
                    operational_languages=(active.manifest.language_realizations if active else ()),
                    update_state=check.state if check else UpdateState.NO_REGISTRY,
                    rollback_version=state.previous_known_good[0] if state.previous_known_good else None,
                )
            )
        return tuple(cards)

    def check_for_updates(self, profile_id: CommunicationProfileId) -> RegistryCheckResult:
        active = self.get_active_pack(profile_id)
        result = self.registry_provider.check(
            profile_id, active.manifest.pack_version if active else None
        )
        self._checks[profile_id] = result
        self._emit(
            "communication_pack_update_checked",
            profile_id=profile_id.value,
            update_state=result.state.value,
        )
        return result

    def update(self, profile_id: CommunicationProfileId) -> ValidatedPack:
        check = self._checks.get(profile_id) or self.check_for_updates(profile_id)
        if check.state is not UpdateState.UPDATE_AVAILABLE or not check.candidate_version:
            raise PackError("UPDATE_NOT_AVAILABLE", check.message)
        try:
            bundle = self.registry_provider.acquire(profile_id, check.candidate_version)
            if not bundle.remote:
                raise PackError("REMOTE_TRUST_REQUIRED", "Registry updates must use remote trust validation")
            pack = validate_bundle(bundle, verifier=self.signature_verifier)
            if pack.manifest.profile_id is not profile_id:
                raise PackError("PROFILE_MISMATCH", "Downloaded pack profile ID does not match")
            self.store.stage_candidate(pack)
            self._emit(
                "communication_pack_candidate_ready",
                profile_id=profile_id.value,
                pack_version=pack.manifest.pack_version,
            )
            activated = self.store.activate_candidate(profile_id, verifier=self.signature_verifier)
        except PackError as exc:
            current = self.get_active_pack(profile_id)
            mapped_state = {
                "INVALID_SIGNATURE": UpdateState.INVALID_SIGNATURE,
                "INVALID_HASH": UpdateState.INVALID_HASH,
                "INVALID_SCHEMA": UpdateState.INVALID_SCHEMA,
                ResolutionFailureCode.PACK_INCOMPATIBLE.value: UpdateState.INCOMPATIBLE_UPDATE,
            }.get(exc.code, UpdateState.FAILED)
            self._checks[profile_id] = RegistryCheckResult(
                profile_id=profile_id,
                state=mapped_state,
                current_version=current.manifest.pack_version if current is not None else None,
                candidate_version=check.candidate_version,
                message=str(exc)[:300],
            )
            self._emit(
                "communication_pack_candidate_rejected",
                profile_id=profile_id.value,
                reason=exc.code,
            )
            raise
        self._emit(
            "communication_pack_activated",
            profile_id=profile_id.value,
            pack_version=activated.manifest.pack_version,
            content_hash=activated.manifest.content_hash,
        )
        return activated

    def rollback(self, profile_id: CommunicationProfileId) -> ValidatedPack:
        pack = self.store.rollback(profile_id)
        self._emit(
            "communication_pack_rollback_completed",
            profile_id=profile_id.value,
            pack_version=pack.manifest.pack_version,
        )
        return pack

    def details(self, profile_id: CommunicationProfileId) -> dict[str, object]:
        source = next(
            item for item in self.store.source_registry().profiles if item.profile_id is profile_id
        )
        active = self.get_active_pack(profile_id)
        return {
            "profile_id": profile_id.value,
            "display_name": PROFILE_DISPLAY_NAMES[profile_id],
            "source_registry_status": source.status.value,
            "source_limitation": source.limitation,
            "sources": [item.model_dump(mode="json") for item in source.sources],
            "pack": active.manifest.model_dump(mode="json") if active else None,
        }

    def _resolution_failed(self, code: ResolutionFailureCode) -> None:
        self._emit("communication_pack_resolution_failed", reason=code.value)
        raise PackError(code, code.value.replace("_", " ").title())

    @staticmethod
    def _emit(event: str, **fields: object) -> None:
        try:
            from orion.realtime_test_evidence import realtime_test_evidence

            realtime_test_evidence.record(event, **fields)
        except (ImportError, RuntimeError, ValueError):
            return


def load_source_registry(path: Path) -> CommunicationSourceRegistry:
    try:
        return CommunicationSourceRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise PackError("INVALID_SOURCE_REGISTRY", "Communication source registry is invalid") from exc


def default_bootstrap_root() -> Path:
    return Path(__file__).resolve().with_name("communication_profile_assets")


def default_profile_data_root() -> Path:
    configured = os.environ.get("ORION_COMMUNICATION_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", Path.cwd() / "runtime")).expanduser().resolve()
    return runtime.parent / "communication-profiles"
