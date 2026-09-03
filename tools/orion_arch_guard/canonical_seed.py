from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


CANONICAL_SEED_VERSION = "1"


class CanonicalKind(StrEnum):
    STRATEGY = "CANONICAL_STRATEGY"
    GOLDEN_COMPONENT = "GOLDEN_COMPONENT"
    DO_NOT_REINVENT = "DO_NOT_REINVENT_RULE"
    RETIREMENT = "RETIREMENT_CANDIDATE"
    RECOVERED_IDEA = "RECOVERED_IDEA"
    HISTORICAL_RECONNECT = "HISTORICAL_RECONNECT_ITEM"
    ROADMAP_STAGE = "CANONICAL_ROADMAP_STAGE"
    USER_VALUED_IDEA = "USER_VALUED_FORGOTTEN_IDEA"


class WorkClassification(StrEnum):
    CURRENT_EXTENSION = "CURRENT_EXTENSION"
    HISTORICAL_RECONNECT = "HISTORICAL_RECONNECT"
    HISTORICAL_ADAPTATION = "HISTORICAL_ADAPTATION"
    PARTIAL_IMPLEMENTATION_COMPLETION = "PARTIAL_IMPLEMENTATION_COMPLETION"
    RECOVERED_IDEA_IMPLEMENTATION = "RECOVERED_IDEA_IMPLEMENTATION"
    TRUE_GREENFIELD = "TRUE_GREENFIELD"
    REFACTOR = "REFACTOR"
    REPLACEMENT = "REPLACEMENT"


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    record_id: str
    kind: CanonicalKind
    title: str
    status: str
    capabilities: tuple[str, ...]
    classification: str
    summary: str
    proof_level: str = "HISTORICAL_AUDIT_CONFIRMED"
    recommended_action: str = "PRESERVE"
    priority: str = "GOVERNED"
    user_decision_required: bool = False
    user_valued: bool = False
    source_refs: tuple[str, ...] = ("D74",)
    evidence_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value


def _golden(
    record_id: str,
    title: str,
    capabilities: tuple[str, ...],
    *,
    boundary: str,
    proof: str = "CURRENT_AUTOMATED_OR_FIELD_PROVEN",
    evidence: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("D74",),
) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        kind=CanonicalKind.GOLDEN_COMPONENT,
        title=title,
        status="CURRENT_GOLDEN_COMPONENT",
        capabilities=capabilities,
        classification=WorkClassification.CURRENT_EXTENSION,
        summary=f"Protected current building block; owner/boundary: {boundary}.",
        proof_level=proof,
        recommended_action="REUSE_AND_PRESERVE",
        source_refs=(*sources, "D74") if "D74" not in sources else sources,
        evidence_refs=evidence,
        metadata={
            "owner_boundary": boundary,
            "reuse_instruction": "Reconnect to this component before adding a parallel owner.",
            "allowed_adaptation": "Bounded adaptation with differential validation.",
            "prohibited_reinvention": "Parallel duplicate owner or protocol stack.",
            "revalidation_triggers": ["ownership change", "provider/session change", "wire boundary change"],
        },
    )


