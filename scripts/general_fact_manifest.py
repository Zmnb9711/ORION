"""Generate fact inventory artifacts; --write updates only the two checked-in manifests."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orion.general_fact_registry import FACTS, CATALOG, CATALOG_VERSION, Exposure, provider_catalog


def trace(item):
    mission = item.source in {'mission_store', 'mission_bridge'}
    return {'source':item.raw_field, 'transport_model':item.normalized_field,
        'owner': 'MissionStore / MissionBridgeTelemetryStore' if mission else 'LiveTelemetryStore',
        'facade':'orion/world_model.py:WorldModelFacade',
        'gateway':item.tool, 'selector':item.snapshot_field, 'leaves':list(item.leaves),
        'admission':'orion/general_semantic_core.py:GeneralSemanticCore._facts' if item.exposed else None,
        'first_unproven_boundary':None if item.exposed else item.reason,
        'evidence_reference':'docs/history/2026-09-14-foundation-step4-fact-surface.md'}


def manifest():
    return {"schema":"orion.general-fact-manifest.v1", "registry_version":CATALOG_VERSION,
        "exposed_count":len(CATALOG), "inventory_count":len(FACTS), "provider_catalog":provider_catalog(),
        "status_counts":dict(Counter(item.exposure.value for item in FACTS)),
        "fact_value_evidence":"OFFLINE only; provider selection is not live DCS value validation",
        "facts":[{**item.model_dump(mode="json"), "trace":trace(item),
            "mapper_status":"IMPLEMENTED" if item.exposed else "NOT_ADMITTED",
            "presentation_status":"IMPLEMENTED" if item.presentation else "NOT_IMPLEMENTED",
            "field_validated":False,
            "evidence_level":"CODE_PLUS_OFFLINE_GATEWAY_REPLAY" if item.exposed else "CODE_AUDIT_ONLY"} for item in FACTS]}


def matrix():
    rows = ['# Foundation fact inventory', '', 'ORION ARCHITECTURE GUARD: OFF', '',
            'Generated registry projection. No current values; physical field validation pending.', '']
    for status in Exposure:
        rows += ['## '+status.value, '', '| Fact | Source → normalized | Unit | Read / output | Reason |', '|---|---|---|---|---|']
        for item in FACTS:
            if item.exposure == status:
                rows.append(f'| {item.capability} | {item.raw_field} → {item.normalized_field} | '
                    f'{item.unit or "not admitted / structured"} | {item.tool or "not admitted"} / '
                    f'{item.presentation or "none"} | {item.reason} |')
        rows += ['']
    return '\n'.join(rows).rstrip()+'\n'


if __name__ == "__main__":
    if "--write" in sys.argv:
        root = Path(__file__).resolve().parents[1]
        (root/'docs/general-fact-surface.json').write_text(json.dumps(manifest(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (root/'docs/general-fact-matrix.md').write_text(matrix(), encoding='utf-8')
        print(json.dumps({'inventory':len(FACTS), 'exposed':len(CATALOG)}))
    elif "--matrix" in sys.argv:
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
