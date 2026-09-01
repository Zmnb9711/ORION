from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from orion.communication_contracts import CommunicationProfileId
from orion.communication_profile_packs import (
    MAX_FILE_BYTES,
    MAX_PACK_FILES,
    CommunicationPackManifest,
    CommunicationProfileService,
    CommunicationProfileStore,
    NoRegistryProvider,
    PackBundle,
    PackError,
    PackRuntimeReadiness,
    PackVerificationStatus,
    ProfileLifecycleState,
    RegistryCheckResult,
    SemanticSelector,
    UpdateState,
    aggregate_content_hash,
    canonical_json,
    manifest_signing_bytes,
    validate_bundle,
)


class HmacTestTrustStore:
    """Deterministic test-only publisher trust seam; never used by production."""

    def __init__(self, keys: dict[tuple[str, str], bytes]) -> None:
        self.keys = keys

    def verify(self, manifest: CommunicationPackManifest, payload: bytes) -> bool:
        signature = manifest.publisher.signature
        key = self.keys.get((manifest.publisher.publisher_id, signature.key_id))
        if key is None or signature.algorithm != "HMAC_SHA256_TEST_ONLY":
            return False
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.value)


TRUST_KEY = b"deterministic-test-key-not-a-production-secret"
TRUST = HmacTestTrustStore({("test-publisher", "test-key-1"): TRUST_KEY})


def _entry(entry_id: str = "test.takeoff", *, selector_status: str = "granted") -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "selector": {
            "unit_type": "atc.takeoff_clearance",
            "domain": "AIRPORT_ATC",
            "status": selector_status,
            "polarity": "positive",
            "roles": ["controller"],
        },
        "slots": [
            {"name": "callsign", "value_type": "CALLSIGN", "required": True},
            {"name": "runway", "value_type": "RUNWAY", "required": True},
        ],
        "rules": [{"kind": "REQUIRE_READBACK", "slot": "runway", "value": None}],
        "realizations": [{"language": "en-US", "text": "TEST ONLY {callsign} {runway}"}],
        "readback_required": True,
        "acknowledgement_required": False,
        "priority": "routine",
        "source_refs": ["test-source"],
        "verification": "VERIFIED",
        "restrictions": ["TEST_ONLY"],
        "test_only": False,
    }