GOLDEN_COMPONENTS: tuple[CanonicalRecord, ...] = (
    _golden("GC01", "Flight Bridge", ("DCS_TELEMETRY", "FLIGHT_CONTEXT"), boundary="DCS export to Core telemetry ingress", sources=("D13", "D26")),
    _golden("GC02", "Mission Bridge", ("MISSION_TRUTH", "WORLD_MODEL"), boundary="DCS mission provenance ingress", sources=("D13", "D26")),
    _golden("GC03", "FlightContextService", ("FLIGHT_CONTEXT",), boundary="Core-owned normalized live flight context", sources=("D26", "D40"), evidence=("STAGE6A_FIELD_20260825",)),
    _golden("GC04", "WorldModel and provenance contracts", ("WORLD_MODEL",), boundary="Core factual truth and provenance", sources=("D26", "D45")),
    _golden("GC05", "FlightContext update gate", ("FLIGHT_CONTEXT", "LIVE_DCS_FACT_PRESENTATION"), boundary="bounded materially-changed context injection", sources=("D40", "5896c4d961f502a4a59cbb31de3d533de8dfebe6"), evidence=("STAGE6A_FIELD_20260825",)),
    _golden("GC06", "Core fact binding", ("WORLD_MODEL", "NATURAL_INFORMATIONAL_PRESENTATION"), boundary="Core owns exact informational facts", sources=("D45", "D72", "27e94bdbf843a3f1895db2756eed49e42fe07989"), evidence=("AIRCRAFT_FA18_FIELD", "AIRCRAFT_F5_FIELD")),
    _golden("GC07", "Placeholder fact validation", ("NATURAL_INFORMATIONAL_PRESENTATION",), boundary="Core validates provider output against bound facts", sources=("D72", "27e94bdbf843a3f1895db2756eed49e42fe07989"), evidence=("AIRCRAFT_FA18_FIELD", "AIRCRAFT_F5_FIELD")),
    _golden("GC08", "ToolGateway and receipts", ("TOOL_CALLING",), boundary="bounded tools, permissions and receipts", sources=("D12", "D46")),
    _golden("GC09", "InteractionRouter known-contract seam", ("INTERACTION_ROUTING",), boundary="known semantic contract selection", sources=("D49", "D68"), evidence=("PURE_TAKEOFF_FIELD",)),
    _golden("GC10", "OSU protected presentation", ("OSU", "PHRASEOLOGY", "PROTECTED_OPERATIONAL_COMMUNICATION"), boundary="Core-owned protected wording", sources=("D55", "D63", "D68"), evidence=("PURE_TAKEOFF_FIELD",)),
    _golden("GC11", "Persistent ATC session", ("VIRTUAL_ATC", "ATC_STATUS", "PERSISTENT_STATE"), boundary="Core-owned multi-turn ATC state", sources=("D03", "D21", "6dea803e9deac09d0ed9e59d7b60cb6368a7a83e"), evidence=("PERSISTENT_ATC_FIELD",)),
    _golden("GC12", "SpeechKit v3 External EOU STT", ("SPEECHKIT_STT", "EOU", "STT"), boundary="native STT finalization after physical PTT end", sources=("D65", "255f2007abd44885d24d8dd2e45974d2873e4b14"), evidence=("SPEECHKIT_EXTERNAL_EOU_FIELD",)),
    _golden("GC13", "UDP7082 true-to-false EOU", ("UDP7082", "PTT", "EOU"), boundary="authoritative official-SRS physical PTT transition", sources=("D66", "55e70f83c839ef2f3a375167785c33feca2a9125"), evidence=("UDP7082_FIELD",)),
    _golden("GC14", "SRS candidate buffering", ("SRS", "PTT", "RADIO_SCHEDULING"), boundary="PCM admitted only after local TX ownership", sources=("D65", "D66", "43c364afaa24cbab4f5e7938b9d3e2a3e28befce"), evidence=("SPEECHKIT_EXTERNAL_EOU_FIELD",)),
    _golden("GC15", "Cadence-aware TX liveness", ("UDP7082", "PTT", "RADIO_SCHEDULING"), boundary="sender-cadence-aware stale detection", sources=("D66", "5cc976a26b12be0520d560cda88ac47fbd1cda4b"), evidence=("CADENCE_LIVENESS_FIELD",)),
    _golden("GC16", "RadioRouter plus canonical SRS adapter and RadioInfo", ("RADIO_ROUTER", "SRS"), boundary="provider-neutral routing to wire-compatible SRS transport", sources=("D36", "D38", "D60"), evidence=("UDP7082_FIELD",)),
    _golden("GC17", "Streaming SpeechKit TTS", ("SPEECHKIT_TTS", "TTS", "RADIO_SCHEDULING"), boundary="one finalized response to one paced SRS transmission", sources=("D67", "090271039c841b0dafc1e5f139d42aca9888f933"), evidence=("PERSISTENT_ATC_FIELD",)),
    _golden("GC18", "Evidence, build identity and Architecture Guard governance", ("EVIDENCE", "PACKAGING", "ARCHITECTURE_GOVERNANCE"), boundary="safe field evidence and development governance", sources=("D27", "D41", "D71", "D73", "D74")),
)


