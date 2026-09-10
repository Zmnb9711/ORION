"""Emit a source-derived fact inventory; no live state/provider access or writes."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orion.general_fact_registry import FACTS, CATALOG, CATALOG_VERSION, provider_catalog


def manifest():
    return {"schema":"orion.general-fact-manifest.v1", "registry_version":CATALOG_VERSION,
        "exposed_count":len(CATALOG), "inventory_count":len(FACTS), "provider_catalog":provider_catalog(),
        "fact_value_evidence":"OFFLINE only; provider selection is not live DCS value validation",
        "facts":[{**item.model_dump(mode="json"),
            "mapper_status":"IMPLEMENTED" if item.exposed else "NOT_ADMITTED",
            "presentation_status":"IMPLEMENTED" if item.presentation else "NOT_IMPLEMENTED",
            "field_validated":False,
            "evidence_level":"CODE_PLUS_OFFLINE_GATEWAY_REPLAY" if item.exposed else "CODE_AUDIT_ONLY"} for item in FACTS]}


if __name__ == "__main__":
    if "--matrix" in sys.argv:
        print("# Actual telemetry fact inventory\n\nORION ARCHITECTURE GUARD: OFF\n")
        print("Generated from Core registry. No phrases or current values. Field validation pending.\n")
        print("| Fact | Quality/exposure | Source / raw → normalized | Type/unit | Authority/freshness | Applicability | Read / presentation | Evidence | Reason |")
        print("|---|---|---|---|---|---|---|---|---|")
        for d in FACTS:
            print(f"| {d.capability} | {d.exposure.value} | {d.source}: {d.raw_field} → {d.normalized_field} | "
                  f"{d.value_type} / {d.unit or 'not established / structured'} | {d.authority}, {d.freshness_seconds}s | "
                  f"{', '.join(d.applicability) or 'common source; availability checked separately'} | "
                  f"{d.tool or 'not admitted'} / {d.presentation or 'none'} | "
                  f"{'code + offline replay' if d.exposed else 'code audit only'} | {d.reason} |")
    else:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