def _signed_bundle(
    *,
    profile_id: str = "FAA_US",
    version: str = "1.0.0",
    entries: list[dict[str, object]] | None = None,
    schema_version: str = "1.0.0",
    minimum: str = "0.2.0-alpha",
    maximum: str = "1.0.0",
    publisher: str = "test-publisher",
    key_id: str = "test-key-1",
    key: bytes = TRUST_KEY,
) -> PackBundle:
    content = canonical_json({"entries": entries if entries is not None else [_entry()]})
    record = {
        "path": "entries.json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
    file_model = CommunicationPackManifest.model_fields["files"]  # schema existence guard
    assert file_model is not None
    payload: dict[str, object] = {
        "profile_id": profile_id,
        "pack_id": f"{profile_id.casefold().replace('_', '-')}-test-pack",
        "pack_version": version,
        "schema_version": schema_version,
        "source_registry_version": "1.0.0",
        "published_at": "2026-09-01T00:00:00Z",
        "verification": "VERIFIED",
        "readiness": "OPERATIONAL",
        "supported_core_versions": {"minimum": minimum, "maximum_exclusive": maximum},
        "domains": ["AIRPORT_ATC"],
        "language_realizations": ["en-US"],
        "coverage": [{"domain": "AIRPORT_ATC", "status": "VERIFIED"}],
        "files": [record],
        "content_hash": hashlib.sha256(canonical_json([record])).hexdigest(),
        "publisher": {
            "publisher_id": publisher,
            "display_name": "Test Publisher",
            "signature": {
                "algorithm": "HMAC_SHA256_TEST_ONLY",
                "key_id": key_id,
                "value": "",
            },
        },
        "source_summary": [
            {
                "source_id": "test-source",
                "title": "Synthetic test source",
                "edition": None,
                "locator": "test://fixture",
                "licensing_note": "TEST_ONLY",
            }
        ],
    }
    manifest = CommunicationPackManifest.model_validate(payload)
    payload["publisher"]["signature"]["value"] = hmac.new(  # type: ignore[index]
        key, manifest_signing_bytes(manifest), hashlib.sha256
    ).hexdigest()
    return PackBundle(
        files={"manifest.json": canonical_json(payload), "entries.json": content},
        remote=True,
    )


def _mutate_manifest(bundle: PackBundle, **updates: object) -> PackBundle:
    payload = json.loads(bundle.files["manifest.json"])
    payload.update(updates)
    return replace(bundle, files={**bundle.files, "manifest.json": canonical_json(payload)})


def _store(tmp_path: Path) -> CommunicationProfileStore:
    return CommunicationProfileStore(tmp_path / "profiles", signature_verifier=TRUST)


def test_valid_manifest_loads_and_is_closed() -> None:
    pack = validate_bundle(_signed_bundle(), verifier=TRUST)
    assert pack.manifest.profile_id is CommunicationProfileId.FAA_US
    assert pack.manifest.schema_version == "1.0.0"
    assert len(pack.entries) == 1

    unknown = json.loads(_signed_bundle().files["manifest.json"])
    unknown["surprise"] = True
    with pytest.raises(PackError, match="violates schema"):
        validate_bundle(
            PackBundle(
                files={
                    "manifest.json": canonical_json(unknown),
                    "entries.json": _signed_bundle().files["entries.json"],
                }
            ),
            verifier=TRUST,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"profile_id": "UNKNOWN"}, "violates schema"),
        ({"schema_version": "2.0.0"}, "Unsupported pack schema"),
        ({"supported_core_versions": {"minimum": "9.0.0", "maximum_exclusive": "10.0.0"}}, "incompatible"),
    ],
)
def test_invalid_profile_schema_and_core_compatibility_fail_closed(
    mutation: dict[str, object], message: str
) -> None:
    with pytest.raises(PackError, match=message):
        validate_bundle(_mutate_manifest(_signed_bundle(), **mutation), verifier=TRUST)


def test_missing_required_manifest_field_fails() -> None:
    bundle = _signed_bundle()
    payload = json.loads(bundle.files["manifest.json"])
    del payload["pack_id"]
    with pytest.raises(PackError, match="violates schema"):
        validate_bundle(
            replace(bundle, files={**bundle.files, "manifest.json": canonical_json(payload)}),
            verifier=TRUST,
        )


def test_duplicate_entry_ids_and_conflicting_selectors_fail() -> None:
    duplicate_id = _signed_bundle(entries=[_entry(), _entry()])
    with pytest.raises(PackError, match="Invalid semantic content"):
        validate_bundle(duplicate_id, verifier=TRUST)
    conflicting = _signed_bundle(entries=[_entry("test.one"), _entry("test.two")])
    with pytest.raises(PackError, match="Invalid semantic content"):
        validate_bundle(conflicting, verifier=TRUST)


def test_file_hash_aggregate_hash_and_file_list_are_enforced() -> None:
    bundle = _signed_bundle()
    assert validate_bundle(bundle, verifier=TRUST)
    with pytest.raises(PackError, match="content hash mismatch"):
        validate_bundle(
            replace(bundle, files={**bundle.files, "entries.json": b'{"entries":[]}'}),
            verifier=TRUST,
        )
    with pytest.raises(PackError, match="Aggregate"):
        validate_bundle(_mutate_manifest(bundle, content_hash="0" * 64), verifier=TRUST)
    with pytest.raises(PackError, match="file list"):
        validate_bundle(
            replace(bundle, files={**bundle.files, "extra.json": b"{}"}),
            verifier=TRUST,
        )


