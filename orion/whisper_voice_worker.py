from __future__ import annotations
import json, os, re, subprocess, sys, urllib.error, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from orion.audio_device_config import audio_device_config
from orion.native_wasapi_player import NativeWasapiPlayer
from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.whisper_cpp_stt import configured_threads, stt_root, whisper_model_path
from orion.windows_sapi_backend import WindowsSapiBackend
ANSI_RE=re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]"); CORE_URL=os.environ.get("ORION_CORE_BASE_URL","http://127.0.0.1:8000").rstrip("/"); VOICE_ENDPOINT="/v1/voice/text"
@dataclass(frozen=True)
class VoiceBridgeReply: heard:str; reply:str; matched:bool; tts_requested:bool
def _state_path(): return Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"voice"/"state.json"
def _write_state(state,*,heard="",reply="",error=""):
 p=_state_path(); p.parent.mkdir(parents=True,exist_ok=True); payload={"state":state,"heard":heard,"reply":reply,"error":error,"updated_at":datetime.now(timezone.utc).isoformat()}; t=p.with_suffix(".tmp"); t.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); t.replace(p)
def whisper_stream_path()->Path:
 override=os.environ.get("ORION_WHISPER_STREAM")
 if override:return Path(override).expanduser().resolve()
 if getattr(sys,"frozen",False):
  exe=Path(sys.executable).resolve(); bundled=exe.parent/"whisper"/"whisper-stream.exe"
  if bundled.is_file(): return bundled
 name="whisper-stream.exe" if os.name=="nt" else "whisper-stream"; return stt_root()/name
def _normalize_transcript_line(line):
 text=ANSI_RE.sub("",line).strip()
 if not text:return ""
 if text.casefold().startswith(("whisper_","ggml_","main:","system_info:","init:","capture:","processing","[start speaking]")):return ""
 if text.startswith("[") and "]" in text and "-->" in text:text=text.split("]",1)[-1].strip()
 return " ".join(text.split())
def _post_text(text,*,core_url=CORE_URL,timeout=5.0):
 body=json.dumps({"text":text,"source":"whisper","language":"ru"},ensure_ascii=False).encode(); req=urllib.request.Request(core_url+VOICE_ENDPOINT,data=body,headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=timeout) as r: payload=json.loads(r.read().decode())
 except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc: raise RuntimeError(f"ORION Core voice bridge unavailable: {exc}") from exc
 return VoiceBridgeReply(str(payload.get("heard",text)),str(payload.get("reply","")),bool(payload.get("matched",False)),bool(payload.get("tts_requested",False)))
def _speak(reply):
 state=audio_device_config.state(); output=state.resolved_output
 if output is None:raise RuntimeError("ORION Voice has no resolved Windows output endpoint")
 spool=Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"voice"/"tts"; backend=WindowsSapiBackend(spool_dir=str(spool)); req=AudioRenderRequest(command_id=f"voice-{uuid4()}",text=reply,agent=VoiceAgent.SYSTEM,profile=VoiceProfile(profile_id="voice_v01_ru",locale="ru-RU",persona="orion"),backend=TtsBackend.WINDOWS_SAPI,output_device=output.device_id); rendered=backend.render(req)
 if not rendered.accepted or not rendered.output_path:raise RuntimeError(rendered.message)
 NativeWasapiPlayer().play(Path(rendered.output_path),output)
def build_stream_command():
 stream=whisper_stream_path(); model=whisper_model_path()
 if not stream.is_file():raise RuntimeError(f"Whisper live microphone component is missing: {stream}")
 if not model.is_file():raise RuntimeError(f"Whisper model is missing: {model}")
 return [str(stream),"--model",str(model),"--threads",str(configured_threads()),"--language","ru","--step","0","--length","8000","--keep","0","--vad-thold","0.60","--freq-thold","100.0","--no-gpu"]
def run_forever(*,core_url=CORE_URL):
 try:
  command=build_stream_command(); _write_state("READY"); process=subprocess.Popen(command,cwd=str(whisper_stream_path().parent),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  if process.stdout is None:raise RuntimeError("Whisper stream stdout is unavailable")
  _write_state("LISTENING"); last=""
  try:
   for raw in process.stdout:
    text=_normalize_transcript_line(raw)
    if not text or text.casefold()==last.casefold():continue
    last=text; _write_state("HEARD",heard=text); bridge=_post_text(text,core_url=core_url); _write_state("CORE_REPLY",heard=bridge.heard,reply=bridge.reply)
    if bridge.tts_requested and bridge.reply:_write_state("SPEAKING",heard=bridge.heard,reply=bridge.reply); _speak(bridge.reply)
    _write_state("LISTENING",heard=bridge.heard,reply=bridge.reply)
  finally:
   if process.poll() is None:process.terminate()
  return int(process.wait())
 except Exception as exc:_write_state("ERROR",error=f"{type(exc).__name__}: {exc}"); raise
def main():return run_forever()
if __name__=="__main__":raise SystemExit(main())