HISTORICAL_RECONNECT_ITEMS: tuple[CanonicalRecord, ...] = (
    CanonicalRecord(
        record_id="HR01",
        kind=CanonicalKind.HISTORICAL_RECONNECT,
        title="Persistent Realtime Session",
        status="HISTORICAL_GOLDEN_CANDIDATE",
        capabilities=("YANDEX_REALTIME", "NATURAL_INFORMATIONAL_PRESENTATION", "FLIGHT_CONTEXT"),
        classification=WorkClassification.HISTORICAL_ADAPTATION,
        summary="Stage 6A persistent Realtime presenter adapted to current Core fact binding and placeholder validation.",
        proof_level="HISTORICAL_FIELD_PROVEN_CURRENT_BENCHMARK_NO_GO",
        recommended_action="RECONNECT_AND_REVALIDATE",
        priority="NEXT",
        source_refs=("D40", "D71", "D72", "D74", "f64d8424d0cfd00543d18a2f0c1fa5a6f81b6b05"),
        evidence_refs=("IPB-20260903-171624",),
        metadata={
            "disposition": "KEEP",
            "production_default": False,
            "benchmark_verdict": "BENCHMARK_NO_GO",
            "successful_warm_median_ms": 357,
            "successful_warm_p90_ms": 515,
            "validator_accepted": "56/56",
            "invalid_downstream_outputs": 0,
            "failure_rate_percent": 30,
            "failure_concentration": "especially RU",
            "promotion_gate": "reliability correction, isolated benchmark PASS, bounded selector, controlled field test",
        },
    ),
    CanonicalRecord(
        record_id="HR02",
        kind=CanonicalKind.HISTORICAL_RECONNECT,
        title="RadioEntity to VoiceProfile resolver",
        status="DISCONNECTED_VALUABLE_MECHANISM",
        capabilities=("RADIO_ENTITY", "VOICE_IDENTITY"),
        classification=WorkClassification.HISTORICAL_RECONNECT,
        summary="Historically designed stable radio identity and per-entity voice seam; not production-wired.",
        proof_level="HISTORICAL_CONTRACT_AND_PROBE",
        recommended_action="RECONNECT_WHEN_PRODUCT_SEQUENCE_REACHES_MULTI_VOICE",
        priority="PRODUCT_BACKLOG",
        user_valued=True,
        source_refs=("D58", "D59", "D74"),
        metadata={
            "current_state": "DISCONNECTED",
            "historical_best": "RADIO_ENTITY mechanism and voice probe",
            "blocker": "Persistent VoiceProfile lifecycle and runtime binding are unfinished.",
            "proof_required": "deterministic identity binding, persistence, and controlled multi-entity field proof",
        },
    ),
)


def _rule(record_id: str, title: str, capability: str, best: str) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        kind=CanonicalKind.DO_NOT_REINVENT,
        title=title,
        status="CURRENT_RULE",
        capabilities=(capability,),
        classification="DO_NOT_REINVENT",
        summary=f"Reuse {best}; the historical record already contains the governing mechanism.",
        recommended_action="BLOCK_DUPLICATE_BY_DEFAULT",
        source_refs=("D71", "D74"),
        metadata={"best_existing_mechanism": best, "exception": "Explicit FULL Guard differential and user decision."},
    )


DO_NOT_REINVENT_RULES: tuple[CanonicalRecord, ...] = (
    _rule("DNR01", "Do not create a second WorldModel", "WORLD_MODEL", "Core WorldModel/provenance contracts"),
    _rule("DNR02", "Do not create a second ToolGateway", "TOOL_CALLING", "ToolGateway and receipts"),
    _rule("DNR03", "Do not create a second RadioRouter", "RADIO_ROUTER", "RadioRouter"),
    _rule("DNR04", "Do not create another authoritative PTT-end heuristic", "EOU", "UDP7082 true-to-false EOU"),
    _rule("DNR05", "Do not restore packet-gap EOU", "EOU", "UDP7082 true-to-false EOU"),
    _rule("DNR06", "Do not restore fixed-timeout TX liveness", "UDP7082", "cadence-aware TX liveness"),
    _rule("DNR07", "Do not give protected operational wording to AI", "PHRASEOLOGY", "OSU protected presentation"),
    _rule("DNR08", "Do not create a parallel persistent ATC state owner", "VIRTUAL_ATC", "persistent Core ATC session"),
    _rule("DNR09", "Do not create another Communication Profile store", "COMMUNICATION_PROFILE", "versioned profile pack lifecycle"),
    _rule("DNR10", "Do not rebuild SRS transport", "SRS", "canonical SRS adapter and RadioInfo"),
    _rule("DNR11", "Do not create a second Realtime protocol stack", "YANDEX_REALTIME", "existing and historical provider/session mechanisms"),
    _rule("DNR12", "Do not restore permanent Whisper by default", "STT", "SpeechKit v3 External EOU STT"),
    _rule("DNR13", "Do not restore four hard language modes", "LANGUAGE_POLICY", "automatic input-language policy independent of Communication Profile"),
    _rule("DNR14", "Do not treat the 20-30 Pilot corpus as production Phraseology KB", "PHRASEOLOGY", "test-corpus-only decision"),
    _rule("DNR15", "Do not interpret current absence as historical absence", "ARCHITECTURE_GOVERNANCE", "three-layer canonical history search"),
)


