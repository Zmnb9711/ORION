from __future__ import annotations

import hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from orion.whisper_cpp_stt import WHISPER_MODEL_SHA1, WHISPER_MODEL_URL, configured_threads, whisper_model_path

ANSI_RE=re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CORE_URL=os.environ.get("ORION_CORE_BASE_URL","http://127.0.0.1:8000").rstrip("/"); VOICE_ENDPOINT="/v1/voice/text"
MIC_READY_MARKERS=("[Start speaking]","capture:","audio capture","SDL")
MIC_ERROR_MARKERS=("failed to open audio","failed to capture","no capture devices","no audio capture","sdl_geterror","audio device")
@dataclass(frozen=True)
class VoiceBridgeReply: heard:str; reply:str; matched:bool; tts_requested:bool

def _state_path(): return Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"voice"/"state.json"
def _write_state(state,*,heard="",reply="",error=""):
 p=_state_path();p.parent.mkdir(parents=True,exist_ok=True)
 payload=json.dumps({"state":state,"heard":heard,"reply":reply,"error":error,"updated_at":datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2)
 # Use a unique temp file so overlapping/retried writers never fight over state.tmp.
 q=p.with_name(f"{p.name}.{os.getpid()}.{uuid4().hex}.tmp")
 try:
  q.write_text(payload,encoding="utf-8")
  for attempt in range(8):
   try:
    os.replace(q,p);return
   except PermissionError:
    if attempt==7:break
    time.sleep(0.015*(attempt+1))
  # State publication is diagnostic/UI only. A transient Windows reader/AV lock
  # must never terminate Voice or abort a 1.5 GB model download.
  try:p.write_text(payload,encoding="utf-8")
  except OSError:pass
 finally:
  try:
   if q.exists():q.unlink()
  except OSError:pass
def _provision_progress(stage,completed,total): _write_state("PROVISIONING",error=(f"{stage}: {completed*100.0/total:.1f}% ({completed}/{total} bytes)" if total else f"{stage}: {completed} bytes"))
def whisper_stream_path():
 o=os.environ.get("ORION_WHISPER_STREAM")
 if o:return Path(o).expanduser().resolve()
 if getattr(sys,"frozen",False):
  p=Path(sys.executable).resolve().parent/"whisper"/"whisper-stream.exe"
  if p.is_file():return p
 return Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"stt"/"whisper.cpp"/("whisper-stream.exe" if os.name=="nt" else "whisper-stream")
def _file_hash(path,algorithm):
 d=hashlib.new(algorithm)
 with path.open("rb") as h:
  for c in iter(lambda:h.read(1024*1024),b""):d.update(c)
 return d.hexdigest()
def _model_ready():
 m=whisper_model_path();return m.is_file() and m.stat().st_size>100_000_000
def ensure_voice_model():
 m=whisper_model_path()
 if _model_ready():return m
 m.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix="orion-voice-model-") as t:
  x=Path(t)/m.name;r=urllib.request.Request(WHISPER_MODEL_URL,headers={"User-Agent":"ORION-DCS/0.2"})
  with urllib.request.urlopen(r,timeout=120) as response,x.open("wb") as out:
   z=response.headers.get("Content-Length")
   try:total=int(z) if z else None
   except ValueError:total=None
   n=0
   while True:
    c=response.read(1024*1024)
    if not c:break
    out.write(c);n+=len(c);_provision_progress("model",n,total)
  _write_state("PROVISIONING",error="model_verify");actual=_file_hash(x,"sha1")
  if actual!=WHISPER_MODEL_SHA1:raise RuntimeError(f"Whisper medium model checksum mismatch: {actual}")
  x.replace(m)
 return m
def _clean(line):return ANSI_RE.sub("",line).strip()
def _is_mic_ready(line):
 t=_clean(line).casefold();return any(x.casefold() in t for x in MIC_READY_MARKERS)
def _mic_error(line):
 t=_clean(line);return t if any(x in t.casefold() for x in MIC_ERROR_MARKERS) else ""
def _normalize_transcript_line(line):
 text=_clean(line)
 if not text:return ""
 if text.casefold().startswith(("whisper_","ggml_","main:","system_info:","init:","capture:","processing","[start speaking]")):return ""
 if text.startswith("[") and "]" in text and "-->" in text:text=text.split("]",1)[-1].strip()
 return " ".join(text.split())
def _post_text(text,*,core_url=CORE_URL,timeout=5.0):
 body=json.dumps({"text":text,"source":"whisper","language":"ru"},ensure_ascii=False).encode();req=urllib.request.Request(core_url+VOICE_ENDPOINT,data=body,headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=timeout) as r:p=json.loads(r.read().decode())
 except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e:raise RuntimeError(f"ORION Core voice bridge unavailable: {e}") from e
 return VoiceBridgeReply(str(p.get("heard",text)),str(p.get("reply","")),bool(p.get("matched",False)),bool(p.get("tts_requested",False)))
