"""Explicitly authorized bounded text-only probe; no audio/Core/radio start."""
import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

from orion.conversational_core import ConversationalCore
from orion.conversational_contracts import ConversationFailure
from orion.yandex_realtime_text_conversation import AiohttpConversationTransport, TextConversationProvider
from orion.windows_credentials import default_voice_credential_store, VoiceCredential
from orion.launcher_cloud_voice_sections import CloudVoiceConfigStore
from orion.planner import PlannerCancellationToken

INPUTS = ["Что-то сегодня полёт тяжело идёт.", "Сегодня как-то непросто летится.", "Что-то я сегодня не в форме."]

async def main():
    key = default_voice_credential_store().load(VoiceCredential.YANDEX_API_KEY)
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR", str(Path(os.environ["LOCALAPPDATA"])/"ORION"/"runtime")))
    folder = CloudVoiceConfigStore(runtime).load().yandex_folder_id
    report = {"time":datetime.now(UTC).isoformat(), "credential_present":bool(key), "folder_present":bool(folder),
              "audio_calls":0,"srs_calls":0,"planner_calls":0,"tool_gateway_calls":0,"turns":[]}
    if not key or not folder:
        report["status"] = "configuration_missing"; return report
    for index, text in enumerate(INPUTS + ["Что-то сегодня всё идёт тяжеловато."]):
        cancel = index == 3
        token = PlannerCancellationToken()
        core = ConversationalCore()
        request = core.request(SimpleNamespace(text=text,input_language="ru-RU",interaction_id=uuid4()))
        trace, instances = [], []
        def observe(event, **fields):
            trace.append({"event":event, **fields})
            if cancel and event == "first_token": token.cancel()
        class Transport(AiohttpConversationTransport):
            async def receive(self):
                value = await super().receive()
                # Event names only; NEVER provider bodies, headers, error details.
                kind = value.get("type")
                trace.append({"wire_event_type":kind if isinstance(kind,str) and len(kind)<80 else "invalid"})
                return value
        def factory():
            instance = Transport(key,folder); instances.append(instance); return instance
        provider = TextConversationProvider(factory,observe=observe)
        turn = {"input":text,"turn_id":str(request.interaction_id),"cancel_probe":cancel}
        started = time.monotonic()
        try:
            candidate = await provider.generate(request,token)
            turn["candidate"] = candidate.draft.text
            try:
                final = core.admit(candidate)
                turn.update(admission="accepted",finalized_text=final.text)
            except ConversationFailure:
                turn["admission"] = "rejected"
            turn["status"] = "completed"
        except ConversationFailure as exc:
            turn["status"] = "cancelled" if str(exc) == "cancelled" else "failed"
            turn["failure_category"] = str(exc)
        except Exception as exc:
            turn.update(status="failed",failure_category=type(exc).__name__)
        turn.update(elapsed_ms=(time.monotonic()-started)*1000,events=trace,owned_tasks=len(provider.owned),
            connections=len(instances),session_closed=bool(instances and instances[0].session and instances[0].session.closed),
            websocket_closed=bool(instances and instances[0].ws and instances[0].ws.closed))
        report["turns"].append(turn)
        if turn["status"] == "failed" or provider.owned:
            report["status"] = "FAILED_STOP_NO_BUILD"; return report
    accepted = [x.get("finalized_text") for x in report["turns"] if x.get("admission") == "accepted"]
    report["status"] = "PASS" if (len(set(accepted)) >= 2 and report["turns"][-1]["status"] == "cancelled"
        and all(x["session_closed"] and x["websocket_closed"] for x in report["turns"])) else "FAILED_STOP_NO_BUILD"
    return report

if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()),ensure_ascii=False,indent=2))