def _retire(record_id: str, title: str, capability: str, reason: str) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        kind=CanonicalKind.RETIREMENT,
        title=title,
        status="DO_NOT_RESTORE_BY_DEFAULT",
        capabilities=(capability,),
        classification="RETIREMENT_CANDIDATE",
        summary=reason,
        recommended_action="RETAIN_HISTORY_NOT_PRODUCTION_DEFAULT",
        source_refs=("D74",),
        metadata={"historical_artifacts": "PRESERVE", "retirement_meaning": "Do not restore to production by default."},
    )


RETIREMENT_CANDIDATES: tuple[CanonicalRecord, ...] = (
    _retire("RC01", "Packet-gap EOU as authoritative boundary", "EOU", "Superseded by physical UDP7082 true-to-false ownership."),
    _retire("RC02", "Fixed-timeout TX-state liveness", "UDP7082", "Superseded by cadence-aware liveness."),
    _retire("RC03", "Provider or VAD owned physical PTT end", "PTT", "Provider finalization cannot own official-SRS physical PTT end."),
    _retire("RC04", "Four hard language modes", "LANGUAGE_POLICY", "Language and aviation Communication Profile are independent."),
    _retire("RC05", "Permanent Whisper worker or fallback", "STT", "Explicitly removed footprint; current SpeechKit path exists."),
    _retire("RC06", "SAPI as primary production presentation", "TTS", "Superseded by provider-neutral streaming SpeechKit presentation."),
    _retire("RC07", "Universal mandatory-Qwen operational route", "INTERACTION_ROUTING", "Protected operational contracts remain deterministic/Core-owned."),
    _retire("RC08", "Pilot 20-30 corpus as production KB", "PHRASEOLOGY", "The number described only a Mixed Composition test corpus."),
)


_IDEAS: tuple[tuple[str, str, tuple[str, ...], str, str, bool], ...] = (
    ("U01", "Unified MODEL C domain migration", ("INTERACTION_ROUTING", "OSU"), "Complete bounded domain migration without changing truth ownership.", "HIGH", False),
    ("U02", "Full Airport ATC lifecycle", ("VIRTUAL_ATC", "ATC_HANDOFF"), "Extend persistent ATC through the full airport lifecycle.", "HIGH", True),
    ("U03", "Carrier ATC runtime", ("CARRIER_ATC",), "Implement carrier-specific runtime over shared contracts.", "FUTURE", False),
    ("U04", "AWACS/GCI conversational route", ("AWACS_GCI",), "Restore the approved AWACS/GCI product direction using current truth boundaries.", "PRODUCT", True),
    ("U05", "Full AAR voice lifecycle", ("AAR",), "Complete tanker/AAR multi-turn voice lifecycle.", "PRODUCT", True),
    ("U06", "JTAC laser/smoke coordination", ("JTAC_FAC",), "Complete bounded JTAC laser and smoke coordination.", "PRODUCT", True),
    ("U07", "Mission Control unified voice route", ("MISSION_CONTROL",), "Unify Mission Control voice interactions on shared routing.", "PRODUCT", True),
    ("U08", "Verified normative phraseology packs", ("PHRASEOLOGY", "COMMUNICATION_PROFILE"), "Build verified, versioned normative content packs.", "HIGH", False),
    ("U09", "Broad deterministic recognition", ("PHRASEOLOGY", "INTERACTION_ROUTING"), "Generalize recognition beyond the Pilot test corpus.", "HIGH", False),
    ("U10", "RadioEntity to VoiceProfile resolver", ("RADIO_ENTITY", "VOICE_IDENTITY"), "Reconnect persistent per-entity voices.", "PRODUCT", True),
    ("U11", "Busy-channel collision and preemption scheduler", ("RADIO_SCHEDULING",), "Add radio-safe collision and urgency scheduling.", "HIGH", False),
    ("U12", "Trusted third-party radio identity correlation", ("RADIO_ENTITY", "SRS"), "Correlate trusted external radio identity without weakening provenance.", "FUTURE", False),
    ("U13", "All-aircraft and rotorcraft knowledge adapters", ("AIRCRAFT_IDENTITY",), "Generalize aircraft knowledge beyond proof modules.", "PRODUCT", True),
    ("U14", "Runtime Modules UI and enforcement", ("LAUNCHER", "RUNTIME_MODULES"), "Make module selection visible and enforced at runtime.", "PRODUCT", False),
    ("U15", "Modular aircraft and component installer", ("INSTALLER", "RUNTIME_MODULES"), "Install bounded aircraft/components selectively.", "FUTURE", False),
    ("U16", "Selective uninstall and data-retention UX", ("INSTALLER", "SECURITY"), "Give explicit component/data retention control.", "FUTURE", False),
    ("U17", "Privacy-aware post-flight debrief", ("DEBRIEF", "SECURITY"), "Provide bounded post-flight debrief without unsafe retention.", "PRODUCT", True),
    ("U18", "Current information and news connector", ("NEWS", "NATURAL_CONVERSATION"), "Restore opt-in current-information conversation.", "PRODUCT", True),
    ("U19", "Mission Editor assistant", ("MISSION_EDITOR",), "Assist mission authoring through bounded tools.", "FUTURE", False),
    ("U20", "Native VR status overlay", ("VR_OVERLAY", "LAUNCHER"), "Expose compact ORION state in VR.", "FUTURE", False),
)


