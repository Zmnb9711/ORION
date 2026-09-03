from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_arch_guard.canonical_seed import (
    ALL_CANONICAL_RECORDS,
    CANONICAL_SEED_VERSION,
    CanonicalKind,
    WorkClassification,
)
from tools.orion_arch_guard.graph_seed import (
    AG2_SEED_VERSION,
    AREA_CAPABILITIES,
    CAPABILITY_DETAILS,
    CAPABILITY_PARENTS,
    DECISION_CAPABILITY_OVERRIDES,
    EVIDENCE_SEEDS,
    EXTRA_RELATIONSHIPS,
    FAMILY_CAPABILITIES,
    IMPLEMENTATION_SEEDS,
    MECHANISM_SEEDS,
    OWNERSHIP_SEEDS,
)
from tools.orion_arch_guard.schema import connect_index, migrate

_DECISION_ID = re.compile(r"D\d{2}")
_COMMIT = re.compile(r"[0-9a-fA-F]{7,40}")
_GRAPH_TABLES = (
    "canonical_record_capabilities",
    "canonical_records",
    "relationships",
    "graph_provenance",
    "ownership_assignments",
    "capability_aliases",
    "evidence",
    "mechanisms",
    "implementations",
    "decisions",
    "capabilities",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9а-яё]+", "_", normalized).strip("_")


def _node_id(kind: str, value: str) -> tuple[str, str]:
    return kind.upper(), value.upper()


@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    database_path: str
    duration_seconds: float
    reused: bool
    capabilities: int
    decisions: int
    implementations: int
    mechanisms: int
    evidence: int
    relationships: int
    ownership_assignments: int
    provenance_links: int
    canonical_records: int
    input_signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    item_id: str
    content_sha256: str
    pointer: dict[str, Any]
    timestamp_utc: str | None


class GraphBuildError(RuntimeError):
    pass


