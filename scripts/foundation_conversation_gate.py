"""Explicit provider-only Step 2 evaluation. No audio, DCS, tools or retry.

Run once with --live; results are bounded developer test data, not user history.
Controlled failure replaces only the parser input in this isolated process.
The actual provider terminal is retained separately and is never mislabelled.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orion.full_voice_stt import FinalizedUserUtterance
from orion.general_semantic_contracts import Dialogue, parse_semantic, provider_instructions
from orion.general_semantic_core import GeneralSemanticCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.interaction_router import InteractionRouter
from orion.personal_context import PersonalContext
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter

CASES = (
    ('ordinary', 'ru-RU', 'Хочется ненадолго отвлечься от дел. Предложи необычную тему для разговора.'),
    ('knowledge', 'ru-RU', 'Объясни коротко, почему радуга имеет форму дуги.'),
    ('continuation', 'ru-RU', 'А почему её центр нельзя увидеть над горизонтом с земли?'),
    ('variation', 'ru-RU', 'Объясни ту же мысль иначе, через наглядное сравнение.'),
    ('another_topic', 'ru-RU', 'Сменим тему: что тебе кажется интересным в старых библиотеках?'),
    ('knowledge', 'en-US', 'Why does a pendulum gradually stop in ordinary air?'),
    ('continuation', 'en-US', 'Where does that energy go?'),
    ('variation', 'en-US', 'Give me a different everyday analogy for that energy transfer.'),
    ('controlled_failure', 'en-US', 'Briefly explain what a palindrome is.'),
    ('after_recovery', 'en-US', 'What makes a short story satisfying even with an open ending?'),
)
ALLOWED = {
    'turn_id', 'operation_id', 'provider_session_id', 'provider_response_id',
    'raw_terminal_text', 'normalized_candidate', 'parsed_terminal', 'semantic_kind',
    'first_text_ms', 'terminal_ms', 'cold_connect_ms', 'isolation_ms', 'user_path_ms',
    'connect_count', 'operation_count', 'result_count', 'history_items_remaining',
    'validation_type', 'validation_path', 'error_class', 'failure_category',
}


class NoTools:
    def definitions(self):
        return ()

    def execute(self, *args, **kwargs):
        raise AssertionError('provider_gate_forbids_tool_execution')


async def evaluate(factory, save):
    report = {'scope': 'developer provider-only; no field/audio proof', 'turns': [], 'events': []}
    current = None

    def observe(event, **fields):
        target = current['events'] if current is not None else report['events']
        if len(target) >= 128:
            return
        clean = {key: value for key, value in fields.items() if key in ALLOWED
                 and isinstance(value, (str, int, float, bool, type(None)))
                 and (not isinstance(value, str) or len(value.encode('utf-8')) <= 4096)}
        target.append({'event': event, 'monotonic': time.monotonic(), **clean})

    owner = factory(observe)
    router = InteractionRouter(provider_factory=lambda: (_ for _ in ()).throw(AssertionError('no_planner')))
    core = GeneralSemanticCore(NoTools(), router, 'step2-eval-'+str(uuid4()))
    hybrid = HybridAircraftCore(NoTools(), lambda: (_ for _ in ()).throw(AssertionError('no_planner')))

    def measured_parse(text):
        start = time.monotonic()
        assert current is not None
        parse_input = '{"kind":"DIALOGUE","text":[]}' if current['case'] == 'controlled_failure' else text
        if current['case'] == 'controlled_failure':
            current['controlled_parse_input'] = parse_input
        try:
            return parse_semantic(parse_input)
        finally:
            current['parse_ms'] = current.get('parse_ms', 0) + (time.monotonic()-start)*1000

    try:
        if not await owner.prepare():
            report['failure'] = 'cold_handshake_failed'
            return report
        # No persistent personal data is sent in this developer-only evaluation.
        with patch('orion.general_semantic_core.load_personal_context', PersonalContext), \
                patch('orion.yandex_warm_aircraft_interpreter.parse_semantic', measured_parse):
            for case, language, text in CASES:
                now = datetime.now(UTC)
                u = FinalizedUserUtterance(uuid4(), text, 1, 2, 1.9, 2.1, 2.2, 2.3,
                    now, now, 'developer-text-no-stt', 0, 0, language)
                req = core.request(u)
                current = {'case': case, 'language': language, 'request': req.model_dump(mode='json'),
                           'events': [], 'prompt_sha256': hashlib.sha256(
                               provider_instructions(req.context, req.personal_context).encode()).hexdigest()}
                report['turns'].append(current)
                count = owner.operation_count
                try:
                    proposal = await owner.interpret_general(req, PlannerCancellationToken())
                    current['parsed'] = proposal.result.model_dump(mode='json')
                    if not isinstance(proposal.result, Dialogue):
                        raise ValueError('non_dialogue_evaluation_result')
                    start = time.monotonic()
                    final = core.execute(u, proposal, PlannerCancellationToken(), hybrid)
                    current['admission_ms'] = (time.monotonic()-start)*1000
                    current['admitted_response'] = final.text
                    core.context.accept(final, delivery='unknown')
                    await owner.wait_isolation()
                    current['status'] = 'admitted_isolated'
                except Exception as exc:
                    current['exception_class'] = type(exc).__name__
                    if case != 'controlled_failure' or 'controlled_parse_input' not in current:
                        current['status'] = 'failed_stop'
                        break
                    current['status'] = 'controlled_validation_failure'
                    start = time.monotonic()
                    current['recovered'] = await owner.wait_recovery()
                    current['recovery_ms'] = (time.monotonic()-start)*1000
                    if not current['recovered']:
                        break
                finally:
                    current['provider_operations'] = owner.operation_count-count
                    save(report)
                if current['provider_operations'] != 1:
                    raise AssertionError('one_operation_required')
    except Exception as exc:
        report['failure'] = type(exc).__name__  # Never unrestricted exception/body.
    finally:
        await owner.shutdown()
        report['operation_count'] = owner.operation_count
        report['connect_count'] = owner.connect_count
        report['owned_tasks_after_shutdown'] = len(owner.owned)
        save(report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from orion.launcher_cloud_voice_sections import CloudVoiceConfigStore
    from orion.windows_credentials import VoiceCredential, default_voice_credential_store
    config = CloudVoiceConfigStore(Path(os.environ['LOCALAPPDATA'])/'ORION'/'runtime').load()
    key = default_voice_credential_store().load(VoiceCredential.YANDEX_API_KEY)
    if not key or not config.yandex_folder_id:
        raise SystemExit('configured_credentials_unavailable')

    def save(report):
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    result = asyncio.run(asyncio.wait_for(evaluate(lambda observe:
        WarmYandexAircraftInterpreter.configured(key, config.yandex_folder_id, general=True, observe=observe), save), 180))
    print(json.dumps({'turns': len(result['turns']), 'operations': result.get('operation_count'),
                      'failure': result.get('failure'), 'report': str(args.output/'report.json')}))


if __name__ == '__main__':
    main()
