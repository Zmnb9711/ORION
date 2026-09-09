"""Approved capability-isolated conversation; no claim of semantic certification."""
import ast
import asyncio
from pathlib import Path

from orion.conversational_core import parse_draft, normalize_candidate_envelope
from orion.planner import PlannerCancellationToken
from test_conversation_prerequisites import Fake, events, SOCIAL
from test_conversation_presentation import rig
from test_hybrid_aircraft import utterance

FIFTH_BODY = '{"kind":"social_support","text":"Похоже, сегодня у вас непростой день. Сочувствую. Если хотите поговорить — я на связи."}'
FIFTH_RAW = ' ```\n' + FIFTH_BODY + '\n```'


def test_fifth_recorded_candidate_exact_to_existing_tts_radio():
    async def run():
        text = parse_draft(FIFTH_RAW).text
        assert normalize_candidate_envelope(FIFTH_RAW) == FIFTH_BODY
        voice, router, radio, tts, observed = rig(Fake(events(text)))
        try:
            assert await voice.run(utterance(SOCIAL[0]), PlannerCancellationToken())
            assert tts.texts == [text]
            assert len(radio.transmit_calls) == 1
            assert not voice.provider.owned
            assert any(e == "response_terminal" and f["status"] == "completed" for e, f in observed)
        finally:
            await voice.shutdown()
            router.shutdown()
    asyncio.run(run())


def test_no_phrase_productions_no_authority_dependencies():
    for name in ("conversational_core", "conversational_contracts", "conversational_presentation",
                 "yandex_realtime_text_conversation"):
        source = Path("orion", name + ".py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any(any(x in module for x in ("tool_gateway", "world_model", "qwen", "full_voice_core")) for module in imports)
        assert "_CLAUSES" not in source