class GraphBuilder:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.connection = connect_index(database_path)
        migrate(self.connection)
        self._ref_cache: dict[str, _ResolvedSource] = {}
        self._evidence_item_by_id = {
            str(seed["id"]): str(seed["item"]) for seed in EVIDENCE_SEEDS
        }

    def close(self) -> None:
        self.connection.close()

    def _row_source(self, row: sqlite3.Row | None, ref: str) -> _ResolvedSource:
        if row is None:
            raise GraphBuildError(f"required AG-1 source item is missing: {ref}")
        return _ResolvedSource(
            item_id=str(row["item_id"]),
            content_sha256=str(row["content_sha256"]),
            pointer=json.loads(str(row["source_pointer_json"])),
            timestamp_utc=row["timestamp_utc"],
        )

    def resolve_ref(self, ref: str) -> _ResolvedSource:
        cached = self._ref_cache.get(ref)
        if cached is not None:
            return cached
        if _DECISION_ID.fullmatch(ref):
            row = self.connection.execute(
                """
                SELECT source_items.* FROM source_items
                JOIN sources ON sources.source_id = source_items.source_id
                WHERE source_items.item_type = 'decision_register_row'
                  AND source_items.native_id = ?
                ORDER BY sources.availability = 'AVAILABLE' DESC,
                         source_items.timestamp_utc DESC
                LIMIT 1
                """,
                (ref,),
            ).fetchone()
        elif ref.startswith("evidence:"):
            row = self.connection.execute(
                "SELECT * FROM source_items WHERE item_id = ? AND item_type = 'evidence_archive'",
                (ref,),
            ).fetchone()
        elif _COMMIT.fullmatch(ref):
            rows = self.connection.execute(
                """
                SELECT * FROM source_items
                WHERE item_type = 'git_commit' AND native_id LIKE ?
                ORDER BY native_id
                """,
                (ref.casefold() + "%",),
            ).fetchall()
            if len(rows) != 1:
                raise GraphBuildError(
                    f"Git ref {ref} resolved to {len(rows)} commits; expected one"
                )
            row = rows[0]
        else:
            evidence_item = self._evidence_item_by_id.get(ref)
            if evidence_item is None:
                raise GraphBuildError(f"unsupported provenance reference: {ref}")
            row = self.connection.execute(
                "SELECT * FROM source_items WHERE item_id = ? AND item_type = 'evidence_archive'",
                (evidence_item,),
            ).fetchone()
        resolved = self._row_source(row, ref)
        self._ref_cache[ref] = resolved
        return resolved

    def _all_required_refs(self) -> list[str]:
        refs: set[str] = {f"D{number:02d}" for number in range(1, 75)}
        for seed in IMPLEMENTATION_SEEDS:
            refs.update(str(value) for value in seed.get("commits", []))
            refs.update(str(value) for value in seed.get("decisions", []))
            refs.update(str(value) for value in seed.get("evidence", []))
        for seed in MECHANISM_SEEDS:
            refs.update(str(value) for value in seed.get("refs", []))
        for seed in EXTRA_RELATIONSHIPS:
            refs.update(str(value) for value in seed.get("refs", []))
        for seed in OWNERSHIP_SEEDS:
            refs.update(str(value) for value in seed.get("refs", []))
        refs.update(str(seed["id"]) for seed in EVIDENCE_SEEDS)
        return sorted(refs)

    def _signature(self) -> str:
        resolved = {
            ref: self.resolve_ref(ref).content_sha256
            for ref in self._all_required_refs()
        }
        return canonical_sha256(
            {
                "ag2_seed_version": AG2_SEED_VERSION,
                "canonical_seed_version": CANONICAL_SEED_VERSION,
                "seed_payload": {
                    "families": FAMILY_CAPABILITIES,
                    "details": CAPABILITY_DETAILS,
                    "parents": CAPABILITY_PARENTS,
                    "area_capabilities": AREA_CAPABILITIES,
                    "decision_overrides": DECISION_CAPABILITY_OVERRIDES,
                    "implementations": IMPLEMENTATION_SEEDS,
                    "mechanisms": MECHANISM_SEEDS,
                    "evidence": EVIDENCE_SEEDS,
                    "relationships": EXTRA_RELATIONSHIPS,
                    "ownership": OWNERSHIP_SEEDS,
                    "canonical": [record.to_dict() for record in ALL_CANONICAL_RECORDS],
                },
                "resolved_sources": resolved,
            }
        )

    def _counts(self) -> dict[str, int]:
        return {
            table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "capabilities",
                "decisions",
                "implementations",
                "mechanisms",
                "evidence",
                "relationships",
                "ownership_assignments",
                "graph_provenance",
                "canonical_records",
            )
        }

    def _result(
        self, started: float, signature: str, *, reused: bool
    ) -> GraphBuildResult:
        counts = self._counts()
        return GraphBuildResult(
            database_path=str(self.database_path.absolute()),
            duration_seconds=time.perf_counter() - started,
            reused=reused,
            capabilities=counts["capabilities"],
            decisions=counts["decisions"],
            implementations=counts["implementations"],
            mechanisms=counts["mechanisms"],
            evidence=counts["evidence"],
            relationships=counts["relationships"],
            ownership_assignments=counts["ownership_assignments"],
            provenance_links=counts["graph_provenance"],
            canonical_records=counts["canonical_records"],
            input_signature=signature,
        )

    def build(self, *, force: bool = False) -> GraphBuildResult:
        started = time.perf_counter()
        self._ref_cache.clear()
        self._validate_seed()
        signature = self._signature()
        existing = self.connection.execute(
            "SELECT value FROM graph_metadata WHERE key = 'AG2_INPUT_SIGNATURE'"
        ).fetchone()
        if not force and existing and existing[0] == signature:
            return self._result(started, signature, reused=True)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for table in _GRAPH_TABLES:
                self.connection.execute(f"DELETE FROM {table}")
            self._insert_capabilities()
            decisions = self._insert_decisions()
            self._insert_evidence()
            self._insert_implementations()
            self._insert_mechanisms()
            self._insert_automatic_relationships(decisions)
            self._insert_extra_relationships()
            self._insert_ownership()
            self._insert_canonical_records(signature)
            self._validate_graph()
            self.connection.execute(
                "INSERT OR REPLACE INTO graph_metadata(key, value) VALUES ('AG2_SEED_VERSION', ?)",
                (AG2_SEED_VERSION,),
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO graph_metadata(key, value) VALUES ('AG2_INPUT_SIGNATURE', ?)",
                (signature,),
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO graph_metadata(key, value) VALUES ('CANONICAL_SEED_VERSION', ?)",
                (CANONICAL_SEED_VERSION,),
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO graph_metadata(key, value) VALUES ('CANONICAL_INPUT_SIGNATURE', ?)",
                (signature,),
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return self._result(started, signature, reused=False)

    def _validate_seed(self) -> None:
        capabilities = {
            capability
            for values in FAMILY_CAPABILITIES.values()
            for capability in values
        }
        if len(capabilities) != sum(len(values) for values in FAMILY_CAPABILITIES.values()):
            raise GraphBuildError("capability IDs must be globally unique")
        referenced: set[str] = set()
        for parent, child in CAPABILITY_PARENTS:
            referenced.update((parent, child))
        for values in AREA_CAPABILITIES.values():
            referenced.update(values)
        for values in DECISION_CAPABILITY_OVERRIDES.values():
            referenced.update(values)
        for seed in IMPLEMENTATION_SEEDS:
            referenced.update(str(value) for value in seed["capabilities"])
        for seed in MECHANISM_SEEDS:
            referenced.update(str(value) for value in seed["capabilities"])
        missing = referenced - capabilities
        if missing:
            raise GraphBuildError(f"unknown capability IDs in AG-2 seed: {sorted(missing)}")
        implementation_ids = {str(seed["id"]) for seed in IMPLEMENTATION_SEEDS}
        mechanism_ids = {str(seed["id"]) for seed in MECHANISM_SEEDS}
        evidence_ids = {str(seed["id"]) for seed in EVIDENCE_SEEDS}
        canonical_ids = {record.record_id for record in ALL_CANONICAL_RECORDS}
        if len(implementation_ids) != len(IMPLEMENTATION_SEEDS):
            raise GraphBuildError("implementation IDs must be unique")
        if len(mechanism_ids) != len(MECHANISM_SEEDS):
            raise GraphBuildError("mechanism IDs must be unique")
        if len(canonical_ids) != len(ALL_CANONICAL_RECORDS):
            raise GraphBuildError("canonical record IDs must be unique")
        unknown_canonical = {
            capability
            for record in ALL_CANONICAL_RECORDS
            for capability in record.capabilities
            if capability not in capabilities
        }
        if unknown_canonical:
            raise GraphBuildError(
                f"unknown capability IDs in canonical seed: {sorted(unknown_canonical)}"
            )
        for seed in IMPLEMENTATION_SEEDS:
            unknown = set(str(value) for value in seed.get("mechanisms", [])) - mechanism_ids
            if unknown:
                raise GraphBuildError(f"unknown mechanisms for {seed['id']}: {sorted(unknown)}")
            unknown_evidence = set(str(value) for value in seed.get("evidence", [])) - evidence_ids
            if unknown_evidence:
                raise GraphBuildError(
                    f"unknown evidence for {seed['id']}: {sorted(unknown_evidence)}"
                )

    def _insert_capabilities(self) -> None:
        for family, capability_ids in FAMILY_CAPABILITIES.items():
            for capability_id in capability_ids:
                details = CAPABILITY_DETAILS.get(capability_id, {})
                name = str(details.get("name") or capability_id.replace("_", " ").title())
                aliases = [str(value) for value in details.get("aliases", [])]
                historical_terms = [
                    str(value) for value in details.get("historical_terms", [])
                ]
                code_symbols = [str(value) for value in details.get("code_symbols", [])]
                providers = [str(value) for value in details.get("providers", [])]
                related_domains = [
                    str(value) for value in details.get("related_domains", [])
                ]
                self.connection.execute(
                    """
                    INSERT INTO capabilities(
                        capability_id, family, name, description, aliases_json,
                        historical_terms_json, code_symbols_json, providers_json,
                        related_domains_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capability_id,
                        family,
                        name,
                        str(details.get("description") or "Stable AG-2 capability taxonomy node."),
                        _json(aliases),
                        _json(historical_terms),
                        _json(code_symbols),
                        _json(providers),
                        _json(related_domains),
                        _json({"seed_version": AG2_SEED_VERSION, "provenance_kind": "DERIVED_TAXONOMY"}),
                    ),
                )
                alias_values = [(capability_id, "STABLE_ID"), (name, "NAME")]
                alias_values.extend((value, "ALIAS") for value in aliases)
                alias_values.extend(
                    (value, "HISTORICAL_TERM") for value in historical_terms
                )
                alias_values.extend((value, "CODE_SYMBOL") for value in code_symbols)
                for alias, alias_type in alias_values:
                    key = normalize_alias(alias)
                    existing = self.connection.execute(
                        "SELECT capability_id FROM capability_aliases WHERE alias_key = ?",
                        (key,),
                    ).fetchone()
                    if existing and existing[0] != capability_id:
                        raise GraphBuildError(
                            f"capability alias collision: {alias!r} maps to {existing[0]} and {capability_id}"
                        )
                    self.connection.execute(
                        "INSERT OR REPLACE INTO capability_aliases(alias_key, capability_id, alias, alias_type) VALUES (?, ?, ?, ?)",
                        (key, capability_id, alias, alias_type),
                    )
                self._insert_provenance(
                    "CAPABILITY",
                    capability_id,
                    [],
                    provenance_kind="DERIVED_TAXONOMY",
                    confidence="CURATED",
                )

    def _parse_decision(self, decision_id: str) -> tuple[list[str], _ResolvedSource]:
        resolved = self.resolve_ref(decision_id)
        path = Path(str(resolved.pointer["path"]))
        line_number = int(resolved.pointer["line_start"])
        line = path.read_text(encoding="utf-8").splitlines()[line_number - 1]
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 12 or cells[0] != decision_id:
            raise GraphBuildError(
                f"Decision {decision_id} source line has {len(cells)} fields; expected 12"
            )
        return cells, resolved

    def _insert_decisions(self) -> dict[str, list[str]]:
        results: dict[str, list[str]] = {}
        for number in range(1, 75):
            decision_id = f"D{number:02d}"
            cells, resolved = self._parse_decision(decision_id)
            superseded = [
                value
                for value in re.findall(r"D\d{2}", cells[9])
                if value != decision_id
            ]
            capabilities = list(
                DECISION_CAPABILITY_OVERRIDES.get(
                    decision_id, AREA_CAPABILITIES.get(cells[2], ("PRODUCT_SCOPE",))
                )
            )
            results[decision_id] = capabilities
            self.connection.execute(
                """
                INSERT INTO decisions(
                    decision_id, decision_date, area, decision_text, proposed_by,
                    user_approval, historical_implementation, current_implementation,
                    decision_status, superseded_by_json, evidence_summary,
                    confidence, source_item_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    cells[1],
                    cells[2],
                    cells[3],
                    cells[4],
                    cells[5],
                    cells[6],
                    cells[7],
                    cells[8],
                    _json(superseded),
                    cells[10],
                    cells[11],
                    resolved.item_id,
                    _json({"exact_register_row": True, "capabilities": capabilities}),
                ),
            )
            self._insert_provenance(
                "DECISION",
                decision_id,
                [resolved],
                provenance_kind="EXACT_L0",
                confidence=cells[11],
            )
        return results

    def _insert_evidence(self) -> None:
        for seed in EVIDENCE_SEEDS:
            resolved = self.resolve_ref(str(seed["id"]))
            self.connection.execute(
                """
                INSERT INTO evidence(
                    evidence_id, name, evidence_type, evidence_status,
                    source_item_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    seed["id"],
                    seed["name"],
                    "FIELD",
                    seed["status"],
                    resolved.item_id,
                    _json({"source_item_id": resolved.item_id}),
                ),
            )
            self._insert_provenance(
                "EVIDENCE",
                str(seed["id"]),
                [resolved],
                provenance_kind="EXACT_L0",
                confidence=str(seed["confidence"]),
            )

    def _resolved_for_implementation(
        self, seed: dict[str, Any]
    ) -> list[_ResolvedSource]:
        refs = [
            *(str(value) for value in seed.get("commits", [])),
            *(str(value) for value in seed.get("decisions", [])),
            *(str(value) for value in seed.get("evidence", [])),
        ]
        return self._dedup_sources(self.resolve_ref(ref) for ref in refs)

    def _insert_implementations(self) -> None:
        for seed in IMPLEMENTATION_SEEDS:
            resolved = self._resolved_for_implementation(seed)
            commits = [
                source.item_id.removeprefix("git:commit:")
                for source in resolved
                if source.item_id.startswith("git:commit:")
            ]
            self.connection.execute(
                """
                INSERT INTO implementations(
                    implementation_id, name, provider, session_model,
                    runtime_status, historical_status, introduced_at,
                    commit_range_json, files_components_json, strengths_json,
                    defects_json, abandonment_reason, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed["id"],
                    seed["name"],
                    seed.get("provider"),
                    seed.get("session_model"),
                    seed["runtime_status"],
                    seed["historical_status"],
                    seed.get("introduced_at"),
                    _json(commits),
                    _json(seed.get("files", [])),
                    _json(seed.get("strengths", [])),
                    _json(seed.get("defects", [])),
                    seed.get("abandonment_reason", "UNKNOWN"),
                    _json(
                        {
                            **dict(seed.get("metadata", {})),
                            "capabilities": seed["capabilities"],
                            "mechanisms": seed.get("mechanisms", []),
                            "evidence": seed.get("evidence", []),
                        }
                    ),
                ),
            )
            self._insert_provenance(
                "IMPLEMENTATION",
                str(seed["id"]),
                resolved,
                provenance_kind="CURATED_PRIMARY_MAPPING",
                confidence="VERY_HIGH",
            )

    def _insert_mechanisms(self) -> None:
        for seed in MECHANISM_SEEDS:
            resolved = self._dedup_sources(
                self.resolve_ref(str(ref)) for ref in seed["refs"]
            )
            self.connection.execute(
                """
                INSERT INTO mechanisms(
                    mechanism_id, name, description, invariant_text,
                    current_presence, historical_status, field_probe_status,
                    strengths_json, defects_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed["id"],
                    str(seed["id"]).replace("_", " ").title(),
                    seed["description"],
                    seed["invariant"],
                    int(bool(seed["current"])),
                    seed["status"],
                    seed["status"],
                    _json(seed.get("strengths", [seed["invariant"]])),
                    _json(seed.get("defects", [])),
                    _json({"capabilities": seed["capabilities"], "introduced_by_refs": seed["refs"]}),
                ),
            )
            self._insert_provenance(
                "MECHANISM",
                str(seed["id"]),
                resolved,
                provenance_kind="CURATED_PRIMARY_MAPPING",
                confidence="VERY_HIGH",
            )

    def _insert_automatic_relationships(
        self, decisions: dict[str, list[str]]
    ) -> None:
        for parent, child in CAPABILITY_PARENTS:
            self._insert_relationship(
                "CAPABILITY",
                parent,
                "PARENT_OF",
                "CAPABILITY",
                child,
                [],
                confidence="CURATED",
                metadata={"provenance_kind": "DERIVED_TAXONOMY"},
            )
        for decision_id, capabilities in decisions.items():
            refs = [self.resolve_ref(decision_id)]
            for capability in capabilities:
                self._insert_relationship(
                    "DECISION",
                    decision_id,
                    "APPLIES_TO_CAPABILITY",
                    "CAPABILITY",
                    capability,
                    refs,
                    confidence="VERY_HIGH",
                )
            superseded = json.loads(
                self.connection.execute(
                    "SELECT superseded_by_json FROM decisions WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()[0]
            )
            for newer in superseded:
                self._insert_relationship(
                    "DECISION",
                    newer,
                    "SUPERSEDES",
                    "DECISION",
                    decision_id,
                    [self.resolve_ref(decision_id), self.resolve_ref(newer)],
                    confidence="VERY_HIGH",
                )
        for seed in IMPLEMENTATION_SEEDS:
            refs = self._resolved_for_implementation(seed)
            implementation_id = str(seed["id"])
            for capability in seed["capabilities"]:
                self._insert_relationship(
                    "IMPLEMENTATION",
                    implementation_id,
                    "IMPLEMENTS",
                    "CAPABILITY",
                    str(capability),
                    refs,
                    confidence="VERY_HIGH",
                )
            for mechanism in seed.get("mechanisms", []):
                self._insert_relationship(
                    "IMPLEMENTATION",
                    implementation_id,
                    "REUSES_MECHANISM",
                    "MECHANISM",
                    str(mechanism),
                    refs,
                    confidence="VERY_HIGH",
                )
            for evidence_id in seed.get("evidence", []):
                self._insert_relationship(
                    "IMPLEMENTATION",
                    implementation_id,
                    "FIELD_PROVEN_BY",
                    "EVIDENCE",
                    str(evidence_id),
                    [self.resolve_ref(str(evidence_id))],
                    confidence="VERY_HIGH",
                )
        for seed in MECHANISM_SEEDS:
            refs = self._dedup_sources(
                self.resolve_ref(str(ref)) for ref in seed["refs"]
            )
            for capability in seed["capabilities"]:
                self._insert_relationship(
                    "MECHANISM",
                    str(seed["id"]),
                    "APPLIES_TO",
                    "CAPABILITY",
                    str(capability),
                    refs,
                    confidence="VERY_HIGH",
                )

    def _insert_extra_relationships(self) -> None:
        for seed in EXTRA_RELATIONSHIPS:
            source_type, source_id = seed["source"]
            target_type, target_id = seed["target"]
            refs = self._dedup_sources(
                self.resolve_ref(str(ref)) for ref in seed["refs"]
            )
            self._insert_relationship(
                str(source_type),
                str(source_id),
                str(seed["type"]),
                str(target_type),
                str(target_id),
                refs,
                confidence=str(seed["confidence"]),
                metadata=dict(seed.get("metadata", {})),
            )

    def _insert_ownership(self) -> None:
        for seed in OWNERSHIP_SEEDS:
            owner_type, owner_id = seed["owner"]
            resolved = self._dedup_sources(
                self.resolve_ref(str(ref)) for ref in seed["refs"]
            )
            assignment_id = "ownership:" + canonical_sha256(
                [seed["role"], owner_type, owner_id, seed["capability"], seed["status"]]
            )[:24].casefold()
            self.connection.execute(
                """
                INSERT INTO ownership_assignments(
                    assignment_id, ownership_role, owner_node_type, owner_node_id,
                    capability_id, historical_status, confidence, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment_id,
                    seed["role"],
                    owner_type,
                    owner_id,
                    seed["capability"],
                    seed["status"],
                    "VERY_HIGH",
                    self._provenance_payload(resolved),
                ),
            )

    def _insert_relationship(
        self,
        source_type: str,
        source_id: str,
        relationship_type: str,
        target_type: str,
        target_id: str,
        sources: Sequence[_ResolvedSource],
        *,
        confidence: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        relationship_id = "relationship:" + canonical_sha256(
            [source_type, source_id, relationship_type, target_type, target_id]
        )[:24].casefold()
        provenance = (
            self._provenance_payload(sources)
            if sources
            else _json({"kind": "DERIVED_TAXONOMY", "seed_version": AG2_SEED_VERSION})
        )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO relationships(
                relationship_id, source_node_type, source_node_id,
                relationship_type, target_node_type, target_node_id,
                confidence, provenance_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relationship_id,
                source_type,
                source_id,
                relationship_type,
                target_type,
                target_id,
                confidence,
                provenance,
                _json(metadata or {}),
            ),
        )

    def _insert_provenance(
        self,
        node_type: str,
        node_id: str,
        sources: Sequence[_ResolvedSource],
        *,
        provenance_kind: str,
        confidence: str,
    ) -> None:
        if not sources:
            provenance_id = "provenance:" + canonical_sha256(
                [node_type, node_id, provenance_kind]
            )[:24].casefold()
            self.connection.execute(
                """
                INSERT INTO graph_provenance(
                    provenance_id, node_type, node_id, source_item_id,
                    source_pointer_json, provenance_kind, confidence,
                    context_item_ids_json
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    provenance_id,
                    node_type,
                    node_id,
                    _json({"derived_seed": "AG-2", "seed_version": AG2_SEED_VERSION}),
                    provenance_kind,
                    confidence,
                    _json([]),
                ),
            )
            return
        context = [source.item_id for source in sources]
        for source in sources:
            provenance_id = "provenance:" + canonical_sha256(
                [node_type, node_id, source.item_id, provenance_kind]
            )[:24].casefold()
            self.connection.execute(
                """
                INSERT INTO graph_provenance(
                    provenance_id, node_type, node_id, source_item_id,
                    source_pointer_json, provenance_kind, confidence,
                    context_item_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provenance_id,
                    node_type,
                    node_id,
                    source.item_id,
                    _json(source.pointer),
                    provenance_kind,
                    confidence,
                    _json(context),
                ),
            )

    @staticmethod
    def _dedup_sources(
        sources: Iterable[_ResolvedSource],
    ) -> list[_ResolvedSource]:
        result: dict[str, _ResolvedSource] = {}
        for source in sources:
            result[source.item_id] = source
        return list(result.values())

    @staticmethod
    def _provenance_payload(sources: Sequence[_ResolvedSource]) -> str:
        return _json(
            {
                "source_item_ids": [source.item_id for source in sources],
                "source_pointers": [source.pointer for source in sources],
            }
        )

    def _insert_canonical_records(self, input_signature: str) -> None:
        decision = self.resolve_ref("D74")
        for record in ALL_CANONICAL_RECORDS:
            value = record.to_dict()
            self.connection.execute(
                """
                INSERT INTO canonical_records(
                    record_id, record_kind, title, status, classification,
                    summary, proof_level, recommended_action, priority,
                    user_decision_required, user_valued, capabilities_json,
                    source_refs_json, evidence_refs_json, metadata_json,
                    input_signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.kind.value,
                    record.title,
                    record.status,
                    record.classification,
                    record.summary,
                    record.proof_level,
                    record.recommended_action,
                    record.priority,
                    int(record.user_decision_required),
                    int(record.user_valued),
                    _json(record.capabilities),
                    _json(record.source_refs),
                    _json(record.evidence_refs),
                    _json(record.metadata),
                    input_signature,
                ),
            )
            for capability in record.capabilities:
                self.connection.execute(
                    "INSERT INTO canonical_record_capabilities(record_id, capability_id) VALUES (?, ?)",
                    (record.record_id, capability),
                )
                self._insert_relationship(
                    "CANONICAL_RECORD",
                    record.record_id,
                    "GOVERNS" if record.kind is CanonicalKind.DO_NOT_REINVENT else "APPLIES_TO",
                    "CAPABILITY",
                    capability,
                    [decision],
                    confidence="VERY_HIGH",
                    metadata={"canonical_kind": record.kind.value},
                )
            self._insert_provenance(
                node_type="CANONICAL_RECORD",
                node_id=record.record_id,
                sources=[decision],
                provenance_kind="D74_CANONICALIZATION",
                confidence="VERY_HIGH",
            )

    def _validate_graph(self) -> None:
        counts = self._counts()
        if counts["decisions"] != 74:
            raise GraphBuildError(f"expected 74 decisions, found {counts['decisions']}")
        if counts["canonical_records"] != len(ALL_CANONICAL_RECORDS):
            raise GraphBuildError(
                f"expected {len(ALL_CANONICAL_RECORDS)} canonical records, "
                f"found {counts['canonical_records']}"
            )
        hard_nodes = {
            "DECISION": "decisions",
            "IMPLEMENTATION": "implementations",
            "MECHANISM": "mechanisms",
            "EVIDENCE": "evidence",
        }
        for node_type, table in hard_nodes.items():
            id_column = {
                "DECISION": "decision_id",
                "IMPLEMENTATION": "implementation_id",
                "MECHANISM": "mechanism_id",
                "EVIDENCE": "evidence_id",
            }[node_type]
            orphan = self.connection.execute(
                f"""
                SELECT COUNT(*) FROM {table} node
                WHERE NOT EXISTS (
                    SELECT 1 FROM graph_provenance provenance
                    WHERE provenance.node_type = ?
                      AND provenance.node_id = node.{id_column}
                      AND provenance.source_item_id IS NOT NULL
                )
                """,
                (node_type,),
            ).fetchone()[0]
            if orphan:
                raise GraphBuildError(f"{orphan} hard {node_type} nodes lack exact provenance")
        invalid_relationships = self.connection.execute(
            """
            SELECT COUNT(*) FROM relationships
            WHERE confidence IN ('', 'UNKNOWN') OR provenance_json IN ('', '{}')
            """
        ).fetchone()[0]
        if invalid_relationships:
            raise GraphBuildError(
                f"{invalid_relationships} relationships lack confidence/provenance"
            )


class CapabilityGraph:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.connection = connect_index(database_path)
        migrate(self.connection)

    def close(self) -> None:
        self.connection.close()

    def resolve_capability(self, value: str) -> str | None:
        row = self.connection.execute(
            "SELECT capability_id FROM capability_aliases WHERE alias_key = ?",
            (normalize_alias(value),),
        ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _decoded(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in list(result):
            if key.endswith("_json") and result[key]:
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
        return result

    def _provenance(self, node_type: str, node_id: str) -> list[dict[str, Any]]:
        return [
            self._decoded(row)
            for row in self.connection.execute(
                "SELECT * FROM graph_provenance WHERE node_type = ? AND node_id = ? ORDER BY source_item_id",
                (node_type, node_id),
            )
        ]

    def capability(self, value: str) -> dict[str, Any] | None:
        capability_id = self.resolve_capability(value)
        if capability_id is None:
            return None
        row = self.connection.execute(
            "SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,)
        ).fetchone()
        if row is None:
            return None
        result = self._decoded(row)
        result["parents"] = [
            item[0]
            for item in self.connection.execute(
                """
                SELECT source_node_id FROM relationships
                WHERE relationship_type = 'PARENT_OF'
                  AND target_node_type = 'CAPABILITY' AND target_node_id = ?
                ORDER BY source_node_id
                """,
                (capability_id,),
            )
        ]
        result["children"] = [
            item[0]
            for item in self.connection.execute(
                """
                SELECT target_node_id FROM relationships
                WHERE relationship_type = 'PARENT_OF'
                  AND source_node_type = 'CAPABILITY' AND source_node_id = ?
                ORDER BY target_node_id
                """,
                (capability_id,),
            )
        ]
        return result

    def related(self, value: str) -> dict[str, Any] | None:
        capability = self.capability(value)
        if capability is None:
            return None
        capability_id = str(capability["capability_id"])
        relationships = [
            self._decoded(row)
            for row in self.connection.execute(
                """
                SELECT * FROM relationships
                WHERE (target_node_type = 'CAPABILITY' AND target_node_id = ?)
                   OR (source_node_type = 'CAPABILITY' AND source_node_id = ?)
                ORDER BY source_node_type, source_node_id, relationship_type
                """,
                (capability_id, capability_id),
            )
        ]
        decision_ids = sorted(
            relationship["source_node_id"]
            for relationship in relationships
            if relationship["source_node_type"] == "DECISION"
        )
        implementation_ids = sorted(
            relationship["source_node_id"]
            for relationship in relationships
            if relationship["source_node_type"] == "IMPLEMENTATION"
        )
        mechanism_ids = {
            relationship["source_node_id"]
            for relationship in relationships
            if relationship["source_node_type"] == "MECHANISM"
        }
        for implementation_id in implementation_ids:
            mechanism_ids.update(
                str(row[0])
                for row in self.connection.execute(
                    """
                    SELECT target_node_id FROM relationships
                    WHERE source_node_type = 'IMPLEMENTATION'
                      AND source_node_id = ?
                      AND relationship_type = 'REUSES_MECHANISM'
                      AND target_node_type = 'MECHANISM'
                    """,
                    (implementation_id,),
                )
            )
        decisions = self._select_nodes("decisions", "decision_id", decision_ids)
        implementations = self._select_nodes(
            "implementations", "implementation_id", implementation_ids
        )
        mechanisms = self._select_nodes(
            "mechanisms", "mechanism_id", sorted(mechanism_ids)
        )
        evidence_ids: set[str] = set()
        for implementation_id in implementation_ids:
            evidence_ids.update(
                str(row[0])
                for row in self.connection.execute(
                    """
                    SELECT target_node_id FROM relationships
                    WHERE source_node_type = 'IMPLEMENTATION'
                      AND source_node_id = ?
                      AND relationship_type = 'FIELD_PROVEN_BY'
                      AND target_node_type = 'EVIDENCE'
                    """,
                    (implementation_id,),
                )
            )
        evidence = self._select_nodes("evidence", "evidence_id", sorted(evidence_ids))
        selected_nodes = {
            ("CAPABILITY", capability_id),
            *(("DECISION", node_id) for node_id in decision_ids),
            *(("IMPLEMENTATION", node_id) for node_id in implementation_ids),
            *(("MECHANISM", node_id) for node_id in mechanism_ids),
            *(("EVIDENCE", node_id) for node_id in evidence_ids),
        }
        relationships = [
            self._decoded(row)
            for row in self.connection.execute(
                """
                SELECT * FROM relationships
                ORDER BY source_node_type, source_node_id, relationship_type,
                         target_node_type, target_node_id
                """
            )
            if (str(row[1]), str(row[2])) in selected_nodes
            and (str(row[4]), str(row[5])) in selected_nodes
        ]
        ownership = [
            self._decoded(row)
            for row in self.connection.execute(
                "SELECT * FROM ownership_assignments WHERE capability_id = ? ORDER BY ownership_role",
                (capability_id,),
            )
        ]
        for node_type, nodes, id_column in (
            ("DECISION", decisions, "decision_id"),
            ("IMPLEMENTATION", implementations, "implementation_id"),
            ("MECHANISM", mechanisms, "mechanism_id"),
            ("EVIDENCE", evidence, "evidence_id"),
        ):
            for node in nodes:
                node["provenance"] = self._provenance(node_type, str(node[id_column]))
        return {
            "capability": capability,
            "decisions": decisions,
            "implementations": implementations,
            "mechanisms": mechanisms,
            "evidence": evidence,
            "ownership": ownership,
            "relationships": relationships,
            "architecture_gate_result": None,
        }

    def history(self, value: str) -> dict[str, Any] | None:
        result = self.related(value)
        if result is None:
            return None
        result["implementations"] = sorted(
            result["implementations"],
            key=lambda item: (item.get("introduced_at") or "", item["implementation_id"]),
        )
        return result

    def explain_implementation(self, implementation_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM implementations WHERE implementation_id = ?",
            (implementation_id.upper(),),
        ).fetchone()
        if row is None:
            return None
        relationships = [
            self._decoded(item)
            for item in self.connection.execute(
                """
                SELECT * FROM relationships
                WHERE (source_node_type = 'IMPLEMENTATION' AND source_node_id = ?)
                   OR (target_node_type = 'IMPLEMENTATION' AND target_node_id = ?)
                ORDER BY relationship_type, source_node_id, target_node_id
                """,
                (implementation_id.upper(), implementation_id.upper()),
            )
        ]
        return {
            "implementation": self._decoded(row),
            "relationships": relationships,
            "provenance": self._provenance("IMPLEMENTATION", implementation_id.upper()),
            "architecture_gate_result": None,
        }

    def status(self) -> dict[str, Any]:
        counts = {
            table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "capabilities",
                "decisions",
                "implementations",
                "mechanisms",
                "evidence",
                "relationships",
                "ownership_assignments",
                "graph_provenance",
                "canonical_records",
            )
        }
        return {
            "database": str(self.database_path.absolute()),
            "counts": counts,
            "seed_version": self.connection.execute(
                "SELECT value FROM graph_metadata WHERE key = 'AG2_SEED_VERSION'"
            ).fetchone()[0],
            "canonical_seed_version": self.connection.execute(
                "SELECT value FROM graph_metadata WHERE key = 'CANONICAL_SEED_VERSION'"
            ).fetchone()[0],
            "previous_best_engine": False,
            "architecture_gate_engine": False,
            "semantic_vector_retrieval": False,
        }

    def canonical_records(
        self,
        *,
        capabilities: Sequence[str] = (),
        kinds: Sequence[str] = (),
        query: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[str] = []
        if capabilities:
            placeholders = ",".join("?" for _ in capabilities)
            clauses.append(
                "record_id IN (SELECT record_id FROM canonical_record_capabilities "
                f"WHERE capability_id IN ({placeholders}))"
            )
            parameters.extend(capabilities)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"record_kind IN ({placeholders})")
            parameters.extend(kinds)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [
            self._decoded(row)
            for row in self.connection.execute(
                f"SELECT * FROM canonical_records{where} ORDER BY record_kind, record_id",
                tuple(parameters),
            )
        ]
        terms = [normalize_alias(term) for term in query.split() if normalize_alias(term)]
        result: list[dict[str, Any]] = []
        for row in rows:
            row["user_decision_required"] = bool(row["user_decision_required"])
            row["user_valued"] = bool(row["user_valued"])
            row["provenance"] = self._provenance("CANONICAL_RECORD", str(row["record_id"]))
            payload = normalize_alias(_json(row))
            if not terms or all(term in payload for term in terms):
                result.append(row)
        return result

    def canonical_context(
        self, capabilities: Sequence[str] = (), *, query: str = ""
    ) -> dict[str, Any]:
        records = self.canonical_records(capabilities=capabilities)
        grouped: dict[str, list[dict[str, Any]]] = {
            kind.value: [] for kind in CanonicalKind
        }
        for record in records:
            grouped[str(record["record_kind"])].append(record)
        normalized_query = normalize_alias(query)
        requested_retirement = []
        mutation = any(
            marker in normalized_query
            for marker in ("restore", "add", "use", "build", "replace", "вернуть", "добавить", "восстановить")
        )
        explicitly_negated = any(
            marker in normalized_query
            for marker in (
                "do_not_restore",
                "must_not_restore",
                "without_restoring",
                "не_восстанавливать",
                "не_возвращать",
            )
        )
        mutation = mutation and not explicitly_negated
        if mutation:
            retirement_terms = {
                "RC01": ("packet_gap", "пакет"),
                "RC02": ("fixed_timeout", "фиксирован"),
                "RC03": ("provider_vad", "vad"),
                "RC04": ("hard_language", "four_language", "четыр"),
                "RC05": ("whisper",),
                "RC06": ("sapi",),
                "RC07": ("mandatory_qwen", "qwen_operational"),
                "RC08": ("20_30", "pilot_corpus"),
            }
            requested_retirement = [
                record
                for record in grouped[CanonicalKind.RETIREMENT.value]
                if any(term in normalized_query for term in retirement_terms.get(str(record["record_id"]), ()))
            ]
        if requested_retirement:
            classification = "RETIREMENT_CONFLICT"
        elif grouped[CanonicalKind.HISTORICAL_RECONNECT.value]:
            classification = WorkClassification.HISTORICAL_ADAPTATION.value
        elif grouped[CanonicalKind.RECOVERED_IDEA.value]:
            domain_current = [
                record
                for record in grouped[CanonicalKind.GOLDEN_COMPONENT.value]
                if record["record_id"] != "GC18"
            ]
            classification = (
                WorkClassification.PARTIAL_IMPLEMENTATION_COMPLETION.value
                if domain_current
                else WorkClassification.RECOVERED_IDEA_IMPLEMENTATION.value
            )
        elif grouped[CanonicalKind.GOLDEN_COMPONENT.value]:
            classification = WorkClassification.CURRENT_EXTENSION.value
        else:
            classification = WorkClassification.TRUE_GREENFIELD.value
        signature = self.connection.execute(
            "SELECT value FROM graph_metadata WHERE key = 'CANONICAL_INPUT_SIGNATURE'"
        ).fetchone()
        return {
            "strategy": grouped[CanonicalKind.STRATEGY.value],
            "current_best": grouped[CanonicalKind.GOLDEN_COMPONENT.value],
            "historical_best": grouped[CanonicalKind.HISTORICAL_RECONNECT.value],
            "recovered_unimplemented_ideas": grouped[CanonicalKind.RECOVERED_IDEA.value],
            "user_valued_forgotten_ideas": grouped[CanonicalKind.USER_VALUED_IDEA.value],
            "do_not_reinvent": grouped[CanonicalKind.DO_NOT_REINVENT.value],
            "retirement_candidates": grouped[CanonicalKind.RETIREMENT.value],
            "retirement_conflicts": requested_retirement,
            "roadmap_stages": grouped[CanonicalKind.ROADMAP_STAGE.value],
            "work_classification": classification,
            "actually_missing": classification == WorkClassification.TRUE_GREENFIELD.value,
            "search_order": [
                "CURRENT_BEST",
                "HISTORICAL_IMPLEMENTATION",
                "HISTORICAL_MECHANISM",
                "DISCONNECTED",
                "PROBE",
                "RECOVERED_UNIMPLEMENTED_IDEA",
                "TRUE_GREENFIELD",
            ],
            "input_signature": str(signature[0]) if signature else "MISSING",
        }

    def _select_nodes(
        self, table: str, id_column: str, node_ids: Sequence[str]
    ) -> list[dict[str, Any]]:
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        return [
            self._decoded(row)
            for row in self.connection.execute(
                f"SELECT * FROM {table} WHERE {id_column} IN ({placeholders}) ORDER BY {id_column}",
                tuple(node_ids),
            )
        ]
