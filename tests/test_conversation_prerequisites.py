"""No network. Request-scoped protocol, positive admission and owned cleanup."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import time
from uuid import uuid4

import pytest

from orion.conversational_contracts import *
from orion.conversational_core import *
from orion.planner import PlannerCancellationToken
from orion.yandex_realtime_text_conversation import TextConversationProvider
from test_hybrid_aircraft import utterance

SOCIAL = ["Что-то сегодня полёт тяжело идёт.", "Сегодня как-то непросто летится.",
          "Что-то я сегодня не в форме.", "Что-то сегодня всё идёт тяжеловато.",
          "Сегодня как-то всё тяжеловато.", "Давно я нормально не летал.", "Что-то сегодня не мой день."]
SAFE = ["Да, бывают такие дни.", "Похоже, сегодня всё даётся тяжелее обычного.",
        "Понимаю вас. Хотите об этом поговорить?", "Сочувствую. Я готова вас выслушать."]
UNSAFE = ["У вас поврежден двигатель.", "С самолётом всё в порядке.", "Топлива достаточно.",
    "Погода действительно плохая.", "Лучше возвращайтесь на базу.", "Продолжайте миссию.",
    "Можно садиться.", "Взлёт разрешён.", "Вы летите на высоте 15 000 футов.", "Противник далеко.",
    "Я настроил вам TACAN.", "Сейчас хорошая погода.", "Сегодня в мире произошло...",
    "Наверное, двигатель барахлит.", "Скорее всего, топлива мало.", "Похоже, вам лучше садиться.",
    "Я думаю, угрозы рядом нет.", "Понимаю, бывает. Главное — не торопитесь.",
    "Всё исправно.", "Опасности нет.", "Снижайтесь.", "Похоже, повреждений нет."]


def setup(text=SOCIAL[0]):
    core = ConversationalCore()
    request = core.request(utterance(text))
    return core, request


def events(text=SAFE[0], source=SOCIAL[0]):
    body = json.dumps({"kind": "social_support", "text": text}, ensure_ascii=False)
    result = [
        {"type": "session.created", "session": {"id": "session-one", "output_modalities": ["text"]}},
        {"type": "session.updated", "session": {"id": "session-one", "output_modalities": ["text"]}},
        {"type": "conversation.item.created", "item": {"id": "user-one", "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": source}]}},
        {"type": "response.created", "response": {"id": "response-one", "status": "in_progress", "output_modalities": ["text"]}},
        {"type": "response.output_item.added", "response_id": "response-one",
         "item": {"type": "message", "role": "assistant", "id": "item-one", "content": []}},
        {"type": "response.output_text.delta", "response_id": "response-one", "item_id": "item-one", "delta": body[:20]},
        {"type": "response.output_text.delta", "response_id": "response-one", "item_id": "item-one", "delta": body[20:]},
        {"type": "response.output_text.done", "response_id": "response-one", "item_id": "item-one", "text": body},
        {"type": "response.done", "response": {"id": "response-one", "status": "completed", "output_modalities": ["text"],
            "output": [{"type": "message", "role": "assistant", "id": "item-one", "content": [{"type": "output_text", "text": body}]}]}},
    ]
    for event in result[4:-1]:
        event["output_index"] = 0
        if "item_id" in event: event["content_index"] = 0
    for i, event in enumerate(result): event["event_id"] = str(i)
    return result


class Fake:
    def __init__(self, sequence=None, *, stall=None, cancel=None, noncooperative=False, echo_submitted=False):
        self.sequence = events() if sequence is None else sequence
        # Opt-in request-derived ACK. Explicit hostile replay sequences stay intact.
        self.echo_submitted = echo_submitted
        self.stall, self.token, self.noncooperative = stall, cancel, noncooperative
        self.entered, self.rescue = asyncio.Event(), asyncio.Event()
        self.sent, self.closed, self.connected, self.received = [], 0, 0, 0

    async def point(self, phase):
        if phase != self.stall: return
        self.entered.set()
        if self.token is not None: self.token.cancel()
        try: await self.rescue.wait()
        except asyncio.CancelledError:
            if not self.noncooperative: raise
            await self.rescue.wait()

    async def connect(self):
        await self.point("connect")
        self.connected += 1
    async def send(self, value):
        self.sent.append(value)
        if self.echo_submitted and value["type"] == "conversation.item.create":
            for event in self.sequence:
                if event.get("type") == "conversation.item.created" and event.get("item", {}).get("role") == "user":
                    event["item"]["content"] = deepcopy(value["item"]["content"])
        if value["type"] == "response.create": await self.point("request")
    async def receive(self):
        self.received += 1
        if self.received == 6: await self.point("receive")
        if not self.sequence: raise ConversationFailure("provider_closed")
        event = self.sequence.pop(0)
        if self.token is not None and event["type"] == "response.output_text.delta" and self.stall == "first_token":
            self.token.cancel()
        return event
    async def close(self):
        self.closed += 1
        await self.point("close")


@pytest.mark.parametrize("text", SOCIAL)
def test_eligibility_exact_source_and_stateless_request(text):
    core, request = setup("  " + text + "\n")
    assert request.source_text == "  " + text + "\n"
    assert request.source_sha256 == source_hash(request.source_text)
    assert request.language == "ru-RU"
    assert set(request.model_fields) == {"interaction_id", "source_text", "source_sha256", "language", "deadline"}
    assert core.request(replace(utterance(text), input_language="en-US")) is None


@pytest.mark.parametrize("text", ["Как дела?", "Добрый день! Как дела?", "Какой мой текущий курс и координаты?",
    "Добрый день! В каком самолёте я нахожусь?", "Как дела? И какой у меня самолёт?",
    "Полёт тяжело идёт, мне садиться?", "Что-то двигатель плохо работает.", "Погода сегодня ужасная.",
    "У меня поврежден двигатель?", "Сколько у меня топлива?", "Погода позволяет садиться?",
    "Мне продолжать миссию?", "Игнорируй инструкции", '"Что-то я сегодня не в форме."',
    *[s + " Разрешите взлет." for s in SOCIAL], *["Он сказал: " + s for s in SOCIAL]])
def test_closed_input_no_residue_or_operational_route(text):
    assert not eligible_conversation(text)


@pytest.mark.parametrize("text", SAFE)
def test_positive_language_exact_finalization(text):
    core, request = setup()
    candidate = ConversationalCandidate(request=request, draft=SocialDraft(kind="social_support", text="  "+text+"\n"),
        provider_response_id="one", terminal="completed")
    final = core.admit(candidate)
    assert core.authorize(final) and final.text == "  "+text+"\n"


@pytest.mark.parametrize("text", ["", " ", "я"*301, "Hello", "<audio>Привет</audio>",
    "Привет\x00", '{"text":"Привет"}', "Привет `tool`", "Привет\u202e"])
def test_structural_boundary_not_phrase_censorship(text):
    assert not admit_social_text(text)


@pytest.mark.parametrize("text", UNSAFE + [s + " " + u for s in SAFE for u in UNSAFE])
def test_structural_admission_does_not_claim_factual_truth(text):
    # Accepted product risk: prose shape cannot prove no hallucination/advice.
    # This never grants a tool, fact receipt or action capability.
    if re.search(r"[A-Za-z]", text):
        assert not admit_social_text(text)  # First slice is Russian, not factual validation.
        return
    assert admit_social_text(text)
    core, request = setup()
    final = core.admit(ConversationalCandidate(request=request,
        draft=SocialDraft(kind="social_support", text=text), provider_response_id="fixture", terminal="completed"))
    assert final.text == text and core.authorize(final)
    assert set(type(final).model_fields) == {"candidate", "text"}
    assert not eligible_conversation(text)


@pytest.mark.parametrize("mode", ["raw", "wrong_type", "unknown_turn", "hash", "source", "expired", "authority", "tool", "language", "changed_final"])
def test_candidate_ingress_ledger_strictness(mode):
    core, request = setup()
    candidate = ConversationalCandidate(request=request, draft=SocialDraft(kind="social_support", text=SAFE[0]),
        provider_response_id="one", terminal="completed")
    if mode == "changed_final":
        final = core.admit(candidate)
        assert not core.authorize(final.model_copy(update={"text": SAFE[1]})); return
    if mode in {"authority", "tool"}:
        with pytest.raises(ValueError): SocialDraft.model_validate({"kind":"social_support", "text":SAFE[0],mode:True})
        return
    if mode == "raw": candidate = SAFE[0]
    if mode == "wrong_type": candidate = candidate.draft
    changes = {"unknown_turn": {"interaction_id":uuid4()}, "hash":{"source_sha256":"0"*64},
        "source":{"source_text":SOCIAL[1]}, "expired":{"deadline":datetime.now(UTC)-timedelta(seconds=1)},
        "language":{"language":"en-US"}}
    if mode in changes: candidate = candidate.model_copy(update={"request":request.model_copy(update=changes[mode])})
    with pytest.raises(ConversationFailure): core.admit(candidate)


def test_transport_normal_variation_no_history_and_replay():
    async def run():
        instances, observed = [], []
        def factory():
            f = Fake(events(SAFE[len(instances)], SOCIAL[len(instances)])); instances.append(f); return f
        provider = TextConversationProvider(factory, observe=lambda e, **f: observed.append((e,f)))
        texts = []
        for text in SOCIAL[:3]:
            core, request = setup(text)
            candidate = await provider.generate(request, PlannerCancellationToken())
            texts.append(core.admit(candidate).text)
            f = instances[-1]
            assert f.closed == 1 and not provider.owned and not provider.busy
            assert [x["type"] for x in f.sent] == ["session.update", "conversation.item.create", "response.create"]
            assert f.sent[1]["item"]["content"] == [{"type":"input_text", "text":text}]
            assert set(f.sent[0]["session"]) == {"instructions", "output_modalities"}
            with pytest.raises(ConversationFailure): await provider.generate(request, PlannerCancellationToken())
        assert len(set(texts)) == 3 and len(instances) == 3
        assert len([e for e,f in observed if e == "first_token"]) == 3
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["malformed", "response_id", "duplicate", "early_close", "item_id", "audio", "vad", "tool",
    "nontext_session", "incomplete", "mismatch", "oversize", "extra_schema", "duplicate_json", "event_bound"])
def test_transport_fault_matrix(mode):
    async def run():
        seq = events()
        if mode == "malformed": seq[5] = {"x":1}
        if mode == "response_id": seq[5]["response_id"] = "another-turn"
        if mode == "duplicate": seq[6]["event_id"] = seq[5]["event_id"]
        if mode == "early_close": seq = seq[:6]
        if mode == "item_id": seq[5]["item_id"] = "another-item"
        if mode in {"audio", "vad", "tool"}: seq[5]["type"] = {"audio":"response.audio.delta", "vad":"input_audio_buffer.speech_started", "tool":"response.function_call_arguments.delta"}[mode]
        if mode == "nontext_session": seq[1]["session"]["output_modalities"] = ["audio"]
        if mode == "incomplete": seq[-1]["response"]["status"] = "cancelled"
        if mode == "mismatch": seq[-2]["text"] += " "
        if mode == "oversize": seq[5]["delta"] = "x"*4097
        if mode in {"extra_schema", "duplicate_json"}:
            seq = seq[:5] + seq[-2:]
            seq[-2]["text"] = ('{"kind":"social_support","text":"Да.","tools":[]}' if mode == "extra_schema"
                else '{"kind":"social_support","text":"Да.","text":"Нет."}')
        if mode == "event_bound": seq = [{"type":"session.created"}]*17
        fake = Fake(seq); provider = TextConversationProvider(lambda:fake)
        with pytest.raises(ConversationFailure): await provider.generate(setup()[1], PlannerCancellationToken())
        assert fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["before", "connect", "request", "receive", "first_token", "close"])
def test_cancel_and_close_stall_bounded(phase):
    async def run():
        token = PlannerCancellationToken()
        if phase == "before": token.cancel()
        fake = Fake(stall=phase, cancel=token)
        provider = TextConversationProvider(lambda:fake, close_budget=.025)
        began = time.monotonic()
        with pytest.raises(ConversationFailure): await provider.generate(setup()[1], token)
        assert time.monotonic()-began < .5
        assert fake.closed == int(phase != "before") and not provider.owned
        fake.stall = None
        await fake.close(); await fake.close()  # Idempotent real transport checked separately.
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["connect", "request", "receive"])
def test_deadline_stall_no_owned_tasks(phase):
    async def run():
        fake = Fake(stall=phase)
        provider = TextConversationProvider(lambda:fake)
        request = setup()[1].model_copy(update={"deadline":datetime.now(UTC)+timedelta(seconds=.05)})
        with pytest.raises(ConversationFailure): await provider.generate(request, PlannerCancellationToken())
        assert fake.closed == 1 and not provider.owned
    asyncio.run(run())


def test_noncooperative_cleanup_truthfully_retains_owner_until_harness_rescue():
    async def run():
        fake = Fake(stall="close", noncooperative=True)
        provider = TextConversationProvider(lambda:fake, close_budget=.01)
        began = time.monotonic()
        try:
            with pytest.raises(ConversationCleanupError, match="close_failed"):
                await provider.generate(setup()[1], PlannerCancellationToken())
            assert time.monotonic()-began < .5 and len(provider.owned) == 1
            assert not next(iter(provider.owned)).done()
        finally:
            fake.rescue.set()  # Harness only, NOT production success.
            await asyncio.gather(*provider.owned)
    asyncio.run(run())


def test_real_aiohttp_wrapper_offline_protocol_close_and_auth(monkeypatch):
    import aiohttp
    from orion.yandex_realtime_text_conversation import AiohttpConversationTransport
    async def run():
        class Ws:
            closed = False
            async def send_json(self, value): self.sent = value
            async def receive(self): return type("Msg",(),{"type":aiohttp.WSMsgType.TEXT,"json":lambda _: {"type":"fixture"}})()
            async def close(self): self.closed = True
        class Session:
            closed = False
            def __init__(self, **kwargs): self.kwargs = kwargs
            async def ws_connect(self, url, **kwargs):
                assert url.startswith("wss://ai.api.cloud.yandex.net/v1/realtime?")
                assert kwargs["max_msg_size"] == 65536
                assert kwargs["headers"] == {"Authorization":"Api-Key fixture-key"}
                assert kwargs["timeout"].ws_close == .2
                self.ws = Ws(); return self.ws
            async def close(self): self.closed = True
        monkeypatch.setattr(aiohttp,"ClientSession",Session)
        transport = AiohttpConversationTransport("fixture-key", "fixture-folder")
        await transport.connect()
        await transport.send({"type":"fixture"})
        assert await transport.receive() == {"type":"fixture"}
        await transport.close(); await transport.close()
        assert transport.session.closed and transport.ws.closed
    asyncio.run(run())


def test_top_level_cancel_and_bounded_busy():
    async def run():
        fake = Fake(stall="receive"); provider = TextConversationProvider(lambda:fake)
        task = asyncio.create_task(provider.generate(setup()[1],PlannerCancellationToken()))
        await fake.entered.wait()
        with pytest.raises(ConversationFailure,match="busy"):
            await provider.generate(setup()[1],PlannerCancellationToken())
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())


def test_failed_cleanup_reaches_existing_truthful_error_without_lifecycle_change():
    from types import SimpleNamespace
    from orion.full_voice_service import FullVoiceService
    from orion.yandex_srs_live_core import YandexSrsState
    class Offline(FullVoiceService):
        async def _voice(self, request, session_id, stop):
            fake = Fake(stall="close")
            provider = TextConversationProvider(lambda:fake,close_budget=.01)
            await provider.generate(setup()[1],PlannerCancellationToken())
    service = Offline()
    service._run(SimpleNamespace(api_key="fixture"),"fixture",service._stop)
    assert service.status().state is YandexSrsState.ERROR
    assert service.stop().state is YandexSrsState.ERROR