RECOVERED_IDEAS: tuple[CanonicalRecord, ...] = tuple(
    CanonicalRecord(
        record_id=idea_id,
        kind=CanonicalKind.RECOVERED_IDEA,
        title=title,
        status="USER_VALUED_UNIMPLEMENTED" if user_valued else "RECOVERED",
        capabilities=capabilities,
        classification=WorkClassification.RECOVERED_IDEA_IMPLEMENTATION,
        summary=intent,
        proof_level="HISTORICAL_INTENT_RECOVERED",
        recommended_action="PRESERVE_ON_ROADMAP",
        priority=priority,
        user_decision_required=True,
        user_valued=user_valued,
        source_refs=("D74",),
        metadata={
            "original_user_intent": intent,
            "approval_status": "VALUABLE_DIRECTION_RECOVERED",
            "design_maturity": "VARIES_REQUIRES_BOUNDED_PREFLIGHT",
            "implementation_status": "NOT_FULLY_IMPLEMENTED",
            "historical_work_available": "QUERY_GUARD_BY_CAPABILITY",
            "dependencies": list(capabilities),
            "why_unfinished": "Historical roadmap item not completed; no rejection recorded.",
            "canonical_compatibility": "COMPATIBLE_SUBJECT_TO_GUARD",
            "allowed_transitions": ["DESIGNED", "APPROVED_IMPLEMENTATION", "IMPLEMENTING", "AUTOMATED_PROVEN", "FIELD_PROVEN", "PRODUCTIZED", "DEFERRED", "REJECTED", "OBSOLETE"],
        },
    )
    for idea_id, title, capabilities, intent, priority, user_valued in _IDEAS
)


CANONICAL_STRATEGIES: tuple[CanonicalRecord, ...] = (
    CanonicalRecord(
        record_id="STRATEGY_A_CURRENT_RECONNECT",
        kind=CanonicalKind.STRATEGY,
        title="Canonical current baseline plus historical reconnect",
        status="APPROVED_CURRENT",
        capabilities=("ARCHITECTURE_GOVERNANCE",),
        classification="CANONICAL_STRATEGY",
        summary="Current lineage is canonical; reconnect/adapt proven historical mechanisms, preserve stronger current mechanisms, and retain approved unfinished ideas.",
        proof_level="USER_APPROVED_FORENSIC_CONCLUSION",
        recommended_action="RECONNECT_ADAPT_EXTEND_REFACTOR_REPLACE",
        source_refs=("D71", "D74", "AG-20260903-173329-291b1626-f64d842-r2"),
        metadata={
            "single_historical_baseline_sufficient": False,
            "wholesale_rollback": False,
            "three_layers": ["CURRENT_BEST", "HISTORICAL_BEST", "RECOVERED_UNIMPLEMENTED_IDEA"],
        },
    ),
)


