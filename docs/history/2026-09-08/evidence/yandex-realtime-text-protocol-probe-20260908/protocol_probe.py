"""One explicitly authorized diagnostic session. Never imports voice runtime."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(r"C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation")
OUT = Path(__file__).resolve().parent
HEAD = "dca668d530dc6cbc4de05064400b22c2216ada3f"
TEXT = "Что-то сегодня полёт тяжело идёт."
INSTRUCTIONS = "Respond briefly in Russian to the user's subjective remark. Return text only. No tools, factual claims or operational advice."
DEADLINE = 15.0
CAP_FIELDS = ("id", "type", "object", "model", "modalities", "output_modalities",
              "input_audio_format", "output_audio_format", "audio", "voice",
              "turn_detection", "tools", "tool_choice", "instructions", "version",
              "protocol_version", "api_version")
FORBIDDEN_KEYS = re.compile(r"authorization|cookie|secret|token|api.?key|password|instructions|prompt|history|messages", re.I)


def json_type(value):
    if value is None: return "NULL"
    if isinstance(value, bool): return "BOOLEAN"
    if isinstance(value, str): return "STRING"
    if isinstance(value, list): return "ARRAY"
    if isinstance(value, dict): return "OBJECT"
    if isinstance(value, (int, float)): return "NUMBER"
    return "OTHER"


class Safe:
    def __init__(self, secrets=()): self.secrets = tuple(x for x in secrets if x)
    def text(self, value):
        if not isinstance(value, str): return value
        for secret in self.secrets: value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(?:Api-Key|Bearer)\s+[^\s\";,]+", "[REDACTED_AUTH]", value)
        return value
    def value(self, value, depth=0):
        if depth > 10: raise ValueError("capability_depth_bound")
        if isinstance(value, str):
            if len(value) > 16384: raise ValueError("safe_string_bound")
            return self.text(value)
        if isinstance(value, list):
            if len(value) > 128: raise ValueError("safe_array_bound")
            return [self.value(x, depth+1) for x in value]
        if isinstance(value, dict):
            if len(value) > 128: raise ValueError("safe_object_bound")
            return {self.text(k): ({"present": True, "type": json_type(v), "value_redacted": True}
                    if FORBIDDEN_KEYS.search(k) else self.value(v, depth+1)) for k,v in value.items()}
        return value


def capability(event, safe):
    session = event.get("session")
    result = {"session_present": "session" in event, "session_type": json_type(session), "fields": {}}
    for key in CAP_FIELDS:
        present = isinstance(session, dict) and key in session
        field = {"present": present, "type": json_type(session[key]) if present else "MISSING"}
        if present and key != "instructions": field["value"] = safe.value(session[key])
        if present and key == "instructions": field["value_redacted"] = True
        result["fields"][key] = field
    if isinstance(session, dict): result["returned_field_names"] = sorted(safe.text(k) for k in session)
    return result


def event_class(event):
    kind = str(event.get("type", ""))
    subtype = str(event.get("item", {}).get("type", "")) if isinstance(event.get("item"), dict) else ""
    part = str(event.get("part", {}).get("type", "")) if isinstance(event.get("part"), dict) else ""
    output = event.get("response", {}).get("output", []) if isinstance(event.get("response"), dict) else []
    subtypes = [subtype] + [str(x.get("type", "")) for x in output if isinstance(x,dict)]
    parts = [part] + [str(p.get("type", "")) for x in output if isinstance(x,dict)
                     for p in x.get("content", []) if isinstance(p,dict)]
    if "function" in kind or "tool" in kind or any("function" in x or "tool" in x for x in subtypes): return "TOOL"
    if kind.startswith("response.") and ("audio" in kind or any("audio" in x for x in parts)): return "AUDIO"
    if "speech_" in kind or kind.startswith("input_audio") or "input_audio_transcription" in kind: return "VAD_SPEECH"
    if "text" in kind: return "TEXT"
    if kind.startswith("session."): return "SESSION"
    if kind == "error": return "ERROR"
    return "OTHER"


def payloads(identity):
    return [
        {"type":"session.update", "event_id": "probe-session-"+identity,
         "session":{"instructions":INSTRUCTIONS,"output_modalities":["text"]}},
        {"type":"conversation.item.create", "event_id":"probe-input-"+identity,
         "item":{"type":"message","object":"realtime.item",
                 "role":"user","content":[{"type":"input_text","text":TEXT}]}},
        {"type":"response.create", "event_id":"probe-response-"+identity,
         "response":{"instructions":INSTRUCTIONS,"output_modalities":["text"]}},
    ]


class Trace:
    def __init__(self, safe):
        self.safe = safe
        self.events = []
        self.counts = {k:0 for k in ("TEXT","AUDIO","TOOL","VAD_SPEECH","SESSION","ERROR","OTHER")}
        self.deltas = []
        self.terminals = []
        self.response_id = None
        self.response_terminal = None
    def receive(self, event, now):
        if not isinstance(event,dict) or not isinstance(event.get("type"),str): raise ValueError("invalid_event_schema")
        if len(self.events) >= 512: raise ValueError("event_count_bound")
        category = event_class(event)
        self.counts[category] += 1
        row = {"type":event["type"],"class":category,"monotonic":now}
        for key in ("event_id","response_id","item_id","output_index","content_index"):
            if key in event: row[key] = self.safe.value(event[key])
        kind = event["type"]
        if kind in ("response.text.delta","response.output_text.delta"):
            delta = event.get("delta")
            if not isinstance(delta,str): raise ValueError("invalid_text_delta")
            if sum(map(len,self.deltas))+len(delta)>16384: raise ValueError("text_bound")
            self.deltas.append(delta)
            row["delta"] = self.safe.text(delta)
        if kind in ("response.text.done","response.output_text.done"):
            row["text_fields"] = {k:{"type":json_type(event[k]),"value":self.safe.value(event[k])}
                                  for k in ("text","transcript") if k in event}
            raw = event.get("text",event.get("transcript"))
            if not isinstance(raw,str): raise ValueError("missing_terminal_text")
            self.terminals.append(raw)
        if kind in ("session.created","session.updated"): row["capability"] = capability(event,self.safe)
        if kind == "conversation.item.created":
            item = event.get("item",{})
            row["item"] = {k:self.safe.value(item[k]) for k in ("id","object","type","role","status") if k in item}
            row["item"]["content"] = [{"type":p.get("type"),
                **({"text":self.safe.text(p["text"])} if isinstance(p.get("text"),str) else {})}
                for p in item.get("content",[]) if isinstance(p,dict)]
        if kind in ("response.created","response.done"):
            response = event.get("response",{})
            row["response"] = {k:self.safe.value(response[k]) for k in ("id","object","status","modalities","output_modalities") if k in response}
            if kind == "response.created":
                if self.response_id is not None: raise ValueError("multiple_responses")
                self.response_id = response.get("id")
            else:
                self.response_terminal = row["response"]
                row["output_shape"] = [{"type":x.get("type"),"id":self.safe.text(x.get("id")),
                  "role":x.get("role"),"content":[{"type":p.get("type"),
                    **({"text":self.safe.text(p["text"])} if isinstance(p.get("text"),str) else {})}
                    for p in x.get("content",[]) if isinstance(p,dict)]}
                  for x in response.get("output",[]) if isinstance(x,dict)]
        if category == "ERROR":
            err = event.get("error",{})
            row["error"] = {k:self.safe.text(str(err[k]))[:512] for k in ("type","code","message","param","event_id") if k in err}
        self.events.append(row)
        return row


def fingerprint():
    paths = subprocess.check_output(["git","ls-files","-co","--exclude-standard"],cwd=ROOT,text=True).splitlines()
    hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if (ROOT/p).is_file()}
    runtime = Path(os.environ.get("ORION_RUNTIME_DIR",str(Path(os.environ["LOCALAPPDATA"])/"ORION"/"runtime")))
    config = runtime/"cloud-voice.json"
    return {"head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "status":subprocess.check_output(["git","status","--porcelain=v1"],cwd=ROOT,text=True),
            "files":hashes,"config_sha256":hashlib.sha256(config.read_bytes()).hexdigest() if config.exists() else None}


async def run(report, safe, key, folder):
    import aiohttp
    from orion.yandex_realtime_provider import build_yandex_url, yandex_authorization_headers
    trace = Trace(safe)
    report["events"] = trace.events
    report["event_counts"] = trace.counts
    session = websocket = None
    stage = "connect"
    initial_tasks = set(asyncio.all_tasks())
    stamps = report["timestamps"]
    try:
        async with asyncio.timeout(DEADLINE):
            stamps["connect_started"] = time.monotonic()
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=DEADLINE,connect=5))
            report["connection_attempts"] = 1
            websocket = await session.ws_connect(build_yandex_url(folder),headers=yandex_authorization_headers(key),
                       max_msg_size=131072,timeout=aiohttp.ClientWSTimeout(ws_close=.3),heartbeat=None)
            stamps["connected"] = time.monotonic()
            async def receive():
                msg = await websocket.receive()
                if msg.type != aiohttp.WSMsgType.TEXT: raise ValueError("websocket_closed_or_non_json_frame")
                row = trace.receive(msg.json(),time.monotonic())
                if row["class"] == "TOOL": raise ValueError("unexpected_tool_event")
                if row["class"] == "ERROR":
                    report["provider_error"] = row.get("error")
                    raise ValueError("explicit_provider_error")
                return row
            async def wait_for(kind):
                for _ in range(32):
                    row = await receive()
                    if row["type"] == kind: return row
                raise ValueError("boundary_event_bound")
            stage = "session_created"
            row = await wait_for("session.created")
            report["provider_session_created"] = True
            stamps[stage] = row["monotonic"]
            events = payloads(report["probe_id"])
            async def send(index, name):
                stamps[name] = time.monotonic()
                # These are local constant synthetic payloads, not provider bodies.
                report["outbound"].append({"monotonic":stamps[name],"payload":safe.value(events[index])})
                # Preserve our known fixed instructions in outbound evidence.
                if index in (0,2): report["outbound"][-1]["payload"]["session" if index==0 else "response"]["instructions"] = INSTRUCTIONS
                await websocket.send_json(events[index])
            stage = "session_update"
            await send(0,"session_update_sent")
            row = await wait_for("session.updated")
            stamps["session_updated"] = row["monotonic"]
            stage = "user_item"
            await send(1,"user_item_sent")
            row = await wait_for("conversation.item.created")
            item = row.get("item",{})
            if item.get("role") != "user" or item.get("type") != "message":
                raise ValueError("user_item_ack_mismatch")
            contents=item.get("content",[])
            if len(contents)!=1 or contents[0].get("type") not in ("input_text","text") or contents[0].get("text") != TEXT:
                raise ValueError("user_text_ack_mismatch")
            report["user_item_accepted"] = True
            stamps["user_item_accepted"] = row["monotonic"]
            stage = "response"
            await send(2,"response_create_sent")
            while True:
                row = await receive()
                if row["type"] in ("response.text.delta","response.output_text.delta"):
                    stamps.setdefault("first_text",row["monotonic"])
                if row["type"] in ("response.text.done","response.output_text.done"): stamps["text_complete"] = row["monotonic"]
                if row["type"] == "response.done":
                    stamps["response_terminal"] = row["monotonic"]
                    if row["response"].get("status") != "completed": raise ValueError("response_not_completed")
                    if not trace.response_id or row["response"].get("id") != trace.response_id: raise ValueError("response_identity_mismatch")
                    if not trace.terminals or not trace.terminals[-1]: raise ValueError("no_terminal_text")
                    if trace.deltas and "".join(trace.deltas)!=trace.terminals[-1]: raise ValueError("text_terminal_mismatch")
                    report["text_raw"] = safe.text(trace.terminals[-1])
                    report["text_redacted"] = report["text_raw"] != trace.terminals[-1]
                    report["verdict"] = "PASS" if not any(trace.counts[k] for k in ("AUDIO","TOOL","VAD_SPEECH")) else "FAIL_UNEXPECTED_OUTPUT"
                    break
    except BaseException as exc:
        report["verdict"] = "FAIL"
        report["failure"] = {"stage":stage,"exception_type":type(exc).__name__,
            "category":str(exc) if isinstance(exc,ValueError) and re.fullmatch(r"[a-z_]+",str(exc)) else "deadline" if isinstance(exc,TimeoutError) else "transport_failure",
            "http_status":getattr(exc,"status",None)}
    finally:
        stamps["cleanup_started"] = time.monotonic()
        close_error = None
        try:
            async with asyncio.timeout(1.0):
                try:
                    if websocket is not None: await websocket.close()
                finally:
                    if session is not None: await session.close()
                await asyncio.sleep(.05)
        except BaseException as exc: close_error = type(exc).__name__
        remaining = [t for t in asyncio.all_tasks() if t not in initial_tasks and not t.done()]
        report["cleanup"] = {"websocket_created":websocket is not None,"websocket_closed":websocket.closed if websocket is not None else None,
            "client_session_created":session is not None,"client_session_closed":session.closed if session is not None else None,
            "remaining_async_tasks":len(remaining),"close_error":close_error,
            "remote_session_destruction":"NOT_OBSERVABLE; client websocket closed only"}
        if close_error or remaining or (session is not None and not session.closed) or (websocket is not None and not websocket.closed): report["verdict"]="FAIL_CLEANUP"
        stamps["cleanup_complete"] = time.monotonic()


def main():
    before=fingerprint()
    if before["head"] != HEAD: raise SystemExit("HEAD mismatch; no provider call")
    # Exclusive file creation is a durable one-attempt latch, never overwritten.
    with (OUT/"attempt-latch.json").open("x",encoding="utf-8") as f:
        json.dump({"time":datetime.now(timezone.utc).isoformat(),"head":HEAD},f)
    sys.path.insert(0,str(ROOT))
    from orion.windows_credentials import default_voice_credential_store, VoiceCredential
    from orion.launcher_cloud_voice_sections import CloudVoiceConfigStore
    key=default_voice_credential_store().load(VoiceCredential.YANDEX_API_KEY)
    runtime=Path(os.environ.get("ORION_RUNTIME_DIR",str(Path(os.environ["LOCALAPPDATA"])/"ORION"/"runtime")))
    folder=CloudVoiceConfigStore(runtime).load().yandex_folder_id
    safe=Safe((key,folder))
    report={"probe_id":uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),"head":HEAD,
      "endpoint":"wss://ai.api.cloud.yandex.net/v1/realtime","model":"speech-realtime-260528",
      "deadline_seconds":DEADLINE,"cleanup_bound_seconds":1,"outbound":[],"timestamps":{},
      "provider_session_created":False,"user_item_accepted":False,"connection_attempts":0,
      "audio_input_sent":False,"audio_decoded":False,"audio_played":False,
      "planner_calls":0,"tool_gateway_calls":0,"dcs_calls":0,"srs_calls":0,"tts_calls":0,
      "retries":0,"reconnects":0}
    threads_before={t.ident for t in threading.enumerate()}
    if not key or not folder: report["verdict"]="FAIL_CONFIG_MISSING"
    else: asyncio.run(run(report,safe,key,folder))
    report.setdefault("cleanup",{})["remaining_new_threads"]=[t.name for t in threading.enumerate() if t.ident not in threads_before]
    if report["cleanup"]["remaining_new_threads"]: report["verdict"]="FAIL_CLEANUP"
    after=fingerprint()
    report["source_audit"]={"before":before,"after":after,"unchanged":before==after}
    if before!=after: report["verdict"]="FAIL_SOURCE_CHANGED"
    rendered=json.dumps(report,ensure_ascii=False,indent=2)
    if any(x and x in rendered for x in (key,folder)): raise SystemExit("Sanitization failed; report not written")
    with (OUT/"provider-protocol-result.json").open("x",encoding="utf-8") as f: f.write(rendered)
    print(json.dumps({"verdict":report["verdict"],"provider_session_created":report["provider_session_created"],
       "result_path":str(OUT/"provider-protocol-result.json")},ensure_ascii=False))


if __name__=="__main__": main()
