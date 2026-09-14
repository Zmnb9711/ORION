"""One explicit bounded Step 4 provider session, developer fixtures, no audio/DCS.

No retry. Source values belong to a controlled local fixture, not live DCS.
Terminal evidence is bounded by the existing safe developer-gate allowlist.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.foundation_conversation_gate import ALLOWED
from orion.full_voice_stt import FinalizedUserUtterance
from orion.general_fact_registry import CATALOG, CATALOG_VERSION, provider_catalog
from orion.general_semantic_contracts import SemanticProposal, parse_semantic, provider_instructions
from orion.general_semantic_core import GeneralSemanticCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.interaction_router import InteractionRouter
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Position, Attitude, SourceQuality, TelemetryEnvelope
from orion.personal_context import PersonalContext
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import build_tool_gateway
from orion.world_model import WorldModelFacade
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter

CASES = (
    ('single', 'Каково сейчас направление носа моего самолёта в градусах?', 'FACT_REQUEST', ('ownship.heading',)),
    ('different_class', 'Сообщи текущую истинную воздушную скорость моего борта.', 'FACT_REQUEST', ('ownship.true_airspeed',)),
    ('multi', 'Мне нужны одновременно текущий тангаж и геометрическая высота над морем.', 'FACT_REQUEST', ('ownship.pitch', 'ownship.altitude_msl')),
    ('summary', 'Дай краткий обзор текущих доступных параметров моего самолёта.', 'STATE_SUMMARY', ()),
    ('gap', 'Покажи текущую температуру выхлопа левого двигателя моего самолёта.', 'CAPABILITY_GAP', ()),
    ('knowledge', 'Почему воздушный шар поднимается при нагревании воздуха?', 'DIALOGUE', ()),
    ('meta', 'Какие категории данных ты можешь получать из симулятора?', 'META_REQUEST', ()),
    ('unseen_form', 'Сколько метров сейчас отделяет наш борт по высоте от поверхности под ним?', 'FACT_REQUEST', ('ownship.altitude_agl',)),
)
# Optional explicitly labelled offline accepted history for a bounded referent
# gate. No preceding provider operations are hidden or counted as live evidence.
PRECEDING = {}
WIRE_TIMELINE = False


async def evaluate(factory, save):
    report = {'scope':'LIVE provider selection + OFFLINE fixture Core; no DCS, STT, TTS, SRS or field proof',
              'registry_version':CATALOG_VERSION, 'catalog_count':len(CATALOG),
              'catalog_bytes':len(json.dumps(provider_catalog(), ensure_ascii=False, separators=(',', ':')).encode()),
              'instruction_bytes':len(provider_instructions().encode()), 'turns':[], 'events':[]}
    current = None

    def observe(event, **fields):
        target = report['events'] if current is None else current['events']
        if len(target) < 128:
            allowed = ALLOWED | {'context_binding_ms', 'instructions_sha256', 'generation_ms',
                                 'generation_first_text_ms', 'latency_target_exceeded', 'wire_type', 'total_ms'}
            clean = {k:v for k,v in fields.items() if k in allowed and isinstance(v, (str, int, float, bool, type(None)))
                     and (not isinstance(v, str) or len(v.encode()) <= 4096)}
            target.append({'event':event, 'monotonic':time.monotonic(), **clean})

    def no_planner():
        raise AssertionError('Planner forbidden in fact gate')

    owner = factory(observe)
    if WIRE_TIMELINE:
        underlying_factory = owner.factory
        class TimelinePort:
            def __init__(self): self.port = underlying_factory()
            async def connect(self): return await self.port.connect()
            async def send(self, value):
                observe('wire_send_start', wire_type=value.get('type'))
                result = await self.port.send(value)
                observe('wire_send_done', wire_type=value.get('type'))
                return result
            async def receive(self):
                result = await self.port.receive()
                observe('wire_received', wire_type=result.get('type'))
                return result
            async def close(self):
                observe('wire_close_start')
                result = await self.port.close()
                observe('wire_close_done')
                return result
        owner.factory = TimelinePort
    store = LiveTelemetryStore()
    gateway = build_tool_gateway(world=WorldModelFacade(telemetry=store))
    router = InteractionRouter(provider_factory=no_planner)
    core = GeneralSemanticCore(gateway, router, 'step4-developer-fixture')
    hybrid = HybridAircraftCore(gateway, no_planner)
    try:
        if not await owner.prepare():
            report['failure'] = 'handshake_failed'
            return report
        with patch('orion.general_semantic_core.load_personal_context', PersonalContext):
            for case in CASES:
                name, text, expected, capabilities = case[:4]
                language = case[4] if len(case) > 4 else 'ru-RU'
                now = datetime.now(UTC)
                store.set(TelemetryEnvelope(state=AircraftState(aircraft_type='FA-18C_hornet',
                    position=Position(latitude=41.2, longitude=43.3, altitude_m=1234, altitude_agl_m=200),
                    heading_deg=103.74, heading_valid=True, true_airspeed_mps=83, vertical_speed_mps=-3,
                    attitude=Attitude(pitch_deg=4, bank_deg=2, yaw_deg=104),
                    source_quality=SourceQuality(true_airspeed=True, vertical_speed=True, altitude_agl=True))), received_at=now)
                utterance = FinalizedUserUtterance(uuid4(), text, 1, 2, 1.9, 2.1, 2.2, 2.3,
                    now, now, 'developer-text-no-stt', 0, 0, language)
                preceding = []
                if name in PRECEDING:
                    core.context.reset()
                    for seed_text, body in PRECEDING[name]:
                        seed = FinalizedUserUtterance(uuid4(), seed_text, 1, 2, 1.9, 2.1, 2.2, 2.3,
                            now, now, 'offline-context-fixture-no-stt', 0, 0, language)
                        seed_request = core.request(seed)
                        proposal = SemanticProposal(request=seed_request, response_id='offline-seed',
                            result=parse_semantic(json.dumps(body)))
                        final_seed = core.execute(seed, proposal, PlannerCancellationToken(), hybrid)
                        core.context.accept(final_seed, delivery='unknown')
                        preceding.append({'scope':'OFFLINE accepted fixture, not provider output',
                            'request':seed_request.model_dump(mode='json'), 'semantic':body,
                            'plan':final_seed.plan.model_dump(mode='json'),
                            'context_after':core.context.project().model_dump(mode='json')})
                request = core.request(utterance)
                current = {'case':name, 'request':request.model_dump(mode='json'), 'expected_kind':expected,
                           'events':[], 'status':'started'}
                if preceding:
                    current['preceding_offline'] = preceding
                    current['provider_instructions'] = provider_instructions(request.context, request.personal_context)
                report['turns'].append(current)
                before = owner.operation_count
                started = time.monotonic()
                try:
                    proposal = await owner.interpret_general(request, PlannerCancellationToken())
                    current['semantic_user_path_ms'] = (time.monotonic()-started)*1000
                    current['parsed'] = proposal.result.model_dump(mode='json')
                    if proposal.result.kind != expected:
                        raise ValueError('unexpected_semantic_kind')
                    selection = current['parsed'].get('facts', current['parsed'])
                    if capabilities and set(selection.get('capabilities', ())) != set(capabilities):
                        raise ValueError('unexpected_fact_selection')
                    started = time.monotonic()
                    final = core.execute(utterance, proposal, PlannerCancellationToken(), hybrid)
                    current['core_and_presentation_ms'] = (time.monotonic()-started)*1000
                    current['core_fact_reads'] = core.read_count
                    current['finalized_fixture_text'] = final.text
                    current['plan_kind'] = final.plan.kind
                    core.context.accept(final, delivery='unknown')
                    await owner.wait_isolation()
                    current['status'] = 'admitted_isolated'
                except Exception as exc:
                    current['status'] = 'failed_stop'
                    current['exception_class'] = type(exc).__name__
                    # Only closed local causes, never provider bodies/credentials.
                    safe = {'unexpected_semantic_kind', 'unexpected_fact_selection', 'semantic_admission_rejected',
                            'general_fact_freshness', 'general_plan_expired'}
                    current['failure'] = str(exc) if str(exc) in safe else 'see_bounded_terminal_evidence'
                    report['failure'] = current['failure']
                    break
                finally:
                    current['provider_operations'] = owner.operation_count-before
                    save(report)
    finally:
        await owner.shutdown()
        report['operation_count'] = owner.operation_count
        report['connect_count'] = owner.connect_count
        report['owned_tasks_after_shutdown'] = len(owner.owned)
        report['pass'] = len(report['turns']) == len(CASES) and all(t['status']=='admitted_isolated' and
            t['provider_operations']==1 for t in report['turns']) and not owner.owned
        save(report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)  # No accidental overwrite/repeat of this gate.
    from orion.launcher_cloud_voice_sections import CloudVoiceConfigStore
    from orion.windows_credentials import VoiceCredential, default_voice_credential_store
    config = CloudVoiceConfigStore(Path(os.environ['LOCALAPPDATA'])/'ORION'/'runtime').load()
    key = default_voice_credential_store().load(VoiceCredential.YANDEX_API_KEY)
    if not key or not config.yandex_folder_id:
        raise SystemExit('configured_credentials_unavailable')

    def save(report):
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    result = asyncio.run(asyncio.wait_for(evaluate(lambda observe:WarmYandexAircraftInterpreter.configured(
        key, config.yandex_folder_id, general=True, observe=observe), save), 120))
    print(json.dumps({'pass':result['pass'], 'failure':result.get('failure'),
                      'operations':result.get('operation_count'), 'report':str(args.output/'report.json')}))


if __name__ == '__main__':
    main()