@pytest.mark.parametrize("unsafe", ["../escape.json", "/absolute.json", "C:/absolute.json"])
def test_unsafe_paths_are_rejected(unsafe: str) -> None:
    bundle = _signed_bundle()
    with pytest.raises(PackError, match="Unsafe pack path"):
        validate_bundle(replace(bundle, files={**bundle.files, unsafe: b"{}"}), verifier=TRUST)


def test_symlink_oversize_file_count_executable_and_malformed_json_are_rejected() -> None:
    bundle = _signed_bundle()
    with pytest.raises(PackError, match="symlinks"):
        validate_bundle(replace(bundle, symlink_paths=("entries.json",)), verifier=TRUST)
    with pytest.raises(PackError, match="file size"):
        validate_bundle(
            replace(bundle, files={**bundle.files, "entries.json": b"x" * (MAX_FILE_BYTES + 1)}),
            verifier=TRUST,
        )
    too_many = {f"f{index}.json": b"{}" for index in range(MAX_PACK_FILES + 1)}
    with pytest.raises(PackError, match="file limit"):
        validate_bundle(PackBundle(files=too_many), verifier=TRUST)
    with pytest.raises(PackError, match="Executable"):
        validate_bundle(replace(bundle, files={**bundle.files, "bad.exe": b"MZ"}), verifier=TRUST)
    with pytest.raises(PackError, match="Executable"):
        validate_bundle(
            replace(bundle, files={**bundle.files, "entries.json": b"MZ disguised executable"}),
            verifier=TRUST,
        )
    with pytest.raises(PackError, match="malformed"):
        validate_bundle(
            PackBundle(files={"manifest.json": b"{broken"}), verifier=TRUST
        )


def test_signature_trust_seam_rejects_wrong_key_unknown_publisher_and_manifest_change() -> None:
    assert validate_bundle(_signed_bundle(), verifier=TRUST)
    with pytest.raises(PackError, match="not trusted"):
        validate_bundle(_signed_bundle(key=b"wrong-key"), verifier=TRUST)
    with pytest.raises(PackError, match="not trusted"):
        validate_bundle(_signed_bundle(publisher="unknown"), verifier=TRUST)
    with pytest.raises(PackError, match="not trusted"):
        validate_bundle(_mutate_manifest(_signed_bundle(), published_at="2026-09-02T00:00:00Z"), verifier=TRUST)
    with pytest.raises(PackError, match="not trusted"):
        validate_bundle(_signed_bundle(), verifier=None)


class FakeRegistry:
    def __init__(self, bundle: PackBundle | None = None, *, state: UpdateState = UpdateState.UPDATE_AVAILABLE) -> None:
        self.bundle = bundle
        self.state = state

    def check(self, profile_id: CommunicationProfileId, current_version: str | None) -> RegistryCheckResult:
        return RegistryCheckResult(
            profile_id=profile_id,
            state=self.state,
            current_version=current_version,
            candidate_version=("1.0.0" if self.state is UpdateState.UPDATE_AVAILABLE else None),
            message=self.state.value,
        )

    def acquire(self, profile_id: CommunicationProfileId, version: str) -> PackBundle:
        assert profile_id is CommunicationProfileId.FAA_US
        assert version == "1.0.0"
        assert self.bundle is not None
        return self.bundle


