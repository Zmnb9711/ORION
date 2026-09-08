"""Request-scoped text-only adapter. No audio, VAD, DCS or tool ownership.

Adapted from 8182e892 Realtime text protocol/assembler, NOT its presenter owner.
Every successful turn closes its own connection, including provider history.
"""
import asyncio
from datetime import UTC, datetime
import json
import time
from typing import Any, cast

from orion.conversational_contracts import ConversationalCandidate, ConversationCleanupError, ConversationFailure
from orion.conversational_core import parse_draft, source_hash
from orion.yandex_realtime_provider import build_yandex_url, yandex_authorization_headers


INSTRUCTIONS = (
    'Respond to this subjective difficult-day remark in Russian. No tools, facts, aviation advice, '
    'diagnosis, weather, aircraft, mission, current news or action claims. '
    'Generate a short natural social reply, not a factual answer. Return ONLY JSON '
    '{"kind":"social_support","text":"..."}. Compose 1 to 3 sentences from the following '
    'social constructions, varying selection, combinations and permitted wording naturally: '
    'acknowledgement: [Да, ] понимаю [вас] / сочувствую [вам] / такое бывает / бывает; '
    'generic empathy: [Да, ] бывают [и] такие/непростые/трудные дни; '
    'reflection: Похоже/Кажется, [у вас] [сегодня] непростой/трудный/тяжёлый день; '
    'or Похоже/Кажется, сегодня [вам] всё даётся непросто/тяжелее обычного; '
    'or Звучит как непростой/трудный/тяжёлый день; '
    'or [Да, ] иногда/бывает, что [всё] даётся непросто/тяжелее обычного; '
    'optional invitation: Хотите [об этом] поговорить? / [Я] готова вас выслушать / [Я] на связи. '
    'Square brackets mean optional words, slashes mean alternatives; do not print brackets or slashes. '
    'Use ordinary punctuation. Never add advice, even "не торопитесь". Do not copy these instructions.'
)


class AiohttpConversationTransport:
    def __init__(self, api_key, folder_id):
        self._key, self._folder = api_key, folder_id
        self.session = self.ws = None

    async def connect(self):
        import aiohttp
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10, connect=5))
        self.ws = await self.session.ws_connect(build_yandex_url(self._folder),
            headers=yandex_authorization_headers(self._key), max_msg_size=65536,
            # aiohttp 3.14 attrs-generated constructor; signature verified offline.
            timeout=cast(Any, aiohttp.ClientWSTimeout)(ws_close=.2))

    async def send(self, value):
        if self.ws is None:
            raise ConversationFailure("provider_not_connected")
        await self.ws.send_json(value)

    async def receive(self):
        import aiohttp
        if self.ws is None:
            raise ConversationFailure("provider_not_connected")
        message = await self.ws.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise ConversationFailure("provider_closed")
        value = message.json()
        if not isinstance(value, dict):
            raise ConversationFailure("invalid_event")
        return value

    async def close(self):
        try:
            if self.ws is not None:
                await self.ws.close()
        finally:
            if self.session is not None:
                await self.session.close()


