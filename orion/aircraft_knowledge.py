from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field


class KnowledgeCategory(StrEnum):
    GENERAL = "general"
    COCKPIT = "cockpit"
    CONTROLS = "controls"
    ELECTRICAL = "electrical"
    FUEL = "fuel"
    ENGINES = "engines"
    HYDRAULICS = "hydraulics"
    FLIGHT_CONTROLS = "flight_controls"
    NAVIGATION = "navigation"
    COMMUNICATIONS = "communications"
    AUTOPILOT = "autopilot"
    SENSORS = "sensors"
    RADAR = "radar"
    ELECTRONIC_WARFARE = "electronic_warfare"
    DATALINK = "datalink"
    WEAPONS = "weapons"
    PERFORMANCE = "performance"
    LIMITATIONS = "limitations"
    NORMAL_PROCEDURES = "normal_procedures"
    EMERGENCY_PROCEDURES = "emergency_procedures"
    TROUBLESHOOTING = "troubleshooting"
    CHECKLISTS = "checklists"
    DCS_INTEGRATION = "dcs_integration"


class KnowledgeSourceType(StrEnum):
    OFFICIAL_MANUAL = "official_manual"
    OFFICIAL_CHANGELOG = "official_changelog"
    OFFICIAL_WEBSITE = "official_website"
    MODULE_DOCUMENTATION = "module_documentation"
    DCS_MISSION_DATA = "dcs_mission_data"
    COMMUNITY_GUIDE = "community_guide"
    OPEN_SOURCE = "open_source"
    FLIGHT_TEST = "flight_test"


class EvidenceLevel(StrEnum):
    VERIFIED = "verified"
    CORROBORATED = "corroborated"
    PROVISIONAL = "provisional"
    DISPUTED = "disputed"


class ProfileStatus(StrEnum):
    PLANNED = "planned"
    SKELETON = "skeleton"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    RELEASED = "released"


class KnowledgeSource(BaseModel):
    source_id: str = Field(min_length=1, max_length=160)
    source_type: KnowledgeSourceType
    title: str = Field(min_length=1, max_length=300)
    publisher: str | None = Field(default=None, max_length=160)
    locator: str | None = Field(default=None, max_length=1000)
    version: str | None = Field(default=None, max_length=120)
    page_or_section: str | None = Field(default=None, max_length=240)
    retrieved_at: str | None = Field(default=None, max_length=80)


class KnowledgeEntry(BaseModel):
    entry_id: str = Field(min_length=1, max_length=200)
    aircraft_id: str = Field(min_length=1, max_length=120)
    category: KnowledgeCategory
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=6000)
    tags: set[str] = Field(default_factory=set)
    applicability: list[str] = Field(default_factory=list)
    telemetry_keys: list[str] = Field(default_factory=list)
    procedure_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence: EvidenceLevel = EvidenceLevel.PROVISIONAL
    requires_review: bool = True


class AircraftProfile(BaseModel):
    aircraft_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    aliases: set[str] = Field(default_factory=set)
    priority: int = Field(ge=1)
    status: ProfileStatus = ProfileStatus.PLANNED
    categories: set[KnowledgeCategory] = Field(default_factory=lambda: set(KnowledgeCategory))
    entry_count: int = 0
    source_count: int = 0
    notes: str | None = Field(default=None, max_length=1000)