_USER_VALUED: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("UV01", "Full Virtual ATC lifecycle", "U02", ("VIRTUAL_ATC",)),
    ("UV02", "AWACS/GCI", "U04", ("AWACS_GCI",)),
    ("UV03", "AAR tanker assistant", "U05", ("AAR",)),
    ("UV04", "JTAC laser and smoke", "U06", ("JTAC_FAC",)),
    ("UV05", "Mission Control", "U07", ("MISSION_CONTROL",)),
    ("UV06", "Persistent voices per RadioEntity", "U10", ("RADIO_ENTITY", "VOICE_IDENTITY")),
    ("UV07", "All aircraft and helicopters", "U13", ("AIRCRAFT_KNOWLEDGE",)),
    ("UV08", "Casual and random conversation", "U01", ("NATURAL_CONVERSATION",)),
    ("UV09", "News and current information", "U18", ("NEWS",)),
    ("UV10", "Post-flight debrief", "U17", ("DEBRIEF",)),
)

USER_VALUED_FORGOTTEN_IDEAS: tuple[CanonicalRecord, ...] = tuple(
    CanonicalRecord(
        record_id=record_id,
        kind=CanonicalKind.USER_VALUED_IDEA,
        title=title,
        status="USER_VALUED_UNIMPLEMENTED",
        capabilities=capabilities,
        classification=WorkClassification.RECOVERED_IDEA_IMPLEMENTATION,
        summary="Protected product direction; must not disappear without explicit reclassification.",
        proof_level="EXPLICIT_USER_VALUE_RECOVERED",
        recommended_action="PRESERVE_UNTIL_EXPLICIT_TRANSITION",
        priority="VISIBLE_NOT_IMMEDIATE",
        user_decision_required=True,
        user_valued=True,
        source_refs=("D74",),
        metadata={"related_recovered_idea": related, "not_completed": True, "not_rejected": True},
    )
    for record_id, title, related, capabilities in _USER_VALUED
)


_STAGES: tuple[tuple[str, str, str], ...] = (
    ("C0", "Historical source recovery", "COMPLETE"),
    ("C1", "Architecture Guard foundation", "COMPLETE"),
    ("C2", "Capability graph and Previous Best gate", "COMPLETE"),
    ("C3", "CANONICAL ORION BASELINE ESTABLISHED", "CURRENT"),
    ("C4", "REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION", "APPROVED_NEXT_STEP"),
    ("C5", "Isolated Realtime benchmark and promotion decision", "PLANNED"),
    ("C6", "Bounded presenter selector", "CONDITIONAL"),
    ("C7", "Controlled DCS/SRS field test", "CONDITIONAL"),
)

CANONICAL_ROADMAP_STAGES: tuple[CanonicalRecord, ...] = tuple(
    CanonicalRecord(
        record_id=stage_id,
        kind=CanonicalKind.ROADMAP_STAGE,
        title=title,
        status=status,
        capabilities=("ARCHITECTURE_GOVERNANCE", "NATURAL_INFORMATIONAL_PRESENTATION") if stage_id >= "C4" else ("ARCHITECTURE_GOVERNANCE",),
        classification="CURRENT_REUSE" if status == "COMPLETE" else "FIELD_PROOF_REQUIRED" if stage_id == "C7" else "HISTORICAL_ADAPTATION" if stage_id in {"C4", "C5"} else "CURRENT_EXTENSION",
        summary="Canonicalization track" if stage_id <= "C3" else "Product reliability and controlled promotion track",
        recommended_action="PRESERVE_ORDER",
        priority="NEXT" if status == "APPROVED_NEXT_STEP" else "ORDERED",
        source_refs=("D74",),
        metadata={"track": "CANONICALIZATION" if stage_id <= "C3" else "PRODUCT_EXPANSION"},
    )
    for stage_id, title, status in _STAGES
)


ALL_CANONICAL_RECORDS: tuple[CanonicalRecord, ...] = (
    *CANONICAL_STRATEGIES,
    *GOLDEN_COMPONENTS,
    *DO_NOT_REINVENT_RULES,
    *RETIREMENT_CANDIDATES,
    *RECOVERED_IDEAS,
    *HISTORICAL_RECONNECT_ITEMS,
    *CANONICAL_ROADMAP_STAGES,
    *USER_VALUED_FORGOTTEN_IDEAS,
)


def validate_canonical_seed() -> None:
    identifiers = [record.record_id for record in ALL_CANONICAL_RECORDS]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("canonical record IDs must be globally unique")
    if len(GOLDEN_COMPONENTS) != 18 or len(DO_NOT_REINVENT_RULES) < 15:
        raise ValueError("canonical minimum register cardinality is not satisfied")
    if len(RETIREMENT_CANDIDATES) != 8 or len(RECOVERED_IDEAS) != 20:
        raise ValueError("canonical audit register cardinality is not satisfied")


validate_canonical_seed()