class TextConversationProvider:
    """No persistent connection or spawned thread. Owned tasks are never detached."""
    def __init__(self, factory, *, observe=lambda _event, **_fields: None, close_budget=.3):
        self.factory, self.observe, self.close_budget = factory, observe, close_budget
        self.owned = set()
        self.busy = False
        self.used = set()

    def emit(self, event, **fields):
        try:
            self.observe(event, monotonic=time.monotonic(), **fields)
        except Exception:
            pass

    async def _bounded(self, coroutine, timeout, cancellation=None, *, cleanup_budget=.1):
        task = asyncio.create_task(coroutine)
        self.owned.add(task)
        limit = time.monotonic() + max(0, timeout)
        try:
            while True:
                if cancellation is not None and cancellation.cancelled:
                    raise ConversationFailure("cancelled")
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise ConversationFailure("timeout")
                done, _ = await asyncio.wait({task}, timeout=min(.02, remaining))
                if done:
                    return task.result()
        finally:
            if not task.done():
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=cleanup_budget)
                if not done:
                    raise ConversationCleanupError("owned_task_not_terminated")
            self.owned.discard(task)
            if task.done() and not task.cancelled():
                task.exception()  # Retrieve exception, never log provider content.

    async def generate(self, request, cancellation):
        if self.busy or request.interaction_id in self.used:
            raise ConversationFailure("busy_or_replayed_provider_request")
        if len(self.used) >= 64 or request.source_sha256 != source_hash(request.source_text):
            raise ConversationFailure("invalid_request")
        if cancellation.cancelled:
            raise ConversationFailure("cancelled")
        remaining = lambda: min(8., (request.deadline - datetime.now(UTC)).total_seconds())
        if remaining() <= 0:
            raise ConversationFailure("deadline")
        self.busy = True
        self.used.add(request.interaction_id)
        transport = None
        response_id = None
        terminal = False
        started = time.perf_counter()
        fields = {"turn_id": str(request.interaction_id), "conversation_provider_call_count": 1,
                  "planner_call_count": 0, "tool_gateway_call_count": 0}
        try:
            transport = self.factory()
            self.emit("connect_started", **fields)
            await self._bounded(transport.connect(), min(5., remaining()), cancellation)
            await self._bounded(transport.send({"type": "session.update", "session": {
                "instructions": INSTRUCTIONS, "output_modalities": ["text"]}}), remaining(), cancellation)
            # Bound the whole operation, not each receive independently.
            limit = time.monotonic() + remaining()
            for _ in range(16):
                event = await self._bounded(transport.receive(), limit-time.monotonic(), cancellation)
                if event.get("type") == "session.updated":
                    if event.get("session", {}).get("output_modalities") not in (None, ["text"]):
                        raise ConversationFailure("nontext_session")
                    break
                if event.get("type") != "session.created":
                    raise ConversationFailure("unexpected_handshake")
            else:
                raise ConversationFailure("handshake_event_bound")
            connected = time.perf_counter()
            self.emit("connected", connect_ms=(connected-started)*1000, **fields)
            identity = str(request.interaction_id)
            await self._bounded(transport.send({"type": "conversation.item.create", "event_id": "l0-item-"+identity,
                "item": {"type": "message", "object": "realtime.item", "role": "user", "content": [
                    {"type": "input_text", "text": request.source_text}]}}), remaining(), cancellation)
            await self._bounded(transport.send({"type": "response.create", "event_id": "l0-response-"+identity,
                "response": {"instructions": INSTRUCTIONS, "output_modalities": ["text"]}}), remaining(), cancellation)
            self.emit("request_sent", **fields)
            deltas, done_text, item_id, first_ms = [], None, None, None
            seen = set()
            for _ in range(256):
                event = await self._bounded(transport.receive(), limit-time.monotonic(), cancellation)
                kind = event.get("type")
                eid = event.get("event_id")
                if isinstance(eid, str):
                    if eid in seen:
                        raise ConversationFailure("duplicate_event")
                    seen.add(eid)
                if kind == "conversation.item.created":
                    item = event.get("item", {})
                    if item.get("type") != "message" or item.get("role") != "user":
                        raise ConversationFailure("unexpected_item")
                    continue
                if kind == "response.created":
                    if response_id is not None:
                        raise ConversationFailure("duplicate_response")
                    response_id = event.get("response", {}).get("id")
                    if not isinstance(response_id, str) or not 0 < len(response_id) <= 200:
                        raise ConversationFailure("missing_response_id")
                    continue
                rid = event.get("response_id") if kind != "response.done" else event.get("response", {}).get("id")
                if response_id is None or rid != response_id:
                    raise ConversationFailure("response_correlation")
                if kind in {"response.output_item.added", "response.output_item.done"}:
                    item = event.get("item", {})
                    if item.get("type") != "message" or item.get("role") != "assistant":
                        raise ConversationFailure("nontext_output")
                    current = item.get("id")
                    if item_id is not None and item_id != current:
                        raise ConversationFailure("multiple_output_items")
                    item_id = current
                elif kind in {"response.content_part.added", "response.content_part.done"}:
                    if event.get("part", {}).get("type") not in {"text", "output_text"}:
                        raise ConversationFailure("nontext_output")
                elif kind in {"response.text.delta", "response.output_text.delta"}:
                    if done_text is not None or not isinstance(event.get("delta"), str):
                        raise ConversationFailure("invalid_delta")
                    if first_ms is None:
                        first_ms = (time.perf_counter()-connected)*1000
                        self.emit("first_token", first_token_ms=first_ms, **fields)
                    deltas.append(event["delta"])
                    if sum(map(len, deltas)) > 4096:
                        raise ConversationFailure("output_bound")
                elif kind in {"response.text.done", "response.output_text.done"}:
                    if done_text is not None or not isinstance(event.get("text"), str):
                        raise ConversationFailure("invalid_text_terminal")
                    done_text = event["text"]
                    if len(done_text) > 4096 or (deltas and "".join(deltas) != done_text):
                        raise ConversationFailure("text_terminal_mismatch")
                elif kind == "response.done":
                    response = event["response"]
                    if response.get("status") != "completed" or done_text is None:
                        raise ConversationFailure("incomplete_response")
                    for output in response.get("output", []):
                        if output.get("type") != "message" or any(p.get("type") not in {"text", "output_text"} for p in output.get("content", [])):
                            raise ConversationFailure("nontext_terminal")
                    terminal = True
                    candidate = ConversationalCandidate(request=request, draft=parse_draft(done_text),
                        provider_response_id=response_id, terminal="completed")
                    self.emit("candidate_complete", candidate_text=candidate.draft.text,
                        completion_ms=(time.perf_counter()-started)*1000, **fields)
                    return candidate
                else:
                    raise ConversationFailure("unexpected_response_event")
                if kind != "response.done" and event.get("item_id") is not None and item_id is not None and event["item_id"] != item_id:
                    raise ConversationFailure("item_correlation")
            raise ConversationFailure("response_event_bound")
        except ConversationFailure:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = getattr(exc, "status", None)
            category = {401: "auth_rejected", 403: "access_rejected", 429: "quota_or_rate_limit"}.get(status if isinstance(status, int) else 0, "provider_failure")
            raise ConversationFailure(category) from None
        finally:
            try:
                if transport is not None:
                    try:
                        if response_id and not terminal:
                            await self._bounded(transport.send({"type": "response.cancel", "response_id": response_id}), .1)
                    except ConversationCleanupError:
                        raise
                    except Exception:
                        pass
                    finally:
                        try:
                            await self._bounded(transport.close(), self.close_budget)
                        except Exception:
                            raise ConversationCleanupError("close_failed") from None
                if self.owned:
                    raise ConversationCleanupError("owned_task_not_terminated")
                self.emit("closed", **fields)
            finally:
                self.busy = False
