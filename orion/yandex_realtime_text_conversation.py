"""Request-scoped text-only adapter. No audio, VAD, DCS or tool ownership.

Adapted from 8182e892 Realtime text protocol/assembler, NOT its presenter owner.
Every successful turn closes its own connection, including provider history.
"""
import asyncio
from datetime import UTC, datetime
import time
from typing import Any, cast

from orion.conversational_contracts import ConversationalCandidate, ConversationCleanupError, ConversationFailure
from orion.conversational_core import parse_draft, source_hash
from orion.yandex_realtime_provider import build_yandex_url, yandex_authorization_headers


INSTRUCTIONS = (
    'Respond to this subjective difficult-day remark in Russian. No tools, facts, aviation advice, '
    'diagnosis, weather, aircraft, mission, current news or action claims. '
    'Generate a short natural social reply, not a factual answer. Return ONLY JSON '
    '{"kind":"social_support","text":"..."}. RETURN ONLY THE JSON OBJECT. '
    'DO NOT USE MARKDOWN OR CODE FENCES. DO NOT ADD EXPLANATION BEFORE OR AFTER THE JSON. '
    'Compose 1 to 3 sentences from the following '
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


def _identifier(value):
    if not isinstance(value, str) or not 0 < len(value) <= 200:
        raise ConversationFailure("invalid_identifier")
    return value


def _capabilities(value):
    if (not isinstance(value, list) or not value or any(type(v) is not str for v in value)
        or len(value) != len(set(value)) or "text" not in value or set(value) - {"text", "audio"}):
        raise ConversationFailure("invalid_text_capability")


def _no_audio_payload(value, path: tuple[str, ...] = (), *, response_metadata=False):
    """Inspect payload slots, not config containers; never decode audio.

    Only response.created/done declare /response/audio as configuration.
    Its optional fields may be absent/null; content/item audio is NOT exempt.
    Session configuration remains handled separately by the handshake parser.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "audio" and response_metadata and path == ("response",):
                if child is not None and not isinstance(child, dict):
                    raise ConversationFailure("invalid_response_audio_config")
            elif key == "audio" and child is not None and child != "":
                raise ConversationFailure("audio_payload")
            if key in {"tools", "tool_calls", "function_call"} and child not in (None, []):
                raise ConversationFailure("tool_output")
            _no_audio_payload(child, path + (key,), response_metadata=response_metadata)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _no_audio_payload(child, path + (str(index),), response_metadata=response_metadata)


class _TextOperation:
    """Bounded single-response event contract; no connection/authority ownership.

    DT403405: multimodal capabilities and null audio envelopes are not payload.
    Only output_text.done supplies final text. Other strings are comparisons.
    """
    def __init__(self, source_text):
        self.source_text = source_text
        self.session_id = self.response_id = self.item_id = self.user_id = None
        self.updated = self.terminal = False
        self.text = ""
        self.done_text = None
        self.seen = set()
        self.once = set()
        self.parts = {}
        self.representations = []
        self.assistant_created = 0
        self.assistant_was_empty = False

    def _once(self, key):
        if key in self.once:
            raise ConversationFailure("duplicate_terminal_or_structure")
        self.once.add(key)

    def _part(self, part, *, terminal=False):
        if isinstance(part, dict) and part.get("type") == "audio":
            # Yandex OutputAudioPart schema + observed `audio` alias, DT403405.
            # Optional audio/transcript; identity/index belong to the event.
            for field, value in part.items():
                if field == "type":
                    continue
                if field == "audio":
                    if value is not None:
                        raise ConversationFailure("invalid_structural_audio")
                elif field == "transcript":
                    if value is not None and (not isinstance(value, str) or len(value) > 4096):
                        raise ConversationFailure("invalid_text_representation")
                else:
                    raise ConversationFailure("unknown_audio_part_field")
            # Comparison only; never accumulated text, terminal or candidate.
            transcript = part.get("transcript")
            if transcript:
                self.representations.append(transcript)
            return "audio"
        if not isinstance(part, dict) or part.get("type") not in {"text", "output_text", "output_audio"}:
            raise ConversationFailure("invalid_content_part")
        kind = "audio" if part["type"] == "output_audio" else "text"
        for key in ("text", "transcript"):
            if key in part and part[key] is not None:
                value = part[key]
                if not isinstance(value, str) or len(value) > 4096:
                    raise ConversationFailure("invalid_text_representation")
                if value or (terminal and kind == "text"):
                    self.representations.append(value)
        return kind

    def _item(self, item, *, terminal=False):
        if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
            raise ConversationFailure("unexpected_item")
        current = _identifier(item.get("id"))
        if current == self.user_id or (self.item_id is not None and current != self.item_id):
            raise ConversationFailure("item_correlation")
        self.item_id = current
        content = item.get("content")
        if not isinstance(content, list) or len(content) > 2:
            raise ConversationFailure("invalid_item_content")
        kinds = [self._part(part, terminal=terminal) for part in content]
        if len(kinds) != len(set(kinds)):
            raise ConversationFailure("duplicate_content")
        return content

    def _binding(self, event, kind):
        if event.get("item_id") != self.item_id or self.item_id is None:
            raise ConversationFailure("item_correlation")
        index = event.get("content_index")
        if type(index) is not int or index not in (0, 1):
            raise ConversationFailure("content_correlation")
        if (index in self.parts and self.parts[index] != kind
            or any(i != index and k == kind for i, k in self.parts.items())):
            raise ConversationFailure("content_correlation")
        self.parts[index] = kind

    def feed(self, event):
        if self.terminal:
            raise ConversationFailure("event_after_response_terminal")
        if not isinstance(event, dict):
            raise ConversationFailure("invalid_event")
        eid = _identifier(event.get("event_id"))
        if eid in self.seen:
            raise ConversationFailure("duplicate_event")
        self.seen.add(eid)
        if len(self.seen) > 272:
            raise ConversationFailure("event_bound")
        kind = event.get("type")
        if kind in {"response.output_audio.delta", "response.audio.delta"}:
            raise ConversationFailure("audio_delta")  # Even empty delta is forbidden.
        if kind in {"session.created", "session.updated"}:
            self._once(kind)
            if self.updated:
                raise ConversationFailure("unexpected_handshake")
            session = event.get("session")
            if not isinstance(session, dict):
                raise ConversationFailure("invalid_session")
            current = _identifier(session.get("id"))
            _capabilities(session.get("output_modalities"))
            _no_audio_payload({k: v for k, v in event.items() if k != "session"})
            _no_audio_payload({k: v for k, v in session.items() if k != "audio"})
            if "audio" in session:
                if not isinstance(session["audio"], dict):
                    raise ConversationFailure("invalid_session_audio_config")
                _no_audio_payload(session["audio"])
            if kind == "session.created":
                self.session_id = current
            elif self.session_id is None or current != self.session_id:
                raise ConversationFailure("session_correlation")
            else:
                self.updated = True
            return None
        if not self.updated:
            raise ConversationFailure("unexpected_handshake")
        _no_audio_payload(event, response_metadata=kind in {"response.created", "response.done"})
        if kind == "conversation.item.created":
            item = event.get("item")
            if not isinstance(item, dict):
                raise ConversationFailure("unexpected_item")
            if item.get("role") == "user":
                self._once("user_item")
                if self.response_id is not None or item.get("type") != "message" or item.get("content") != [
                    {"type": "input_text", "text": self.source_text}]:
                    raise ConversationFailure("user_item_correlation")
                self.user_id = _identifier(item.get("id"))
            else:
                if self.response_id is None or self.done_text is not None:
                    raise ConversationFailure("unexpected_item")
                content = self._item(item)
                self.assistant_created += 1
                if self.assistant_created > 2 or (self.assistant_created == 2 and (not content or not self.assistant_was_empty)):
                    raise ConversationFailure("unexpected_item")
                self.assistant_was_empty = not content
            return None
        if kind == "response.created":
            self._once(kind)
            response = event.get("response")
            if not self.user_id or not isinstance(response, dict) or response.get("status") != "in_progress":
                raise ConversationFailure("invalid_response")
            _capabilities(response.get("output_modalities"))
            if response.get("output") not in (None, []):
                raise ConversationFailure("unexpected_initial_output")
            self.response_id = _identifier(response.get("id"))
            return None
        response = event.get("response") if kind == "response.done" else None
        rid = response.get("id") if isinstance(response, dict) else event.get("response_id")
        if self.response_id is None or rid != self.response_id:
            raise ConversationFailure("response_correlation")
        if kind != "response.done" and (type(event.get("output_index")) is not int or event["output_index"] != 0):
            raise ConversationFailure("output_correlation")
        if kind in {"response.output_item.added", "response.output_item.done"}:
            self._once(kind)
            self._item(event.get("item"), terminal=kind.endswith("done"))
        elif kind in {"response.content_part.added", "response.content_part.done"}:
            part_kind = self._part(event.get("part"), terminal=kind.endswith("done"))
            self._binding(event, part_kind)
            self._once((kind, event["content_index"]))
        elif kind == "response.output_text.delta":
            self._binding(event, "text")
            if self.done_text is not None or not isinstance(event.get("delta"), str):
                raise ConversationFailure("invalid_delta")
            self.text += event["delta"]
            if len(self.text) > 4096:
                raise ConversationFailure("output_bound")
        elif kind == "response.output_text.done":
            self._binding(event, "text")
            self._once(kind)
            value = event.get("text")
            if not isinstance(value, str) or not value or len(value) > 4096 or self.text != value:
                raise ConversationFailure("text_terminal_mismatch")
            self.done_text = value
        elif kind in {"response.output_audio.done", "response.output_audio_transcript.done"}:
            self._binding(event, "audio")
            self._once(kind)
            self._part({"type": "output_audio", **{k: event[k] for k in ("text", "transcript") if k in event}})
        elif kind == "response.done":
            if not isinstance(response, dict) or response.get("status") != "completed" or self.done_text is None:
                raise ConversationFailure("incomplete_response")
            _capabilities(response.get("output_modalities"))
            output = response.get("output")
            if not isinstance(output, list) or len(output) != 1:
                raise ConversationFailure("invalid_terminal_output")
            self._item(output[0], terminal=True)
            if any(value != self.done_text for value in self.representations):
                raise ConversationFailure("text_terminal_mismatch")
            self.terminal = True
            return self.done_text
        else:
            raise ConversationFailure("unexpected_response_event")
        return None


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
            self.emit("connect_complete", **fields)
            await self._bounded(transport.send({"type": "session.update", "session": {
                "instructions": INSTRUCTIONS, "output_modalities": ["text"]}}), remaining(), cancellation)
            # Bound the whole operation, not each receive independently.
            limit = time.monotonic() + remaining()
            operation = _TextOperation(request.source_text)
            for _ in range(16):
                event = await self._bounded(transport.receive(), limit-time.monotonic(), cancellation)
                operation.feed(event)
                self.emit(event["type"], **fields)
                if operation.updated:
                    break
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
            first_ms = None
            for _ in range(256):
                event = await self._bounded(transport.receive(), limit-time.monotonic(), cancellation)
                kind = event.get("type")
                done_text = operation.feed(event)
                response_id = operation.response_id
                if cancellation.cancelled:
                    raise ConversationFailure("cancelled")
                if kind == "response.output_text.delta":
                    if first_ms is None:
                        first_ms = (time.perf_counter()-connected)*1000
                        self.emit("first_token", first_token_ms=first_ms, **fields)
                if kind == "response.output_text.done":
                    self.emit("text_complete", **fields)
                if done_text is not None:
                    if not isinstance(response_id, str) or not 0 < len(response_id) <= 200:
                        raise ConversationFailure("response_correlation")
                    terminal = True
                    candidate = ConversationalCandidate(request=request, draft=parse_draft(done_text),
                        provider_response_id=response_id, terminal="completed")
                    self.emit("candidate_complete", candidate_text=candidate.draft.text,
                        completion_ms=(time.perf_counter()-started)*1000, **fields)
                    return candidate
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
                if cancellation.cancelled:
                    raise ConversationFailure("cancelled")
            finally:
                self.busy = False
