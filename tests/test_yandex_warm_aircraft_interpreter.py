"""Offline warm lifecycle and ACK-backed context isolation, no cloud/network."""
import asyncio
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import pytest

from orion.aircraft_interpretation import InterpretationRequest, WARM_INTERPRETER_PROVIDER, source_hash
from orion.conversational_contracts import ConversationFailure
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter, InterpreterState
from test_conversation_prerequisites import events

A = "Что у нас за машина?"
B = "Где мы?"


def req(text=A):
    return InterpretationRequest(interaction_id=uuid4(), operation_id=uuid4(), source_text=text,
        source_sha256=source_hash(text), deadline=datetime.now(UTC)+timedelta(seconds=2),
        expected_provider=WARM_INTERPRETER_PROVIDER)


class Wire:
    def __init__(self, mode="normal"):
        self.queue = asyncio.Queue()
        self.sent, self.items, self.classified = [], set(), []
        self.connected = self.closed = 0
        self.mode, self.source = mode, ""
        self.entered = asyncio.Event()

    async def connect(self):
        self.connected += 1
        if self.mode == "connect_error": raise OSError("fixture")
        if self.mode == "connect_stall":
            self.entered.set(); await asyncio.Event().wait()

    async def send(self, value):
        self.sent.append(value)
        kind = value["type"]
        if kind == "session.update":
            for e in events()[:2]: self.queue.put_nowait(e)
        elif kind == "conversation.item.create":
            assert not self.items, "previous server context was not deleted"
            self.source = value["item"]["content"][0]["text"]
        elif kind == "response.create":
            self.entered.set()
            if self.mode == "generation_stall": return
            self.classified.append(self.source)
            value = "aircraft.identity" if self.source == A else "not_applicable"
            data = events("placeholder", source=self.source)[2:]
            body = json.dumps({"capability": value})
            if self.mode == "bad_schema": body = '{"aircraft":"F/A-18C"}'
            # Same real protocol structure; only the role-specific text payload changes.
            for e in data:
                if e["type"] == "response.output_text.delta": e["delta"] = ""
                if e["type"] == "response.output_text.done": e["text"] = body
                if e["type"] == "response.done": e["response"]["output"][0]["content"][0]["text"] = body
            data[3]["delta"] = body
            if self.mode == "wrong_response": data[-1]["response"]["id"] = "wrong"
            self.items.update(("user-one", "item-one"))
            for e in data: self.queue.put_nowait(e)
        elif kind == "conversation.item.delete":
            identity = value["item_id"]
            assert identity in self.items
            if self.mode == "delete_stall": return
            self.items.remove(identity)
            self.queue.put_nowait({"type": "conversation.item.deleted", "event_id": "delete-"+identity,
                "item_id": "wrong" if self.mode == "wrong_delete" else identity})

    async def receive(self): return await self.queue.get()
    async def close(self): self.closed += 1; self.items.clear()


@pytest.mark.parametrize("order", [(A, B), (B, A), (A, B, A)])
def test_warm_same_owner_ack_isolation_both_orders(order):
    async def run():
        wire, observed = Wire(), []
        owner = WarmYandexAircraftInterpreter(lambda: wire, observe=lambda e, **f: observed.append((e, f)))
        assert await owner.prepare()
        for text in order:
            result = await owner.interpret(req(text), PlannerCancellationToken())
            assert result.intent.capability == ("aircraft.identity" if text == A else "not_applicable")
            assert owner.state is InterpreterState.ISOLATING
            await owner.wait_isolation()
            assert owner.state is InterpreterState.READY and not wire.items
        assert owner.connect_count == wire.connected == 1
        assert owner.operation_count == owner.result_count == len(order)
        assert sum(e == "item_deleted" for e, _ in observed) == 2*len(order)
        assert all("tools" not in p and "audio" not in p for p in wire.sent)
        await owner.shutdown()
        assert wire.closed == 1 and not owner.owned
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["bad_schema", "wrong_response", "generation_stall"])
def test_failure_never_admits_or_reuses_dirty_connection(mode):
    async def run():
        wire = Wire(mode); owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert await owner.prepare()
        with pytest.raises((ValueError, ConversationFailure)):
            await owner.interpret(req(), PlannerCancellationToken())
        assert owner.state is InterpreterState.DEGRADED and wire.closed == 1
        with pytest.raises(ConversationFailure, match="not_warm"):
            await owner.interpret(req(B), PlannerCancellationToken())
        assert wire.connected == 1 and not owner.owned and owner.result_count == 0
        await owner.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["cold", "idle", "connecting", "active"])
def test_shutdown_every_state_drains(phase):
    async def run():
        wire = Wire("connect_stall" if phase == "connecting" else "generation_stall")
        owner = WarmYandexAircraftInterpreter(lambda: wire)
        active = None
        if phase == "connecting": active = asyncio.create_task(owner.prepare())
        elif phase != "cold":
            assert await owner.prepare()
            if phase == "active": active = asyncio.create_task(owner.interpret(req(), PlannerCancellationToken()))
        if active: await wire.entered.wait()
        await owner.shutdown()
        assert not owner.owned and owner.state is InterpreterState.STOPPED
        if active: assert active.done()
        assert wire.closed == int(phase != "cold")
    asyncio.run(run())


def test_warmup_failure_is_optional_and_has_no_retry():
    async def run():
        wire = Wire("connect_error"); owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert not await owner.prepare()
        assert not await owner.prepare()
        assert wire.connected == wire.closed == 1
        await owner.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["hash", "provider", "expired", "cancel", "replay"])
def test_bad_request_no_new_provider_operation(mutation):
    async def run():
        wire = Wire(); owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert await owner.prepare()
        r, token = req(), PlannerCancellationToken()
        if mutation == "hash": r = r.model_copy(update={"source_sha256": "a"*64})
        if mutation == "provider": r = r.model_copy(update={"expected_provider": "evil"})
        if mutation == "expired": r = r.model_copy(update={"deadline": datetime.now(UTC)-timedelta(seconds=1)})
        if mutation == "cancel": token.cancel()
        if mutation == "replay": await owner.interpret(r, token)
        count = owner.operation_count
        with pytest.raises(ConversationFailure): await owner.interpret(r, token)
        assert owner.operation_count == count
        await owner.shutdown()
    asyncio.run(run())
