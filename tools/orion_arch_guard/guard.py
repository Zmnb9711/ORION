from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.graph import CapabilityGraph, normalize_alias
from tools.orion_arch_guard.guard_rules import (
    AG3_RULESET_VERSION,
    ARCHITECTURE_SENSITIVE_CAPABILITIES,
    MODE_ESCALATION_TERMS,
    PERFORMANCE_SEEDS,
    RULE_CAPABILITIES,
)
from tools.orion_arch_guard.privacy import redact_text
from tools.orion_arch_guard.schema import connect_index, migrate


class GuardMode(StrEnum):
    FULL = "FULL"
    STANDARD = "STANDARD"
    LIGHT = "LIGHT"


class ArchitectureGate(StrEnum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    USER_DECISION_REQUIRED = "USER_DECISION_REQUIRED"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"


@dataclass(frozen=True, slots=True)
class PreflightInput:
    mode: GuardMode
    task_title: str
    task_description: str = ""
    proposed_change: str = ""
    affected_files: tuple[str, ...] = ()
    explicit_capabilities: tuple[str, ...] = ()
    current_head: str = ""
    user_constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredReport:
    result: dict[str, Any]
    human_report: str
    json_path: Path | None = None
    human_path: Path | None = None


@dataclass(slots=True)
class _CapabilityMatch:
    capability_id: str
    confidence: float
    matched_terms: set[str] = field(default_factory=set)


_HEX_HEAD = re.compile(r"[0-9a-fA-F]{7,40}\Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_text(value: str, *, limit: int = 4000) -> str:
    return redact_text(" ".join(value.replace("\x00", " ").split()))[:limit]


def _decoded(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in list(result):
        if key.endswith("_json") and result[key]:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


class ArchitectureGuard:
    def __init__(
        self,
        database_path: Path,
        *,
        reports_dir: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = database_path.absolute()
        self.connection = connect_index(self.database_path)
        migrate(self.connection)
        self.graph = CapabilityGraph(self.database_path)
        self.reports_dir = (
            reports_dir
            or self.database_path.parent / "reports"
        ).absolute()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._ensure_performance_metrics()

    def close(self) -> None:
        self.graph.close()
        self.connection.close()

    def preflight(self, request: PreflightInput, *, store: bool = True) -> StoredReport:
        safe_request = self._sanitize_request(request)
        combined = self._combined_text(safe_request)
        scenarios = self._detect_scenarios(combined)
        capabilities, candidates = self._expand_capabilities(safe_request, scenarios)
        history = self._history(capabilities)
        coverage = self._history_coverage(history)
        ownership_drift = self._ownership_drift(scenarios, combined)
        effective_mode, escalation = self._effective_mode(
            safe_request.mode, capabilities, ownership_drift, combined
        )
        conflicts = self._conflicts(scenarios, combined, capabilities)
        previous_best = self._previous_best(scenarios, history, combined)
        performance = self._performance(capabilities, scenarios)
        evidence_reuse = self._evidence_reuse(scenarios, history, conflicts)

        if coverage["architecture_critical_missing"]:
            gate = ArchitectureGate.INCOMPLETE_HISTORY
        elif any(item["severity"] == "BLOCK" for item in conflicts):
            gate = ArchitectureGate.BLOCK
        elif (
            any(item["severity"] == "USER_DECISION_REQUIRED" for item in conflicts)
            or (ownership_drift and effective_mode is GuardMode.FULL)
            or not capabilities
        ):
            gate = ArchitectureGate.USER_DECISION_REQUIRED
        else:
            gate = ArchitectureGate.PASS

        primary_evidence = self._primary_evidence(history)
        index_signature = self._index_signature()
        task_hash = canonical_sha256(asdict(safe_request))
        logical_payload: dict[str, Any] = {
            "mode_requested": safe_request.mode.value,
            "mode_effective": effective_mode.value,
            "mode_escalation_reasons": escalation,
            "task": asdict(safe_request),
            "head_sha": safe_request.current_head,
            "ruleset_version": AG3_RULESET_VERSION,
            "index_signature": index_signature,
            "affected_capabilities": capabilities,
            "candidate_capabilities": candidates,
            "history_coverage": coverage,
            "decisions": history["decisions"],
            "implementations": history["implementation_buckets"],
            "implementation_records": history["implementations"],
            "previous_best": previous_best,
            "mechanisms": history["mechanisms"],
            "ownership_drift": ownership_drift,
            "performance": performance,
            "evidence_reuse": evidence_reuse,
            "conflicts": conflicts,
            "requires_user_decision": gate is ArchitectureGate.USER_DECISION_REQUIRED,
            "gate": gate.value,
            "primary_evidence": primary_evidence,
        }
        logical_signature = canonical_sha256(logical_payload)
        generated_at = self._now().astimezone(timezone.utc)
        report_id = (
            f"AG-{generated_at.strftime('%Y%m%d-%H%M%S')}-"
            f"{task_hash[:8].casefold()}-{safe_request.current_head[:7].casefold()}-"
            f"r{AG3_RULESET_VERSION}"
        )
        result = {
            "report_id": report_id,
            "generated_at_utc": generated_at.isoformat(),
            "logical_signature": logical_signature,
            **logical_payload,
        }
        human = render_human_report(result)
        json_path: Path | None = None
        human_path: Path | None = None
        if store:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.reports_dir / f"{report_id}.json"
            human_path = self.reports_dir / f"{report_id}.md"
            json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            human_path.write_text(human, encoding="utf-8")
            self._persist(result, safe_request, json_path, human_path)
        return StoredReport(result, human, json_path, human_path)

    @staticmethod
    def _sanitize_request(request: PreflightInput) -> PreflightInput:
        head = request.current_head.casefold()
        if not _HEX_HEAD.fullmatch(head):
            raise ValueError("current_head must be a 7-40 character Git SHA")
        return PreflightInput(
            mode=GuardMode(request.mode),
            task_title=_safe_text(request.task_title),
            task_description=_safe_text(request.task_description),
            proposed_change=_safe_text(request.proposed_change),
            affected_files=tuple(_safe_text(value, limit=500) for value in request.affected_files),
            explicit_capabilities=tuple(
                _safe_text(value, limit=200) for value in request.explicit_capabilities
            ),
            current_head=head,
            user_constraints=tuple(
                _safe_text(value, limit=1000) for value in request.user_constraints
            ),
        )

    @staticmethod
    def _combined_text(request: PreflightInput) -> str:
        return normalize_alias(
            " ".join(
                (
                    request.task_title,
                    request.task_description,
                    request.proposed_change,
                    *request.affected_files,
                    *request.user_constraints,
                )
            )
        )

    @staticmethod
    def _detect_scenarios(text: str) -> set[str]:
        def has(*terms: str) -> bool:
            return all(normalize_alias(term) in text for term in terms)

        scenarios: set[str] = set()
        if (
            "aircraft_identity" in text
            or has("aircraft", "natural")
            or has("live dcs", "natural formulation")
            or has("qwen planner", "informational")
        ):
            scenarios.add("natural_information")
        if ("packet_gap" in text or "packetgap" in text or "quiescence" in text) and (
            "eou" in text or "udp7082" in text or "transmission_end" in text
        ):
            scenarios.add("packet_gap")
        if (
            "four_manual" in text
            or "four_hard" in text
            or all(term in text for term in ("free", "aviation", "ru", "en"))
        ) and "mode" in text:
            scenarios.add("hard_language_modes")
        if "whisper" in text:
            scenarios.add("whisper")
        if "qwen" in text and (
            "protected_atc" in text
            or "protected_clearance" in text
            or ("atc_clearance" in text and "rewrite" in text)
            or ("protected" in text and "phraseology" in text)
        ):
            scenarios.add("protected_qwen")
        if (
            re.search(r"(?:20|twenty)_?(?:to|30|thirty|_30)", text)
            and "phraseology" in text
            and ("production" in text or "limit" in text or "kb" in text)
        ):
            scenarios.add("phraseology_limit")
        if "callsign" in text and "manual" in text and (
            "authoritative" in text or "authority" in text or "launcher" in text
        ):
            scenarios.add("manual_callsign")
        if "srs" in text and (
            "rebuild" in text
            or "new_srs_transport" in text
            or ("build" in text and "transport" in text)
        ):
            scenarios.add("rebuild_srs")
        return scenarios

    def _expand_capabilities(
        self, request: PreflightInput, scenarios: set[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        matches: dict[str, _CapabilityMatch] = {}

        def add(capability_id: str, confidence: float, term: str) -> None:
            current = matches.get(capability_id)
            if current is None:
                current = _CapabilityMatch(capability_id, confidence)
                matches[capability_id] = current
            current.confidence = max(current.confidence, confidence)
            current.matched_terms.add(term)

        for value in request.explicit_capabilities:
            capability_id = self.graph.resolve_capability(value)
            if capability_id is not None:
                add(capability_id, 1.0, f"explicit:{value}")

        padded = f"_{self._combined_text(request)}_"
        for row in self.connection.execute(
            "SELECT capability_id, alias, alias_type FROM capability_aliases ORDER BY alias_key"
        ):
            alias_key = normalize_alias(str(row[1]))
            if len(alias_key) < 4:
                continue
            if f"_{alias_key}_" in padded:
                confidence = 0.95 if str(row[2]) == "STABLE_ID" else 0.88
                add(str(row[0]), confidence, str(row[1]))

        for scenario in scenarios:
            for capability_id in RULE_CAPABILITIES[scenario]:
                add(capability_id, 0.85, f"policy:{scenario}")

        if matches:
            add("ARCHITECTURE_GOVERNANCE", 1.0, "mandatory:D71")

        ordered = sorted(matches.values(), key=lambda item: (-item.confidence, item.capability_id))
        affected = [
            {
                "capability_id": item.capability_id,
                "confidence": round(item.confidence, 2),
                "matched_terms": sorted(item.matched_terms),
            }
            for item in ordered
        ]
        candidates = [item for item in affected if item["confidence"] < 0.8]
        return affected, candidates

    def _history(self, capabilities: Sequence[dict[str, Any]]) -> dict[str, Any]:
        nodes: dict[str, dict[str, dict[str, Any]]] = {
            "decisions": {},
            "implementations": {},
            "mechanisms": {},
            "evidence": {},
            "ownership": {},
        }
        for capability in capabilities:
            related = self.graph.related(str(capability["capability_id"]))
            if related is None:
                continue
            for key, id_key in (
                ("decisions", "decision_id"),
                ("implementations", "implementation_id"),
                ("mechanisms", "mechanism_id"),
                ("evidence", "evidence_id"),
                ("ownership", "assignment_id"),
            ):
                for node in related[key]:
                    nodes[key][str(node[id_key])] = node

        decisions = sorted(nodes["decisions"].values(), key=lambda item: item["decision_id"])
        decision_buckets: dict[str, list[dict[str, Any]]] = {
            key: [] for key in ("CURRENT", "SUPERSEDED", "REJECTED", "DEFERRED", "UNRESOLVED")
        }
        for decision in decisions:
            status = str(decision.get("decision_status", "")).upper()
            if "REJECTED" in status:
                bucket = "REJECTED"
            elif "SUPERSEDED" in status and "SUPERSEDES" not in status:
                bucket = "SUPERSEDED"
            elif "DEFERRED" in status:
                bucket = "DEFERRED"
            elif "UNRESOLVED" in status:
                bucket = "UNRESOLVED"
            else:
                bucket = "CURRENT"
            decision_buckets[bucket].append(decision)

        implementations = sorted(
            nodes["implementations"].values(), key=lambda item: item["implementation_id"]
        )
        implementation_buckets: dict[str, list[str]] = {
            key: []
            for key in (
                "CURRENT",
                "PARTIAL",
                "DISCONNECTED",
                "HISTORICAL_ONLY",
                "PROBE",
                "FIELD_PROVEN",
                "EXPLICITLY_REMOVED",
            )
        }
        for implementation in implementations:
            identifier = str(implementation["implementation_id"])
            runtime = str(implementation.get("runtime_status", "")).upper()
            historical = str(implementation.get("historical_status", "")).upper()
            combined = f"{runtime} {historical}"
            for bucket, marker in (
                ("CURRENT", "CURRENT"),
                ("PARTIAL", "PARTIAL"),
                ("DISCONNECTED", "DISCONNECTED"),
                ("HISTORICAL_ONLY", "HISTORICAL_ONLY"),
                ("PROBE", "PROBE"),
                ("FIELD_PROVEN", "FIELD_PROVEN"),
                ("EXPLICITLY_REMOVED", "EXPLICITLY_REMOVED"),
            ):
                if marker in combined:
                    implementation_buckets[bucket].append(identifier)

        return {
            "decisions": decision_buckets,
            "implementations": implementations,
            "implementation_buckets": implementation_buckets,
            "mechanisms": sorted(
                nodes["mechanisms"].values(), key=lambda item: item["mechanism_id"]
            ),
            "evidence": sorted(nodes["evidence"].values(), key=lambda item: item["evidence_id"]),
            "ownership": sorted(
                nodes["ownership"].values(), key=lambda item: item["assignment_id"]
            ),
        }

    def _history_coverage(self, history: dict[str, Any]) -> dict[str, Any]:
        item_counts = dict(
            self.connection.execute(
                "SELECT item_type, COUNT(*) FROM source_items GROUP BY item_type"
            )
        )
        source_paths = "\n".join(
            str(row[0]).casefold()
            for row in self.connection.execute("SELECT path_reference FROM sources")
        )
        categories = {
            "chatgpt_history": "COMPLETE" if item_counts.get("chatgpt_message", 0) else "UNAVAILABLE",
            "codex_history": "COMPLETE" if item_counts.get("codex_response_item", 0) else "UNAVAILABLE",
            "git_all": "COMPLETE" if item_counts.get("git_commit", 0) else "UNAVAILABLE",
            "deleted_history_lineage": "COMPLETE" if item_counts.get("git_path_change", 0) else "UNAVAILABLE",
            "decision_register": "COMPLETE" if item_counts.get("decision_register_row", 0) == 73 else "PARTIAL",
            "master": "COMPLETE" if "master-architecture" in source_paths else "UNAVAILABLE",
            "development_history": "COMPLETE" if "development-history" in source_paths else "UNAVAILABLE",
            "evidence": "COMPLETE" if item_counts.get("evidence_archive", 0) else "UNAVAILABLE",
            "releases_probes": "COMPLETE" if item_counts.get("release_artifact", 0) else "UNAVAILABLE",
        }
        critical_missing: list[dict[str, str]] = []
        selected: list[tuple[str, str]] = []
        for bucket in history["decisions"].values():
            selected.extend(("DECISION", str(item["decision_id"])) for item in bucket)
        selected.extend(
            ("IMPLEMENTATION", str(item["implementation_id"]))
            for item in history["implementations"]
        )
        selected.extend(
            ("MECHANISM", str(item["mechanism_id"])) for item in history["mechanisms"]
        )
        for node_type, node_id in selected:
            rows = self.connection.execute(
                """
                SELECT source.source_id, source.availability, source.exists_flag
                FROM graph_provenance provenance
                JOIN source_items item ON item.item_id = provenance.source_item_id
                JOIN sources source ON source.source_id = item.source_id
                WHERE provenance.node_type = ? AND provenance.node_id = ?
                """,
                (node_type, node_id),
            ).fetchall()
            if rows and not any(str(row[1]) == "AVAILABLE" and int(row[2]) for row in rows):
                critical_missing.append({"node_type": node_type, "node_id": node_id})
        complete = sum(value == "COMPLETE" for value in categories.values())
        overall = "COMPLETE" if complete == len(categories) else "PARTIAL" if complete else "UNAVAILABLE"
        return {
            "overall": overall,
            "categories": categories,
            "architecture_critical_missing": critical_missing,
        }

    @staticmethod
    def _ownership_drift(scenarios: set[str], text: str) -> list[dict[str, Any]]:
        drift: list[dict[str, Any]] = []

        def add(kind: str, current: str, proposed: str, basis: str) -> None:
            drift.append(
                {
                    "type": kind,
                    "current_or_historical_owner": current,
                    "proposed_owner": proposed,
                    "basis": basis,
                }
            )

        if "natural_information" in scenarios:
            if "qwen" in text and "replace_current_qwen" not in text:
                add(
                    "PRESENTATION_OWNER_CHANGED",
                    "historical persistent Yandex Realtime",
                    "Qwen Planner",
                    "Stage 6A versus proposed/current bounded Planner differential",
                )
                add(
                    "SESSION_MODEL_CHANGED",
                    "PERSISTENT_REALTIME_SESSION",
                    "BOUNDED_PLANNER_CALL",
                    "persistent historical presentation versus stateless formulation",
                )
            else:
                add(
                    "PRESENTATION_OWNER_CHANGED",
                    "CURRENT_QWEN_INFORMATIONAL_FORMULATION",
                    "proposed low-latency natural formulation backend",
                    "proposal replaces current presentation owner",
                )
                add(
                    "SESSION_MODEL_CHANGED",
                    "BOUNDED_PLANNER_CALL",
                    "persistent/warm formulation path",
                    "proposal changes formulation session lifetime",
                )
        if "packet_gap" in scenarios:
            add("PTT_OWNER_CHANGED", "UDP7082 IsSending", "packet-gap heuristic", "D66")
            add("EOU_OWNER_CHANGED", "UDP7082 true-to-false", "packet-gap heuristic", "D66")
        if "whisper" in scenarios:
            add("STT_OWNER_CHANGED", "SpeechKit v3 External EOU", "Whisper fallback", "D34/D65")
        if "protected_qwen" in scenarios:
            add("PROTECTED_WORDING_OWNER_CHANGED", "Core OSU/Phraseology", "Qwen", "D55/D63/D72")
        if "manual_callsign" in scenarios:
            add("FACT_AUTHORITY_CHANGED", "DCS/mission truth", "Launcher manual field", "D14")
        if "rebuild_srs" in scenarios:
            add("RADIO_TRANSPORT_CHANGED", "RadioRouter/SRS adapter", "new SRS transport", "D39/D60/D61/D71")
        return drift

    @staticmethod
    def _effective_mode(
        requested: GuardMode,
        capabilities: Sequence[dict[str, Any]],
        ownership_drift: Sequence[dict[str, Any]],
        text: str,
    ) -> tuple[GuardMode, list[str]]:
        if requested is GuardMode.FULL:
            return requested, []
        bounded_test_only = "test" in text and (
            "without_changing" in text or "no_architecture_change" in text
        )
        sensitive = any(
            item["capability_id"] in ARCHITECTURE_SENSITIVE_CAPABILITIES
            for item in capabilities
        )
        architecture_term = any(normalize_alias(term) in text for term in MODE_ESCALATION_TERMS)
        if ownership_drift or (sensitive and architecture_term and not bounded_test_only):
            reasons = [item["type"] for item in ownership_drift]
            if sensitive and architecture_term:
                reasons.append("ARCHITECTURE_SENSITIVE_CHANGE")
            return GuardMode.FULL, sorted(set(reasons))
        return requested, []

    def _conflicts(
        self, scenarios: set[str], text: str, capabilities: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []

        def add(
            conflict_type: str,
            severity: str,
            message: str,
            decisions: Sequence[str] = (),
            implementations: Sequence[str] = (),
        ) -> None:
            conflicts.append(
                {
                    "conflict_id": canonical_sha256(
                        [conflict_type, severity, message, decisions, implementations]
                    )[:24].casefold(),
                    "type": conflict_type,
                    "severity": severity,
                    "message": message,
                    "decision_ids": list(decisions),
                    "implementation_ids": list(implementations),
                }
            )

        if "packet_gap" in scenarios:
            add(
                "REINTRODUCES_SUPERSEDED_EOU",
                "BLOCK",
                "Packet-gap EOU was superseded after field failure; UDP7082 true-to-false owns physical TX end.",
                ("D66",),
                ("PACKET_GAP_EOU_HEURISTIC", "UDP7082_AUTHORITATIVE_EOU"),
            )
        if "hard_language_modes" in scenarios:
            add(
                "REINTRODUCES_SUPERSEDED_LANGUAGE_MODES",
                "BLOCK",
                "Four hard language modes conflict with automatic input language and Communication Profiles.",
                ("D50", "D51", "D53"),
                ("HARD_FOUR_LANGUAGE_MODES", "COMMUNICATION_PROFILE_INFRASTRUCTURE"),
            )
        if "whisper" in scenarios:
            add(
                "REINTRODUCES_EXPLICITLY_REMOVED_STT",
                "BLOCK",
                "D34 explicitly removed the permanent Whisper fallback; no newer explicit supersession is present.",
                ("D34", "D65"),
                ("WHISPER_STT_WORKER", "SPEECHKIT_V3_EXTERNAL_EOU_STT"),
            )
        if "protected_qwen" in scenarios:
            add(
                "PROTECTED_WORDING_AUTHORITY_REGRESSION",
                "BLOCK",
                "Protected operational wording remains Core/OSU/Phraseology-owned and may not return to Qwen.",
                ("D55", "D63", "D72"),
                ("OSU_PROTECTED_PHRASEOLOGY",),
            )
        if "phraseology_limit" in scenarios:
            add(
                "REJECTED_PRODUCT_KB_LIMIT",
                "BLOCK",
                "The 20-30 phrase number is a test corpus only, not a production Phraseology KB limit.",
                ("D62",),
                ("PILOT_PHRASEOLOGY_TEST_CORPUS", "PILOT_20_30_PRODUCT_KB_INTERPRETATION"),
            )
        if "manual_callsign" in scenarios:
            add(
                "MANUAL_CALLSIGN_FACT_AUTHORITY",
                "BLOCK",
                "D14 assigns callsign truth to DCS/mission provenance rather than duplicate Launcher input.",
                ("D14",),
            )
        if "rebuild_srs" in scenarios:
            add(
                "DUPLICATE_FIELD_PROVEN_RADIO_STACK",
                "BLOCK",
                "A new SRS transport duplicates the field-proven RadioRouter/SRS/UDP7082 stack and violates reconnect-before-rebuild.",
                ("D39", "D60", "D61", "D66", "D71"),
                ("UDP7082_AUTHORITATIVE_EOU", "SRS_CANDIDATE_BUFFERING_IMPLEMENTATION"),
            )
        if "natural_information" in scenarios:
            add(
                "VALID_PRESENTATION_ALTERNATIVES",
                "USER_DECISION_REQUIRED",
                "Historical persistent Realtime and current Core-bound Qwen each preserve different proven strengths; history does not authorize choosing a replacement silently.",
                ("D40", "D71", "D72"),
                ("STAGE6A_FLIGHTCONTEXT_REALTIME", "CURRENT_QWEN_INFORMATIONAL_FORMULATION", "CURRENT_AIRCRAFT_IDENTITY_QUERY"),
            )
        if not capabilities:
            add(
                "AMBIGUOUS_CAPABILITY",
                "USER_DECISION_REQUIRED",
                "No architecture capability could be deterministically resolved from task text or explicit capabilities.",
            )
        return conflicts

    @staticmethod
    def _previous_best(
        scenarios: set[str], history: dict[str, Any], text: str
    ) -> dict[str, Any]:
        implementations = history["implementations"]
        identifiers = [str(item["implementation_id"]) for item in implementations]
        field_proven = history["implementation_buckets"]["FIELD_PROVEN"]
        mechanisms = [
            str(item["mechanism_id"])
            for item in history["mechanisms"]
            if str(item.get("field_probe_status", "")) in {"FIELD_PROVEN", "PROBE_PROVEN", "AUTOMATED_PROVEN"}
        ]
        whole: list[str] = []
        reusable: list[str] = mechanisms
        duplicate = False
        potentially_superior = False
        hybrid = False
        improves: list[str] = []
        regresses: list[str] = []

        if "natural_information" in scenarios:
            reusable = [
                value
                for value in (
                    "PERSISTENT_REALTIME_SESSION",
                    "FLIGHTCONTEXT_UPDATE_GATE",
                    "CORE_FACT_BINDING",
                    "PLACEHOLDER_FACT_VALIDATION",
                )
                if value in [str(item["mechanism_id"]) for item in history["mechanisms"]]
            ]
            potentially_superior = True
            hybrid = True
            duplicate = "qwen" in text and "CURRENT_QWEN_INFORMATIONAL_FORMULATION" in identifiers
            improves = ["potentially lower formulation latency", "persistent natural presentation"]
            regresses = ["presentation/session ownership changes", "new lifecycle and correlation risk"]
        elif "packet_gap" in scenarios:
            whole = [value for value in ("UDP7082_AUTHORITATIVE_EOU",) if value in identifiers]
            reusable = [value for value in ("UDP7082_TRUE_FALSE_EOU", "CADENCE_AWARE_TX_LIVENESS") if value in mechanisms]
            duplicate = True
            potentially_superior = True
            regresses = ["loses authoritative physical PTT end", "reintroduces premature finalization"]
        elif "hard_language_modes" in scenarios:
            whole = [value for value in ("AUTOMATIC_INPUT_LANGUAGE_POLICY", "COMMUNICATION_PROFILE_INFRASTRUCTURE") if value in identifiers]
            duplicate = True
            regresses = ["re-conflates language and aviation procedure profile"]
        elif "whisper" in scenarios:
            whole = [value for value in ("SPEECHKIT_V3_EXTERNAL_EOU_STT",) if value in identifiers]
            duplicate = True
            regresses = ["restores removed dependency/worker footprint"]
        elif "protected_qwen" in scenarios:
            whole = [value for value in ("OSU_PROTECTED_PHRASEOLOGY",) if value in identifiers]
            duplicate = True
            regresses = ["transfers protected wording away from Core"]
        elif "rebuild_srs" in scenarios:
            whole = [value for value in ("UDP7082_AUTHORITATIVE_EOU", "SRS_CANDIDATE_BUFFERING_IMPLEMENTATION") if value in identifiers]
            duplicate = True
            potentially_superior = True
            regresses = ["duplicates field-proven transport and EOU ownership"]
        elif field_proven:
            whole = list(field_proven)

        disappeared = [
            {
                "implementation_id": item["implementation_id"],
                "reason": item.get("abandonment_reason", "UNKNOWN"),
            }
            for item in implementations
            if item.get("abandonment_reason", "UNKNOWN") != "UNKNOWN"
            or str(item.get("runtime_status", ""))
            in {"DISCONNECTED", "HISTORICAL_ONLY", "SUPERSEDED", "EXPLICITLY_REMOVED"}
        ]
        comparisons = [
            {
                "implementation_id": item["implementation_id"],
                "runtime_status": item.get("runtime_status"),
                "historical_status": item.get("historical_status"),
                "strengths": item.get("strengths", []),
                "defects": item.get("defects", []),
                "field_evidence": item["implementation_id"] in field_proven,
            }
            for item in implementations
        ]
        return {
            "previous_implementations_found": identifiers,
            "field_proven_previous_implementations": field_proven,
            "previous_best_whole_implementation": whole or None,
            "previous_best_mechanisms": reusable,
            "why_old_solution_disappeared": disappeared,
            "current_implementation": history["implementation_buckets"]["CURRENT"],
            "proposed_implementation": _safe_text(text.replace("_", " "), limit=1000),
            "duplicates_existing_work": duplicate,
            "previous_solution_potentially_superior": potentially_superior,
            "old_mechanism_reusable": bool(reusable),
            "hybrid_reuse_possible": hybrid,
            "what_improves": improves,
            "what_regresses": regresses,
            "qualitative_comparison": comparisons,
            "selection_order": ["RECONNECT", "ADAPT", "EXTEND", "REFACTOR", "REPLACE"],
        }

    def _performance(
        self, capabilities: Sequence[dict[str, Any]], scenarios: set[str]
    ) -> dict[str, Any]:
        capability_ids = [str(item["capability_id"]) for item in capabilities]
        if not capability_ids:
            metrics: list[dict[str, Any]] = []
        else:
            placeholders = ",".join("?" for _ in capability_ids)
            metrics = [
                _decoded(row)
                for row in self.connection.execute(
                    f"SELECT * FROM performance_metrics WHERE capability_id IN ({placeholders}) ORDER BY metric_id",
                    tuple(capability_ids),
                )
            ]
        return {
            "metrics": metrics,
            "metric_boundary_comparability": "PRESERVED",
            "boundary_comparability": (
                "PARTIAL_DIFFERENT_BOUNDARIES" if "natural_information" in scenarios else "NOT_OBSERVABLE"
            ),
            "performance_regression_risk": (
                "MAJOR" if "natural_information" in scenarios and metrics else "NOT_OBSERVABLE"
            ),
            "numeric_scores_invented": False,
        }

    @staticmethod
    def _evidence_reuse(
        scenarios: set[str], history: dict[str, Any], conflicts: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        evidence = [str(item["evidence_id"]) for item in history["evidence"]]
        blocked = any(item["severity"] == "BLOCK" for item in conflicts)
        new_invariant = (
            "Realtime text formulation plus current Core binding"
            if "natural_information" in scenarios
            else None
        )
        return {
            "what_existing_evidence_proves": evidence,
            "relevant_implementation_changed": False,
            "evidence_remains_valid": bool(evidence),
            "head_advancement_alone_invalidates_evidence": False,
            "existing_tests_reusable": True,
            "reuse_existing_field_evidence": bool(evidence),
            "new_test_required": bool(new_invariant) and not blocked,
            "new_field_test_required": bool(new_invariant) and not blocked,
            "new_invariant_requires_test": new_invariant,
        }

    def _primary_evidence(self, history: dict[str, Any]) -> list[dict[str, Any]]:
        nodes: list[tuple[str, str]] = []
        for bucket in history["decisions"].values():
            nodes.extend(("DECISION", str(item["decision_id"])) for item in bucket)
        nodes.extend(
            ("IMPLEMENTATION", str(item["implementation_id"]))
            for item in history["implementations"]
        )
        nodes.extend(
            ("MECHANISM", str(item["mechanism_id"])) for item in history["mechanisms"]
        )
        result: dict[tuple[str, str, str], dict[str, Any]] = {}
        for node_type, node_id in nodes:
            for row in self.connection.execute(
                """
                SELECT source_item_id, source_pointer_json, provenance_kind, confidence
                FROM graph_provenance
                WHERE node_type = ? AND node_id = ? AND source_item_id IS NOT NULL
                ORDER BY source_item_id
                """,
                (node_type, node_id),
            ):
                key = (node_type, node_id, str(row[0]))
                result[key] = {
                    "node_type": node_type,
                    "node_id": node_id,
                    "source_item_id": row[0],
                    "source_pointer": json.loads(row[1]),
                    "provenance_kind": row[2],
                    "confidence": row[3],
                }
        return list(result.values())[:160]

    def _index_signature(self) -> str:
        graph_signature = self.connection.execute(
            "SELECT value FROM graph_metadata WHERE key = 'AG2_INPUT_SIGNATURE'"
        ).fetchone()
        snapshot = self.connection.execute(
            """
            SELECT snapshot_id, manifest_sha256, indexed_at_utc
            FROM source_snapshots ORDER BY indexed_at_utc DESC, snapshot_id DESC LIMIT 1
            """
        ).fetchone()
        return canonical_sha256(
            {
                "graph": graph_signature[0] if graph_signature else "MISSING",
                "snapshot": dict(snapshot) if snapshot else None,
                "ruleset": AG3_RULESET_VERSION,
            }
        )

    def _ensure_performance_metrics(self) -> None:
        for seed in PERFORMANCE_SEEDS:
            source_item_id = seed.get("preferred_source_item")
            if source_item_id is not None:
                exists = self.connection.execute(
                    "SELECT 1 FROM source_items WHERE item_id = ?", (source_item_id,)
                ).fetchone()
                if exists is None:
                    source_item_id = None
            if source_item_id is None:
                row = self.connection.execute(
                    "SELECT source_item_id FROM evidence WHERE evidence_id = ?",
                    (seed["evidence"],),
                ).fetchone()
                source_item_id = row[0] if row else None
            self.connection.execute(
                """
                INSERT OR REPLACE INTO performance_metrics(
                    metric_id, name, capability_id, implementation_id,
                    metric_name, metric_value, unit, boundary, statistic,
                    sample_count, comparability, evidence_id, source_item_id,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed["id"],
                    seed["name"],
                    seed["capability"],
                    seed["implementation"],
                    seed["metric"],
                    seed["value"],
                    seed["unit"],
                    seed["boundary"],
                    seed["statistic"],
                    seed["sample_count"],
                    seed["comparability"],
                    seed["evidence"],
                    source_item_id,
                    _json({"ruleset": AG3_RULESET_VERSION}),
                ),
            )
        self.connection.commit()

    def _persist(
        self,
        result: dict[str, Any],
        request: PreflightInput,
        json_path: Path,
        human_path: Path,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO guard_runs(
                run_id, created_at_utc, mode_requested, mode_effective,
                task_hash, head_sha, ruleset_version, index_signature,
                logical_signature, gate, input_json, output_json,
                human_report_path, json_report_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["report_id"],
                result["generated_at_utc"],
                result["mode_requested"],
                result["mode_effective"],
                canonical_sha256(asdict(request)),
                result["head_sha"],
                result["ruleset_version"],
                result["index_signature"],
                result["logical_signature"],
                result["gate"],
                _json(asdict(request)),
                _json(result),
                str(human_path),
                str(json_path),
            ),
        )
        for conflict in result["conflicts"]:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO guard_conflicts(
                    conflict_id, run_id, conflict_type, severity, description,
                    decision_ids_json, implementation_ids_json, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{result['report_id']}:{conflict['conflict_id']}",
                    result["report_id"],
                    conflict["type"],
                    conflict["severity"],
                    conflict["message"],
                    _json(conflict["decision_ids"]),
                    _json(conflict["implementation_ids"]),
                    _json({"primary_evidence_in_report": True}),
                ),
            )
        self.connection.commit()


def _ids(items: Iterable[dict[str, Any]], key: str) -> str:
    values = [str(item[key]) for item in items]
    return ", ".join(values) if values else "NONE"


def render_human_report(result: dict[str, Any]) -> str:
    decisions = result["decisions"]
    previous = result["previous_best"]
    coverage = result["history_coverage"]
    lines = [
        "# ORION ARCHITECTURE GUARD",
        "",
        f"Report ID: `{result['report_id']}`  ",
        f"Mode: `{result['mode_requested']} → {result['mode_effective']}`  ",
        f"Task: {result['task']['task_title']}  ",
        f"HEAD: `{result['head_sha']}`",
        "",
        "## Affected capabilities",
        "",
        _ids(result["affected_capabilities"], "capability_id"),
        "",
        "## History coverage",
        "",
        f"Overall: `{coverage['overall']}`; architecture-critical missing: "
        f"`{len(coverage['architecture_critical_missing'])}`.",
        "",
        "## Current decisions",
        "",
        _ids(decisions["CURRENT"], "decision_id"),
        "",
        "## Superseded decisions",
        "",
        _ids(decisions["SUPERSEDED"], "decision_id"),
        "",
        "## Rejected decisions",
        "",
        _ids(decisions["REJECTED"], "decision_id"),
        "",
        "## Previous implementations",
        "",
        ", ".join(previous["previous_implementations_found"]) or "NONE",
        "",
        "## Field-proven previous implementations",
        "",
        ", ".join(previous["field_proven_previous_implementations"]) or "NONE",
        "",
        "## Previous best whole implementation",
        "",
        ", ".join(previous["previous_best_whole_implementation"] or []) or "NO SINGLE EVIDENCE-BACKED WINNER",
        "",
        "## Previous best mechanisms",
        "",
        ", ".join(previous["previous_best_mechanisms"]) or "NONE",
        "",
        "## Why old solution disappeared",
        "",
        _json(previous["why_old_solution_disappeared"]),
        "",
        "## Current / proposed implementation",
        "",
        f"Current: {', '.join(previous['current_implementation']) or 'NONE'}  ",
        f"Proposed: {result['task']['proposed_change'] or result['task']['task_description'] or result['task']['task_title']}",
        "",
        "## Duplicate-work risk",
        "",
        f"`{previous['duplicates_existing_work']}`",
        "",
        "## Ownership drift",
        "",
        _json(result["ownership_drift"]),
        "",
        "## Performance differential",
        "",
        f"Risk: `{result['performance']['performance_regression_risk']}`; "
        f"boundary comparability: `{result['performance']['boundary_comparability']}`.",
        "",
        "## Safety / UX differential",
        "",
        f"Improves: {_json(previous['what_improves'])}  ",
        f"Regresses: {_json(previous['what_regresses'])}",
        "",
        "## Hybrid reuse opportunities",
        "",
        f"Hybrid possible: `{previous['hybrid_reuse_possible']}`; mechanisms: "
        f"{', '.join(previous['previous_best_mechanisms']) or 'NONE'}.",
        "",
        "## Evidence reuse",
        "",
        f"Existing evidence reusable: `{result['evidence_reuse']['reuse_existing_field_evidence']}`.  ",
        f"New invariant requiring test: `{result['evidence_reuse']['new_invariant_requires_test']}`.",
        "",
        "## Conflicts",
        "",
        *(
            [f"- **{item['severity']}** `{item['type']}` — {item['message']}" for item in result["conflicts"]]
            or ["NONE"]
        ),
        "",
        "## ARCHITECTURE GATE",
        "",
        f"# {result['gate']}",
        "",
        f"User supersession required: `{result['requires_user_decision']}`",
        "",
        "## Primary provenance pointers",
        "",
        *[
            f"- `{item['node_type']}:{item['node_id']}` → `{item['source_item_id']}` — "
            f"`{_json(item['source_pointer'])}`"
            for item in result["primary_evidence"]
        ],
        "",
    ]
    return "\n".join(lines)