class KnowledgeSearchQuery(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    aircraft_id: str | None = Field(default=None, max_length=120)
    categories: set[KnowledgeCategory] = Field(default_factory=set)
    verified_only: bool = False


class KnowledgeSearchResult(BaseModel):
    entries: list[KnowledgeEntry] = Field(default_factory=list)
    total: int = 0


DEFAULT_AIRCRAFT_PRIORITY: tuple[tuple[str, str, set[str]], ...] = (
    ("fa-18c", "F/A-18C Hornet", {"hornet", "fa18c", "f/a-18c", "f/a-18c hornet"}),
    ("f-5e", "F-5E Tiger II", {"tiger", "tiger ii", "f5e"}),
    ("p-51d", "P-51D Mustang", {"mustang", "p51", "p-51"}),
    ("mig-21bis", "MiG-21bis", {"mig-21", "миг-21", "fishbed"}),
    ("a-10c-ii", "A-10C II Tank Killer", {"a-10c ii", "a10c2", "tank killer"}),
    ("jf-17", "JF-17 Thunder", {"jf17", "thunder"}),
    ("p-47d", "P-47D Thunderbolt", {"p47", "thunderbolt"}),
    ("spitfire-lf-mk-ix", "Spitfire LF Mk IX", {"spitfire", "spitfire ix"}),
    ("ah-64d", "AH-64D Apache", {"apache", "ah64d"}),
    ("f-16c", "F-16C Viper", {"viper", "f16c"}),
    ("ka-50-iii", "Ka-50 III", {"ka-50", "black shark"}),
    ("mi-24p", "Mi-24P Hind", {"mi-24", "hind"}),
    ("mi-8mtv2", "Mi-8MTV2", {"mi-8", "hip"}),
    ("f-14", "F-14 Tomcat", {"tomcat", "f14"}),
    ("mirage-2000c", "Mirage 2000C", {"m2000c", "mirage"}),
    ("av-8b", "AV-8B N/A", {"harrier", "av8b"}),
    ("f-15e", "F-15E Strike Eagle", {"strike eagle", "f15e"}),
)

FA18_OFFICIAL_SOURCE_ID = "ed-fa18c-early-access-guide-en"
FA18_OFFICIAL_GUIDE_URL = (
    "https://www.digitalcombatsimulator.com/en/downloads/documentation/"
    "dcs-hornet_early_access_guide_en/"
)

FA18_BASELINE_ENTRIES: tuple[KnowledgeEntry, ...] = (
    KnowledgeEntry(
        entry_id="fa18-general-role",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.GENERAL,
        title="F/A-18C multirole operating scope",
        summary=(
            "The DCS F/A-18C knowledge profile covers the Hornet as a carrier-capable multirole aircraft. "
            "ORION should answer aircraft-specific questions by combining this profile with cited manual sections "
            "instead of relying on generic fighter assumptions."
        ),
        tags={"hornet", "multirole", "carrier", "general"},
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-communications-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.COMMUNICATIONS,
        title="Hornet communications knowledge scope",
        summary=(
            "Communications knowledge for the Hornet includes its two cockpit communication radios, preset-channel "
            "use, manual frequency entry where supported, radio selection and mission-provided radio data. ORION must "
            "prefer mission/live data for current frequencies and presets when that data is available."
        ),
        tags={"comm1", "comm2", "radio", "preset", "frequency"},
        applicability=["cockpit radios", "mission radio presets"],
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-navigation-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.NAVIGATION,
        title="Hornet navigation knowledge scope",
        summary=(
            "Navigation knowledge includes HSI-based navigation, waypoint handling, TACAN, aircraft navigation data "
            "and INS/GPS-related operation. Dynamic mission values such as tanker or airfield TACAN channels must be "
            "taken from mission/live data rather than hard-coded into the aircraft profile."
        ),
        tags={"hsi", "waypoint", "tacan", "ins", "gps", "navigation"},
        applicability=["navigation", "tacan", "waypoints"],
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-radar-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.RADAR,
        title="Hornet radar knowledge scope",
        summary=(
            "Radar knowledge is aircraft-specific and includes air-to-air radar operation, track and search modes, "
            "multi-sensor integration concepts and air-to-ground radar modes documented for the DCS module. "
            "Detailed procedural answers should reference the relevant manual section before execution guidance."
        ),
        tags={"radar", "air-to-air", "air-to-ground", "tws", "stt", "msi"},
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-sensors-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.SENSORS,
        title="Hornet sensor knowledge scope",
        summary=(
            "Sensor knowledge includes the aircraft displays, targeting-sensor workflows, helmet-mounted display "
            "integration and sensor-control concepts documented for the DCS Hornet. ORION should distinguish "
            "aircraft capability from the sensors actually loaded in the current mission."
        ),
        tags={"sensors", "targeting", "hmd", "displays"},
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-weapons-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.WEAPONS,
        title="Hornet weapons knowledge scope",
        summary=(
            "Weapons knowledge is organized by air-to-air and air-to-ground employment and must remain tied to the "
            "specific DCS module implementation. ORION should use mission loadout data to determine what is actually "
            "available before giving aircraft-specific employment guidance."
        ),
        tags={"weapons", "air-to-air", "air-to-ground", "stores", "loadout"},
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
    KnowledgeEntry(
        entry_id="fa18-procedures-overview",
        aircraft_id="fa-18c",
        category=KnowledgeCategory.NORMAL_PROCEDURES,
        title="Hornet procedure-answering policy",
        summary=(
            "Normal-procedure answers should be assembled from cited Hornet manual procedures and the current "
            "aircraft state. The knowledge layer separates stable aircraft procedure knowledge from live cockpit "
            "telemetry so ORION can answer both 'how is this done?' and 'what should I do next right now?'."
        ),
        tags={"procedures", "checklist", "aircraft-state", "workflow"},
        source_ids=[FA18_OFFICIAL_SOURCE_ID],
        evidence=EvidenceLevel.VERIFIED,
        requires_review=False,
    ),
)


class AircraftKnowledgeRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._profiles: dict[str, AircraftProfile] = {}
        self._entries: dict[str, KnowledgeEntry] = {}
        self._sources: dict[str, KnowledgeSource] = {}
        self._seed_profiles()
        self._seed_fa18c_baseline()

    def _seed_profiles(self) -> None:
        for priority, (aircraft_id, display_name, aliases) in enumerate(DEFAULT_AIRCRAFT_PRIORITY, start=1):
            self._profiles[aircraft_id] = AircraftProfile(
                aircraft_id=aircraft_id,
                display_name=display_name,
                aliases=aliases,
                priority=priority,
                status=ProfileStatus.SKELETON if aircraft_id == "fa-18c" else ProfileStatus.PLANNED,
                notes=(
                    "Initial AKL profile. Content must be populated from cited sources and reviewed."
                    if aircraft_id == "fa-18c"
                    else None
                ),
            )

    def _seed_fa18c_baseline(self) -> None:
        self._sources[FA18_OFFICIAL_SOURCE_ID] = KnowledgeSource(
            source_id=FA18_OFFICIAL_SOURCE_ID,
            source_type=KnowledgeSourceType.OFFICIAL_MANUAL,
            title="DCS: F/A-18C Early Access Guide",
            publisher="Eagle Dynamics",
            locator=FA18_OFFICIAL_GUIDE_URL,
            version="official online documentation",
            page_or_section="aircraft systems and operating procedures",
        )
        for entry in FA18_BASELINE_ENTRIES:
            self._entries[entry.entry_id] = entry.model_copy(deep=True)
        self._profiles["fa-18c"].status = ProfileStatus.IN_PROGRESS
        self._profiles["fa-18c"].notes = (
            "Baseline Hornet AKL seeded from the official Eagle Dynamics guide. "
            "Detailed section-level knowledge is expanded incrementally and remains source-traceable."
        )
        self._refresh_counts()

    def list_profiles(self) -> list[AircraftProfile]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(self._profiles.values(), key=lambda x: x.priority)]

    def get_profile(self, aircraft_id: str) -> AircraftProfile | None:
        resolved = self.resolve_aircraft_id(aircraft_id)
        if resolved is None:
            return None
        with self._lock:
            profile = self._profiles.get(resolved)
            return profile.model_copy(deep=True) if profile else None

    def resolve_aircraft_id(self, value: str) -> str | None:
        needle = value.strip().casefold()
        if not needle:
            return None
        with self._lock:
            for profile in self._profiles.values():
                candidates = {profile.aircraft_id.casefold(), profile.display_name.casefold()}
                candidates.update(alias.casefold() for alias in profile.aliases)
                if needle in candidates:
                    return profile.aircraft_id
        return None

    def list_sources(self, aircraft_id: str | None = None) -> list[KnowledgeSource]:
        with self._lock:
            if aircraft_id is None:
                source_ids = set(self._sources)
            else:
                resolved = self.resolve_aircraft_id(aircraft_id)
                if resolved is None:
                    return []
                source_ids = {
                    source_id
                    for entry in self._entries.values()
                    if entry.aircraft_id == resolved
                    for source_id in entry.source_ids
                }
            return [
                self._sources[source_id].model_copy(deep=True)
                for source_id in sorted(source_ids)
                if source_id in self._sources
            ]

    def list_entries(
        self,
        aircraft_id: str,
        category: KnowledgeCategory | None = None,
    ) -> list[KnowledgeEntry]:
        resolved = self.resolve_aircraft_id(aircraft_id)
        if resolved is None:
            return []
        with self._lock:
            entries = [
                entry.model_copy(deep=True)
                for entry in self._entries.values()
                if entry.aircraft_id == resolved and (category is None or entry.category is category)
            ]
        entries.sort(key=lambda item: (item.category.value, item.title))
        return entries

    def upsert_source(self, source: KnowledgeSource) -> KnowledgeSource:
        with self._lock:
            self._sources[source.source_id] = source.model_copy(deep=True)
            self._refresh_counts()
            return source.model_copy(deep=True)

    def upsert_entry(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        with self._lock:
            if entry.aircraft_id not in self._profiles:
                raise KeyError("Aircraft profile not found")
            unknown_sources = [source_id for source_id in entry.source_ids if source_id not in self._sources]
            if unknown_sources:
                raise ValueError(f"Unknown source ids: {', '.join(unknown_sources)}")
            self._entries[entry.entry_id] = entry.model_copy(deep=True)
            profile = self._profiles[entry.aircraft_id]
            if profile.status in {ProfileStatus.PLANNED, ProfileStatus.SKELETON}:
                profile.status = ProfileStatus.IN_PROGRESS
            self._refresh_counts()
            return entry.model_copy(deep=True)

    def search(self, query: KnowledgeSearchQuery) -> KnowledgeSearchResult:
        needle = query.text.casefold()
        resolved_aircraft_id = self.resolve_aircraft_id(query.aircraft_id) if query.aircraft_id else None
        if query.aircraft_id and resolved_aircraft_id is None:
            return KnowledgeSearchResult()
        with self._lock:
            matches = []
            for entry in self._entries.values():
                if resolved_aircraft_id and entry.aircraft_id != resolved_aircraft_id:
                    continue
                if query.categories and entry.category not in query.categories:
                    continue
                if query.verified_only and entry.evidence is not EvidenceLevel.VERIFIED:
                    continue
                haystack = " ".join((entry.title, entry.summary, *entry.tags, *entry.applicability)).casefold()
                if needle in haystack:
                    matches.append(entry.model_copy(deep=True))
            matches.sort(key=lambda item: (item.aircraft_id, item.category.value, item.title))
            return KnowledgeSearchResult(entries=matches, total=len(matches))

    def _refresh_counts(self) -> None:
        for profile in self._profiles.values():
            profile.entry_count = sum(entry.aircraft_id == profile.aircraft_id for entry in self._entries.values())
            source_ids = {
                source_id
                for entry in self._entries.values()
                if entry.aircraft_id == profile.aircraft_id
                for source_id in entry.source_ids
            }
            profile.source_count = len(source_ids)


aircraft_knowledge = AircraftKnowledgeRegistry()