def test_candidate_activation_is_atomic_preserves_active_and_supports_rollback(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(
        store,
        registry_provider=FakeRegistry(_signed_bundle(version="1.0.0")),
        signature_verifier=TRUST,
    )
    before = service.get_active_pack(CommunicationProfileId.FAA_US)
    assert before is not None and before.manifest.pack_version == "0.1.0"
    service.check_for_updates(CommunicationProfileId.FAA_US)
    after = service.update(CommunicationProfileId.FAA_US)
    assert after.manifest.pack_version == "1.0.0"
    state = store.lifecycle(CommunicationProfileId.FAA_US)
    assert state.active_version == "1.0.0"
    assert state.candidate_version is None
    assert state.previous_known_good == ("0.1.0",)
    assert not (store.root / "staging" / "FAA_US" / "1.0.0").exists()

    rolled_back = service.rollback(CommunicationProfileId.FAA_US)
    assert rolled_back.manifest.pack_version == "0.1.0"
    assert store.lifecycle(CommunicationProfileId.FAA_US).active_version == "0.1.0"


def test_candidate_staging_is_bounded_to_one_version_per_profile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    CommunicationProfileService(store, signature_verifier=TRUST)
    first = validate_bundle(_signed_bundle(version="1.0.0"), verifier=TRUST)
    second = validate_bundle(_signed_bundle(version="1.1.0"), verifier=TRUST)
    store.stage_candidate(first)
    store.stage_candidate(second)
    staged = store.root / "staging" / "FAA_US"
    assert [item.name for item in staged.iterdir()] == ["1.1.0"]
    assert store.lifecycle(CommunicationProfileId.FAA_US).candidate_version == "1.1.0"


def test_invalid_candidate_never_replaces_active(tmp_path: Path) -> None:
    bad = _signed_bundle(key=b"wrong")
    service = CommunicationProfileService(
        _store(tmp_path),
        registry_provider=FakeRegistry(bad),
        signature_verifier=TRUST,
    )
    service.check_for_updates(CommunicationProfileId.FAA_US)
    with pytest.raises(PackError, match="not trusted"):
        service.update(CommunicationProfileId.FAA_US)
    active = service.get_active_pack(CommunicationProfileId.FAA_US)
    assert active is not None and active.manifest.pack_version == "0.1.0"
    assert service.cards()[1].update_state is UpdateState.INVALID_SIGNATURE


@pytest.mark.parametrize(
    "state",
    [UpdateState.UP_TO_DATE, UpdateState.INCOMPATIBLE_UPDATE],
)
def test_registry_check_states_never_mutate_active(tmp_path: Path, state: UpdateState) -> None:
    service = CommunicationProfileService(
        _store(tmp_path), registry_provider=FakeRegistry(state=state), signature_verifier=TRUST
    )
    before = service.get_active_pack(CommunicationProfileId.FAA_US)
    result = service.check_for_updates(CommunicationProfileId.FAA_US)
    after = service.get_active_pack(CommunicationProfileId.FAA_US)
    assert result.state is state
    assert before is not None and after is not None
    assert before.manifest.content_hash == after.manifest.content_hash


@pytest.mark.parametrize(
    ("bundle_factory", "expected"),
    [
        (lambda: _signed_bundle(key=b"wrong"), UpdateState.INVALID_SIGNATURE),
        (
            lambda: replace(
                _signed_bundle(),
                files={**_signed_bundle().files, "entries.json": b'{"entries":[]}'},
            ),
            UpdateState.INVALID_HASH,
        ),
        (
            lambda: _mutate_manifest(_signed_bundle(), schema_version="2.0.0"),
            UpdateState.INVALID_SCHEMA,
        ),
    ],
)
def test_failed_update_is_classified_and_preserves_active(
    tmp_path: Path, bundle_factory, expected: UpdateState  # noqa: ANN001
) -> None:
    service = CommunicationProfileService(
        _store(tmp_path),
        registry_provider=FakeRegistry(bundle_factory()),
        signature_verifier=TRUST,
    )
    before = service.get_active_pack(CommunicationProfileId.FAA_US)
    service.check_for_updates(CommunicationProfileId.FAA_US)
    with pytest.raises(PackError):
        service.update(CommunicationProfileId.FAA_US)
    after = service.get_active_pack(CommunicationProfileId.FAA_US)
    assert before is not None and after is not None
    assert before.manifest.pack_version == after.manifest.pack_version == "0.1.0"
    assert service.cards()[1].update_state is expected


def test_retention_is_bounded_to_active_and_two_previous_versions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(store, signature_verifier=TRUST)
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        pack = validate_bundle(_signed_bundle(version=version), verifier=TRUST)
        store.stage_candidate(pack)
        store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    state = store.lifecycle(CommunicationProfileId.FAA_US)
    assert state.active_version == "1.2.0"
    assert state.previous_known_good == ("1.1.0", "1.0.0")
    versions = {item.name for item in (store.root / "installed" / "FAA_US").iterdir()}
    assert versions == {"1.0.0", "1.1.0", "1.2.0"}


def test_same_version_with_different_content_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    CommunicationProfileService(store, signature_verifier=TRUST)
    first = validate_bundle(_signed_bundle(version="1.0.0"), verifier=TRUST)
    store.stage_candidate(first)
    store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    changed_entry = _entry()
    changed_entry["realizations"] = [
        {"language": "en-US", "text": "DIFFERENT TEST ONLY {callsign} {runway}"}
    ]
    conflict = validate_bundle(
        _signed_bundle(version="1.0.0", entries=[changed_entry]), verifier=TRUST
    )
    store.stage_candidate(conflict)
    with pytest.raises(PackError, match="cannot be replaced"):
        store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    assert store.lifecycle(CommunicationProfileId.FAA_US).active_version == "1.0.0"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"source_refs": ["missing-source"]}, "UNKNOWN_SOURCE_REFERENCE"),
        (
            {
                "selector": {
                    "unit_type": "atc.takeoff_clearance",
                    "domain": "UNDECLARED",
                    "status": "granted",
                    "polarity": "positive",
                    "roles": ["controller"],
                }
            },
            "UNDECLARED_DOMAIN",
        ),
        (
            {
                "realizations": [
                    {"language": "ru-RU", "text": "TEST ONLY"}
                ]
            },
            "UNDECLARED_LANGUAGE",
        ),
    ],
)
def test_entry_provenance_domain_and_language_must_match_manifest(
    mutation: dict[str, object], code: str
) -> None:
    entry = _entry()
    entry.update(mutation)
    with pytest.raises(PackError) as captured:
        validate_bundle(_signed_bundle(entries=[entry]), verifier=TRUST)
    assert captured.value.code == code