def _speak(reply):
 from orion.audio_device_config import audio_device_config
 from orion.native_wasapi_player import NativeWasapiPlayer
 from orion.tts_audio import AudioRenderRequest,TtsBackend,VoiceProfile
 from orion.voice_core import VoiceAgent
 from orion.windows_sapi_backend import WindowsSapiBackend
 output=audio_device_config.state().resolved_output
 if output is None:raise RuntimeError("ORION Voice has no resolved Windows output endpoint")
 backend=WindowsSapiBackend(spool_dir=str(Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"voice"/"tts"));request=AudioRenderRequest(command_id=f"voice-{uuid4()}",text=reply,agent=VoiceAgent.SYSTEM,profile=VoiceProfile(profile_id="voice_v01_ru",locale="ru-RU",persona="orion"),backend=TtsBackend.WINDOWS_SAPI,output_device=output.device_id);rendered=backend.render(request)
 if not rendered.accepted or not rendered.output_path:raise RuntimeError(rendered.message)
 NativeWasapiPlayer().play(Path(rendered.output_path),output)
def build_stream_command():
 s,m=whisper_stream_path(),whisper_model_path()
 if not s.is_file():raise RuntimeError(f"Whisper live microphone component is missing: {s}")
 if not m.is_file():raise RuntimeError(f"Whisper model is missing: {m}")
 return [str(s),"--model",str(m),"--threads",str(configured_threads()),"--language","ru","--step","0","--length","8000","--keep","0","--vad-thold","0.60","--freq-thold","100.0","--no-gpu"]
def startup_probe():
 try:
  _write_state("PROBING");s=whisper_stream_path()
  if not s.is_file():raise RuntimeError(f"Whisper live microphone component is missing: {s}")
  c=subprocess.run([str(s),"--help"],cwd=str(s.parent),capture_output=True,text=True,errors="replace",timeout=10,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  if c.returncode:raise RuntimeError(f"whisper-stream startup probe failed: exit={c.returncode}; {(c.stderr or c.stdout or 'no output').strip()}")
  _write_state("PROBE_PASS");return 0
 except Exception as e:_write_state("ERROR",error=f"{type(e).__name__}: {e}");return 1
def run_forever(*,core_url=CORE_URL):
 try:
  s=whisper_stream_path()
  if not s.is_file():raise RuntimeError(f"Whisper live microphone component is missing: {s}")
  if not _model_ready():_write_state("PROVISIONING",error="Preparing local Whisper medium model");ensure_voice_model()
  command=build_stream_command();_write_state("STARTING_MIC")
  p=subprocess.Popen(command,cwd=str(s.parent),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  if p.stdout is None:raise RuntimeError("Whisper stream stdout is unavailable")
  mic_ready=False;last="";startup=[]
  try:
   for raw in p.stdout:
    clean=_clean(raw)
    if clean:startup.append(clean);startup=startup[-20:]
    err=_mic_error(raw)
    if err and not mic_ready:_write_state("MIC_ERROR",error=err);raise RuntimeError(f"Microphone capture failed: {err}")
    if not mic_ready and _is_mic_ready(raw):mic_ready=True;_write_state("MIC_OPEN");_write_state("LISTENING")
    text=_normalize_transcript_line(raw)
    if not text or text.casefold()==last.casefold():continue
    if not mic_ready:mic_ready=True;_write_state("MIC_OPEN");_write_state("LISTENING")
    last=text;_write_state("HEARD",heard=text);b=_post_text(text,core_url=core_url);_write_state("CORE_REPLY",heard=b.heard,reply=b.reply)
    if b.tts_requested and b.reply:_write_state("SPEAKING",heard=b.heard,reply=b.reply);_speak(b.reply)
    _write_state("LISTENING",heard=b.heard,reply=b.reply)
  finally:
   if p.poll() is None:p.terminate()
  code=int(p.wait())
  if not mic_ready:
   detail=" | ".join(startup[-8:]) or f"whisper-stream exited with code {code} before microphone readiness"
   _write_state("MIC_ERROR",error=detail);raise RuntimeError(f"Microphone was not opened: {detail}")
  return code
 except Exception as e:
  try:mic_error=_state_path().is_file() and json.loads(_state_path().read_text(encoding="utf-8")).get("state")=="MIC_ERROR"
  except (OSError,json.JSONDecodeError):mic_error=False
  if not mic_error:_write_state("ERROR",error=f"{type(e).__name__}: {e}")
  raise
def main():return startup_probe() if os.environ.get("ORION_VOICE_STARTUP_PROBE")=="1" else run_forever()
if __name__=="__main__":raise SystemExit(main())
