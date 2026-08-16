from __future__ import annotations
import tempfile,wave
from pathlib import Path
from uuid import uuid4
from pydantic import BaseModel
from orion.audio_device_config import audio_device_config
from orion.whisper_cpp_direct_stt import recognize_wav
from orion.native_wasapi_player import NativeWasapiPlayer
from orion.tts_audio import AudioRenderRequest,TtsBackend,VoiceProfile
from orion.voice_core import VoiceAgent
from orion.windows_sapi_backend import WindowsSapiBackend
from orion.windows_wasapi_backend import WasapiDirection,WasapiEndpoint
PROMPT="Привет, как дела?";RESPONSE="Всё хорошо. Связь установлена."
class ConversationalAudioTestResult(BaseModel):
 ok:bool;recognized_text:str="";prompt:str=PROMPT;response:str=RESPONSE;stages:dict[str,bool];message:str;input_samplerate:int|None=None
def _resolve_sounddevice_index(endpoint,direction):
 import sounddevice as sd
 hostapis=sd.query_hostapis();wasapi={i for i,x in enumerate(hostapis) if "wasapi" in str(x.get("name","")).casefold()};key="max_input_channels" if direction is WasapiDirection.INPUT else "max_output_channels";c=[]
 for i,x in enumerate(sd.query_devices()):
  if int(x.get(key,0))<=0:continue
  if wasapi and int(x.get("hostapi",-1)) not in wasapi:continue
  c.append((i,str(x.get("name",""))))
 target=endpoint.name.casefold();exact=next((i for i,n in c if n.casefold()==target),None)
 if exact is not None:return exact
 partial=next((i for i,n in c if target in n.casefold() or n.casefold() in target),None)
 if partial is not None:return partial
 raise RuntimeError(f"WASAPI {direction.value} device not found: {endpoint.name}")
def _native_input_samplerate(device,fallback=48000):
 import sounddevice as sd
 try:s=int(round(float(sd.query_devices(device).get("default_samplerate",fallback))))
 except (TypeError,ValueError):s=fallback
 return s if s>0 else fallback
def _capture_wav(endpoint,target,duration_seconds=4.0):
 import sounddevice as sd
 device=_resolve_sounddevice_index(endpoint,WasapiDirection.INPUT);sr=_native_input_samplerate(device);frames=max(1,int(duration_seconds*sr))
 try:
  with sd.RawInputStream(samplerate=sr,device=device,channels=1,dtype="int16") as stream:audio,_=stream.read(frames)
 except Exception as e:raise RuntimeError(f"Microphone capture failed at Windows/WASAPI native sample rate {sr} Hz: {e}") from e
 target.parent.mkdir(parents=True,exist_ok=True)
 with wave.open(str(target),"wb") as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes(bytes(audio))
 return sr
def _matches_control_phrase(text):
 n="".join(ch for ch in text.casefold() if ch.isalnum() or ch.isspace());return {"привет","как","дела"}.issubset(set(n.split()))
def run_conversational_audio_test():
 stages={"core_connected":True,"input_resolved":False,"audio_captured":False,"phrase_recognized":False,"output_resolved":False,"response_played":False};state=audio_device_config.state();inp=state.resolved_input;out=state.resolved_output
 if inp is None or out is None:return ConversationalAudioTestResult(ok=False,stages=stages,message="Core could not resolve selected audio endpoints")
 stages["input_resolved"]=True;stages["output_resolved"]=True;sr=None;recognized=""
 try:
  with tempfile.TemporaryDirectory(prefix="orion-audio-test-") as tmp:
   capture=Path(tmp)/"input.wav";sr=_capture_wav(inp,capture);stages["audio_captured"]=True;recognized=recognize_wav(capture,language="ru")
   if not _matches_control_phrase(recognized):return ConversationalAudioTestResult(ok=False,recognized_text=recognized,stages=stages,input_samplerate=sr,message=f"Control phrase was not recognized: {recognized or '(no speech)'}")
   stages["phrase_recognized"]=True;backend=WindowsSapiBackend(spool_dir=str(Path(tmp)/"tts"));req=AudioRenderRequest(command_id=f"audio-test-{uuid4()}",text=RESPONSE,agent=VoiceAgent.SYSTEM,profile=VoiceProfile(profile_id="audio_test_ru",locale="ru-RU",persona="orion",rate=1.0,volume=1.0),backend=TtsBackend.WINDOWS_SAPI,output_device=out.device_id);rendered=backend.render(req)
   if not rendered.accepted or not rendered.output_path:return ConversationalAudioTestResult(ok=False,recognized_text=recognized,stages=stages,input_samplerate=sr,message=rendered.message)
   NativeWasapiPlayer().play(Path(rendered.output_path),out);stages["response_played"]=True;return ConversationalAudioTestResult(ok=True,recognized_text=recognized,stages=stages,input_samplerate=sr,message=RESPONSE)
 except Exception as e:return ConversationalAudioTestResult(ok=False,recognized_text=recognized,stages=stages,input_samplerate=sr,message=f"Audio test failed: {e}")