def test_selection_persists_does_not_delete_packs_and_snapshot_is_pinned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(store, signature_verifier=TRUST)
    assert service.get_selected_profile() is None
    for profile_id in CommunicationProfileId:
        service.select_profile(profile_id)
        reloaded = CommunicationProfileService(_store(tmp_path), signature_verifier=TRUST)
        assert reloaded.get_selected_profile() is profile_id
        assert all(reloaded.get_active_pack(item) is not None for item in CommunicationProfileId)

    operational = validate_bundle(
        _signed_bundle(profile_id="FAA_US", version="1.0.0"), verifier=TRUST
    )
    store.stage_candidate(operational)
    store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    service.select_profile(CommunicationProfileId.FAA_US)
    old_snapshot = service.snapshot_selected_profile()
    newer = validate_bundle(_signed_bundle(profile_id="FAA_US", version="1.1.0"), verifier=TRUST)
    store.stage_candidate(newer)
    store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    new_snapshot = service.snapshot_selected_profile()
    assert old_snapshot.pack_version == "1.0.0"
    assert new_snapshot.pack_version == "1.1.0"
    assert old_snapshot.content_hash == operational.manifest.content_hash


def test_pack_update_never_switches_selected_profile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(store, signature_verifier=TRUST)
    service.select_profile(CommunicationProfileId.ICAO)
    pack = validate_bundle(_signed_bundle(profile_id="FAA_US", version="1.0.0"), verifier=TRUST)
    store.stage_candidate(pack)
    store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    assert service.get_selected_profile() is CommunicationProfileId.ICAO


