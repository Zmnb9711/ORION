"""Preserved 2026-09-08 event ORDER, not a claimed raw-wire recording.

Source provider-protocol-result.json SHA256:
C45012C772FBB45D5B5B1C0B30135401548046D08A5127980B7A90A1088E6DAD.
Projection omitted part/item bodies, audio and transcript fields. Those are
explicitly reconstructed here with support DT403405 audio:null semantics.
Structured SocialDraft content is a synthetic variant, NOT the old response.
"""
import json

SOURCE = "Что-то сегодня полёт тяжело идёт."
HISTORICAL_DELTAS = [" Понимаю", ",", " бывает", " такое", ".", " Надеюсь",
                     ",", " дальше", " будет", " полег", "че", "!"]


def sequence(text="  Понимаю вас. Хотите об этом поговорить?\n", *, historical=False):
    body = ("".join(HISTORICAL_DELTAS) if historical else
            json.dumps({"kind": "social_support", "text": text}, ensure_ascii=False))
    deltas = HISTORICAL_DELTAS if historical else [body[i*len(body)//12:(i+1)*len(body)//12] for i in range(12)]
    session = {"id": "session-one", "type": "realtime", "object": "realtime.session",
               "output_modalities": ["text", "audio"], "tools": [],
               "audio": {"input": {"format": {"type": "audio/pcm", "rate": None}},
                         "output": {"voice": "kirill"}}}
    def item(content):
        return {"type": "message", "role": "assistant", "id": "item-one", "content": content}
    empty = [{"type": "output_text", "text": ""}, {"type": "output_audio", "audio": None}]
    terminal = [{"type": "output_audio", "audio": None, "transcript": body}]
    def event(kind, **fields):
        return {"type": "response."+kind, "response_id": "response-one", "output_index": 0, **fields}
    def part(kind, index, **fields):
        return event(kind, item_id="item-one", content_index=index, **fields)
    result = [
        {"type": "session.created", "session": dict(session)},
        {"type": "session.updated", "session": dict(session)},
        {"type": "conversation.item.created", "item": {"id": "user-one", "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": SOURCE}]}},
        {"type": "response.created", "response": {"id": "response-one", "status": "in_progress",
            "output_modalities": ["text", "audio"]}},
        {"type": "conversation.item.created", "item": item([])},
        {"type": "conversation.item.created", "item": item(empty)},
        event("output_item.added", item=item(empty)),
        part("content_part.added", 0, part=empty[0]),
        part("content_part.added", 1, part=empty[1]),
        *[part("output_text.delta", 0, delta=value) for value in deltas],
        part("content_part.done", 0, part={"type": "output_text", "text": body}),
        part("output_text.done", 0, text=body),
        part("content_part.done", 1, part=terminal[0]),
        part("output_audio.done", 1, audio=None),
        part("output_audio_transcript.done", 1, transcript=body),
        event("output_item.done", item=item(terminal)),
        {"type": "response.done", "response": {"id": "response-one", "status": "completed",
            "output_modalities": ["text", "audio"], "output": [item(terminal)]}},
    ]
    for index, value in enumerate(result):
        value["event_id"] = str(index)
    return result
