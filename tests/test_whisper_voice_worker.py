from pathlib import Path
import pytest
from orion import whisper_voice_worker as worker

def test_stream_parser_drops_runtime_noise():
 assert worker._normalize_transcript_line("main: using VAD\n")=="";assert worker._normalize_transcript_line("whisper_init: loading model\n")=="";assert worker._normalize_transcript_line("  Привет, как дела?  \n")=="Привет, как дела?"
def test_microphone_markers():
 assert worker._is_mic_ready("[Start speaking]\n");assert worker._is_mic_ready("capture: device opened\n");assert worker._mic_error("failed to open audio device")
def test_stream_command_is_live_vad_cpu_only(monkeypatch,tmp_path):
 s=tmp_path/"whisper-stream.exe";m=tmp_path/"ggml-medium.bin";s.write_bytes(b"s");m.write_bytes(b"m");monkeypatch.setattr(worker,"whisper_stream_path",lambda:s);monkeypatch.setattr(worker,"whisper_model_path",lambda:m);monkeypatch.setattr(worker,"configured_threads",lambda:4);c=worker.build_stream_command();assert c[0]==str(s);assert c[c.index("--language")+1]=="ru";assert c[c.index("--step")+1]=="0";assert "--vad-thold" in c;assert "--no-gpu" in c
def test_post_text_contract(monkeypatch):
 class R:
  def __enter__(self):return self
  def __exit__(self,*a):return False
  def read(self):return b'{"heard":"hi","reply":"ok","matched":true,"tts_requested":true}'
 monkeypatch.setattr(worker.urllib.request,"urlopen",lambda request,timeout:R());r=worker._post_text("hi",core_url="http://core");assert r.matched and r.tts_requested and r.reply=="ok"
def test_worker_provisions_only_model_before_spawning_packaged_stream(monkeypatch,tmp_path):
 s=tmp_path/"whisper-stream.exe";s.write_bytes(b"s");monkeypatch.setattr(worker,"whisper_stream_path",lambda:s);monkeypatch.setattr(worker,"_model_ready",lambda:False);monkeypatch.setattr(worker,"build_stream_command",lambda:[str(s)]);calls=[]
 monkeypatch.setattr(worker,"ensure_voice_model",lambda:calls.append("model"))
 class P:
  stdout=iter(["[Start speaking]\n"])
  def poll(self):return 0
  def terminate(self):raise AssertionError()
  def wait(self):return 0
 monkeypatch.setattr(worker.subprocess,"Popen",lambda *a,**k:(calls.append("spawn") or P()));assert worker.run_forever(core_url="http://core")==0;assert calls==["model","spawn"]
def test_worker_does_not_claim_listening_before_mic_ready(monkeypatch,tmp_path):
 s=tmp_path/"whisper-stream.exe";s.write_bytes(b"s");monkeypatch.setattr(worker,"whisper_stream_path",lambda:s);monkeypatch.setattr(worker,"_model_ready",lambda:True);monkeypatch.setattr(worker,"build_stream_command",lambda:[str(s)]);states=[];monkeypatch.setattr(worker,"_write_state",lambda state,**kw:states.append((state,kw)))
 class P:
  stdout=iter(["whisper_init: loading model\n","failed to open audio device\n"])
  def poll(self):return 1
  def terminate(self):pass
  def wait(self):return 1
 monkeypatch.setattr(worker.subprocess,"Popen",lambda *a,**k:P())
 with pytest.raises(RuntimeError):worker.run_forever(core_url="http://core")
 names=[x[0] for x in states];assert "LISTENING" not in names;assert "MIC_ERROR" in names
def test_worker_bridges_only_after_mic_open(monkeypatch,tmp_path):
 s=tmp_path/"whisper-stream.exe";s.write_bytes(b"s");monkeypatch.setattr(worker,"whisper_stream_path",lambda:s);monkeypatch.setattr(worker,"_model_ready",lambda:True);monkeypatch.setattr(worker,"build_stream_command",lambda:[str(s)]);states=[];monkeypatch.setattr(worker,"_write_state",lambda state,**kw:states.append(state))
 class P:
  stdout=iter(["[Start speaking]\n","Привет. Как дела?\n"])
  def poll(self):return 0
  def terminate(self):raise AssertionError()
  def wait(self):return 0
 monkeypatch.setattr(worker.subprocess,"Popen",lambda *a,**k:P());monkeypatch.setattr(worker,"_post_text",lambda text,core_url:worker.VoiceBridgeReply(text,"Всё хорошо. Связь установлена.",True,False));assert worker.run_forever(core_url="http://core")==0;assert states.index("MIC_OPEN")<states.index("LISTENING")<states.index("HEARD")