def test_legacy_settings_cannot_override_profile_selection(tmp_path: Path) -> None:
    from orion.orion_settings import CommunicationMode, OrionSettingsStore, OrionSettingsUpdate

    legacy = OrionSettingsStore()
    legacy.update(
        OrionSettingsUpdate(
            communication_mode=CommunicationMode.AVIATION_RUSSIAN,
            default_profile_id="legacy-profile",
        )
    )
    service = CommunicationProfileService(_store(tmp_path))
    service.select_profile(CommunicationProfileId.NATO_MILITARY)
    assert legacy.get().communication_mode is CommunicationMode.AVIATION_RUSSIAN
    assert service.get_selected_profile() is CommunicationProfileId.NATO_MILITARY


def test_profile_events_are_privacy_bounded(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import orion.realtime_test_evidence as evidence_module

    captured: list[tuple[str, dict[str, object]]] = []

    class Sink:
        def record(self, event: str, **fields: object) -> None:
            captured.append((event, fields))

    monkeypatch.setattr(evidence_module, "realtime_test_evidence", Sink())
    service = CommunicationProfileService(_store(tmp_path))
    service.select_profile(CommunicationProfileId.FAP_RUSSIAN_ATC)
    service.snapshot_selected_profile(require_operational=False)
    names = [item[0] for item in captured]
    assert names == ["communication_profile_selected", "communication_profile_snapshot"]
    assert set(captured[-1][1]) == {
        "profile_id",
        "pack_id",
        "pack_version",
        "schema_version",
        "source_registry_version",
        "content_hash",
        "verification_status",
    }
    assert all("text" not in fields and "credential" not in fields for _, fields in captured)


def test_bootstrap_has_no_silent_default_and_no_verified_normative_content(tmp_path: Path) -> None:
    service = CommunicationProfileService(_store(tmp_path), registry_provider=NoRegistryProvider())
    assert service.get_selected_profile() is None
    with pytest.raises(PackError) as captured:
        service.snapshot_selected_profile()
    assert captured.value.code == "PROFILE_NOT_SELECTED"
    for card in service.cards():
        assert card.readiness is PackRuntimeReadiness.RESEARCH_ONLY
        assert card.verification in {PackVerificationStatus.EXPERIMENTAL, PackVerificationStatus.PARTIAL}
        assert card.operational_languages == ()
        assert card.update_state is UpdateState.NO_REGISTRY
    result = service.check_for_updates(CommunicationProfileId.ICAO)
    assert result.state is UpdateState.NO_REGISTRY
    assert service.get_active_pack(CommunicationProfileId.ICAO) is not None


def test_invalid_configured_pack_is_never_reported_as_effective(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(store)
    service.select_profile(CommunicationProfileId.FAA_US)
    manifest = store.root / "installed" / "FAA_US" / "0.1.0" / "manifest.json"
    manifest.write_text("{broken", encoding="utf-8")
    store._cache.clear()
    cards = service.cards()
    selected = cards[1]
    assert selected.selected
    assert selected.effective_profile_id is None
    assert selected.readiness is PackRuntimeReadiness.INVALID
    assert selected.verification is PackVerificationStatus.INVALID


def test_operational_language_comes_only_from_pinned_pack_not_input_language(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = CommunicationProfileService(store, signature_verifier=TRUST)
    pack = validate_bundle(_signed_bundle(), verifier=TRUST)
    store.stage_candidate(pack)
    store.activate_candidate(CommunicationProfileId.FAA_US, verifier=TRUST)
    service.select_profile(CommunicationProfileId.FAA_US)
    snapshot = service.snapshot_selected_profile()
    assert snapshot.operational_languages == ("en-US",)
    assert "input_language" not in type(snapshot).model_fields
    selector = SemanticSelector(
        unit_type="atc.takeoff_clearance",
        domain="AIRPORT_ATC",
        status="granted",
        polarity="positive",
        roles=("controller",),
    )
    assert service.resolve_entry(snapshot, selector, language="en-US").entry_id == "test.takeoff"
    with pytest.raises(PackError) as captured:
        service.resolve_entry(snapshot, selector, language="ru-RU")
    assert captured.value.code == "REALIZATION_NOT_AVAILABLE"


def test_lifecycle_state_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProfileLifecycleState.model_validate({"active_version": None, "legacy": True})
