import pytest
from fastapi.testclient import TestClient

from orion.aircraft_knowledge import (
    EvidenceLevel,
    FA18_OFFICIAL_SOURCE_ID,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeSearchQuery,
    KnowledgeSource,
    KnowledgeSourceType,
    ProfileStatus,
    aircraft_knowledge,
)
from orion.app import app


def test_user_defined_aircraft_priority_is_preserved() -> None:
    profiles = aircraft_knowledge.list_profiles()

    assert [profile.aircraft_id for profile in profiles[:8]] == [
        "fa-18c",
        "f-5e",
        "p-51d",
        "mig-21bis",
        "a-10c-ii",
        "jf-17",
        "p-47d",
        "spitfire-lf-mk-ix",
    ]
    assert profiles[0].status is ProfileStatus.IN_PROGRESS


def test_fa18_aliases_resolve_to_canonical_profile() -> None:
    assert aircraft_knowledge.resolve_aircraft_id("Hornet") == "fa-18c"
    assert aircraft_knowledge.resolve_aircraft_id("F/A-18C") == "fa-18c"
    assert aircraft_knowledge.resolve_aircraft_id("F/A-18C Hornet") == "fa-18c"
    assert aircraft_knowledge.get_profile("hornet") is not None


def test_fa18_baseline_uses_official_ed_source() -> None:
    profile = aircraft_knowledge.get_profile("fa-18c")
    sources = aircraft_knowledge.list_sources("hornet")
    entries = aircraft_knowledge.list_entries("fa18c")

    assert profile is not None
    assert profile.entry_count >= 7
    assert profile.source_count >= 1
    assert any(source.source_id == FA18_OFFICIAL_SOURCE_ID for source in sources)
    assert all(FA18_OFFICIAL_SOURCE_ID in entry.source_ids for entry in entries)
    assert all(entry.evidence is EvidenceLevel.VERIFIED for entry in entries)


def test_fa18_baseline_covers_core_operating_domains() -> None:
    categories = {entry.category for entry in aircraft_knowledge.list_entries("hornet")}

    assert KnowledgeCategory.GENERAL in categories
    assert KnowledgeCategory.COMMUNICATIONS in categories
    assert KnowledgeCategory.NAVIGATION in categories
    assert KnowledgeCategory.RADAR in categories
    assert KnowledgeCategory.SENSORS in categories
    assert KnowledgeCategory.WEAPONS in categories
    assert KnowledgeCategory.NORMAL_PROCEDURES in categories


def test_hornet_alias_can_be_used_in_search_filter() -> None:
    result = aircraft_knowledge.search(
        KnowledgeSearchQuery(text="TACAN", aircraft_id="Hornet", verified_only=True)
    )

    assert result.total >= 1
    assert all(entry.aircraft_id == "fa-18c" for entry in result.entries)


def test_aircraft_knowledge_api_exposes_hornet_baseline() -> None:
    client = TestClient(app)

    profile_response = client.get("/v1/aircraft-knowledge/profiles/hornet")
    source_response = client.get("/v1/aircraft-knowledge/profiles/hornet/sources")
    entries_response = client.get(
        "/v1/aircraft-knowledge/profiles/hornet/entries",
        params={"category": "communications"},
    )

    assert profile_response.status_code == 200
    assert profile_response.json()["aircraft_id"] == "fa-18c"
    assert source_response.status_code == 200
    assert any(item["source_id"] == FA18_OFFICIAL_SOURCE_ID for item in source_response.json())
    assert entries_response.status_code == 200
    assert entries_response.json()
    assert all(item["category"] == "communications" for item in entries_response.json())


def test_entry_requires_registered_sources() -> None:
    with pytest.raises(ValueError, match="Unknown source ids"):
        aircraft_knowledge.upsert_entry(
            KnowledgeEntry(
                entry_id="fa18-test-without-source",
                aircraft_id="fa-18c",
                category=KnowledgeCategory.NAVIGATION,
                title="Test entry",
                summary="Test summary",
                source_ids=["missing-source"],
            )
        )


def test_cited_entry_can_be_searched() -> None:
    source = aircraft_knowledge.upsert_source(
        KnowledgeSource(
            source_id="official-fa18-manual-test",
            source_type=KnowledgeSourceType.OFFICIAL_MANUAL,
            title="F/A-18C official manual test source",
            publisher="Eagle Dynamics",
            page_or_section="Test section",
        )
    )
    entry = aircraft_knowledge.upsert_entry(
        KnowledgeEntry(
            entry_id="fa18-navigation-test",
            aircraft_id="fa-18c",
            category=KnowledgeCategory.NAVIGATION,
            title="Navigation test topic",
            summary="A test knowledge entry used to validate source tracking and search.",
            tags={"navigation", "test"},
            source_ids=[source.source_id],
            evidence=EvidenceLevel.VERIFIED,
            requires_review=False,
        )
    )

    result = aircraft_knowledge.search(
        KnowledgeSearchQuery(text="source tracking", aircraft_id="fa-18c", verified_only=True)
    )

    assert result.total >= 1
    assert any(item.entry_id == entry.entry_id for item in result.entries)
    profile = aircraft_knowledge.get_profile("fa-18c")
    assert profile is not None
    assert profile.status is ProfileStatus.IN_PROGRESS
    assert profile.entry_count >= 1
    assert profile.source_count >= 1
