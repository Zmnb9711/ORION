import pytest

from orion.aircraft_knowledge import (
    EvidenceLevel,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeSearchQuery,
    KnowledgeSource,
    KnowledgeSourceType,
    ProfileStatus,
    aircraft_knowledge,
)


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
    assert profiles[0].status is ProfileStatus.SKELETON


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
