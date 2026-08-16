from __future__ import annotations

import hashlib, os, shutil, subprocess, sys, tempfile, urllib.request, wave, zipfile
from array import array
from collections.abc import Callable
from pathlib import Path

WHISPER_MODEL_NAME="medium";WHISPER_MODEL_FILENAME="ggml-medium.bin";WHISPER_MODEL_SHA1="fd9727b6e1217c2f614f9b698455c4ffd82463b4";WHISPER_CPP_VERSION="v1.8.6";WHISPER_WINDOWS_X64_SHA256="b07ea0b1b4115a38e1a7b07debf581f0b77d999925f8acb8f39d322b0ba0a822";WHISPER_WINDOWS_X64_URL=f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_CPP_VERSION}/whisper-bin-x64.zip";WHISPER_MODEL_URL=f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{WHISPER_MODEL_FILENAME}?download=true";DEFAULT_THREADS=4;TARGET_SAMPLE_RATE=16000;WINDOWS_ILLEGAL_INSTRUCTION=0xC000001D;WINDOWS_FAIL_FAST_EXCEPTION=0xC0000409;WINDOWS_PORTABLE_RECOVERY_STATUSES=frozenset({WINDOWS_ILLEGAL_INSTRUCTION,WINDOWS_FAIL_FAST_EXCEPTION});PORTABLE_CPU_BACKEND="ggml-cpu.dll";RUNTIME_VERSION_MARKER="ORION_WHISPER_RUNTIME_VERSION.txt";ProgressCallback=Callable[[str,int,int|None],None]
def stt_root():
 o=os.environ.get("ORION_WHISPER_ROOT");return Path(o).expanduser().resolve() if o else Path(os.environ.get("ORION_RUNTIME_DIR","runtime"))/"stt"/"whisper.cpp"
def _packaged_root():
 if getattr(sys,"frozen",False):
  p=Path(sys.executable).resolve().parent/"whisper"
  if p.is_dir():return p
 return None
def whisper_cli_path():
 o=os.environ.get("ORION_WHISPER_CLI")
 if o:return Path(o).expanduser().resolve()
 packaged=_packaged_root()
 if packaged:
  p=packaged/("whisper-cli.exe" if os.name=="nt" else "whisper-cli")
  if p.is_file():return p
 return stt_root()/("whisper-cli.exe" if os.name=="nt" else "whisper-cli")
def whisper_model_path():
 o=os.environ.get("ORION_WHISPER_MODEL");return Path(o).expanduser().resolve() if o else stt_root()/"models"/WHISPER_MODEL_FILENAME
def _windows_runtime_complete(cli):
 if os.name!="nt":return True
 # Packaged installer runtime is version-pinned by the build itself; it does not
 # need the mutable runtime marker used by downloaded/repairable runtimes.
 packaged=_packaged_root()
 if packaged and cli.parent.resolve()==packaged.resolve():return (cli.parent/PORTABLE_CPU_BACKEND).is_file()
 marker=cli.parent/RUNTIME_VERSION_MARKER
 try:v=marker.read_text(encoding="utf-8").strip()
 except OSError:return False
 return (cli.parent/PORTABLE_CPU_BACKEND).is_file() and v==WHISPER_CPP_VERSION
def runtime_ready():
 c=whisper_cli_path();return c.is_file() and whisper_model_path().is_file() and _windows_runtime_complete(c)
def configured_threads():
 try:v=int(os.environ.get("ORION_WHISPER_THREADS",str(DEFAULT_THREADS)))
 except ValueError:v=DEFAULT_THREADS
 return max(1,min(v,16))
def _hash(path,algorithm):
 d=hashlib.new(algorithm)
 with path.open("rb") as h:
  for c in iter(lambda:h.read(1024*1024),b""):d.update(c)
 return d.hexdigest()
def _download(url,target,*,stage,progress=None):
 target.parent.mkdir(parents=True,exist_ok=True);r=urllib.request.Request(url,headers={"User-Agent":"ORION-DCS/0.2"})
 with urllib.request.urlopen(r,timeout=120) as response,target.open("wb") as output:
  z=response.headers.get("Content-Length")
  try:total=int(z) if z else None
  except ValueError:total=None
  n=0
  while True:
   c=response.read(1024*1024)
   if not c:break
   output.write(c);n+=len(c)
   if progress:progress(stage,n,total)
def ensure_runtime(progress=None):
 cli=whisper_cli_path();model=whisper_model_path()
 if cli.is_file() and model.is_file() and _windows_runtime_complete(cli):
  if progress:progress("ready",1,1)
  return cli,model
 if os.name!="nt" and not cli.is_file():raise RuntimeError("Automatic ORION Whisper provisioning currently supports Windows x64 only")
 root=stt_root();root.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix="orion-whisper-install-") as t:
  td=Path(t);need=not cli.is_file() or not _windows_runtime_complete(cli)
  if need:
   a=td/"whisper-bin-x64.zip";_download(WHISPER_WINDOWS_X64_URL,a,stage="runtime",progress=progress)
   if progress:progress("runtime_verify",0,None)
   actual=_hash(a,"sha256")
   if actual!=WHISPER_WINDOWS_X64_SHA256:raise RuntimeError(f"Whisper runtime checksum mismatch: {actual}")
   x=td/"runtime"
   with zipfile.ZipFile(a) as z:z.extractall(x)
   found=next(x.rglob("whisper-cli.exe"),None)
   if found is None:raise RuntimeError("whisper-cli.exe was not found in the official whisper.cpp package")
   for item in found.parent.iterdir():
    dst=root/item.name
    shutil.copytree(item,dst,dirs_exist_ok=True) if item.is_dir() else shutil.copy2(item,dst)
   (root/RUNTIME_VERSION_MARKER).write_text(WHISPER_CPP_VERSION+"\n",encoding="utf-8");cli=whisper_cli_path()
  if not model.is_file():
   tm=td/WHISPER_MODEL_FILENAME;_download(WHISPER_MODEL_URL,tm,stage="model",progress=progress)
   if progress:progress("model_verify",0,None)
   actual=_hash(tm,"sha1")
   if actual!=WHISPER_MODEL_SHA1:raise RuntimeError(f"Whisper medium model checksum mismatch: {actual}")
   model.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(tm,model)
 if not runtime_ready():raise RuntimeError("ORION Whisper runtime provisioning did not produce the required files")
 if progress:progress("ready",1,1)
 return whisper_cli_path(),model
def _read_pcm16_mono_16k(source):
 with wave.open(str(source),"rb") as w:ch=w.getnchannels();sw=w.getsampwidth();sr=w.getframerate();frames=w.readframes(w.getnframes())
 if sw!=2:raise RuntimeError(f"Whisper input must be 16-bit PCM; got sample width {sw}")
 if ch<1:raise RuntimeError("Whisper input WAV has no audio channels")
 s=array("h");s.frombytes(frames)
 if sys.byteorder!="little":s.byteswap()
 if ch>1:
  mono=array("h")
  for i in range(0,len(s),ch):f=s[i:i+ch];mono.append(int(sum(f)/len(f)))
  s=mono
 if sr!=TARGET_SAMPLE_RATE:
  if sr<=0:raise RuntimeError(f"Invalid WAV sample rate: {sr}")
  count=max(1,int(round(len(s)*TARGET_SAMPLE_RATE/sr)));r=array("h")
  if len(s)==1:r.extend([s[0]]*count)
  else:
   scale=(len(s)-1)/max(1,count-1)
   for ti in range(count):pos=ti*scale;l=int(pos);rr=min(l+1,len(s)-1);f=pos-l;v=round(s[l]+(s[rr]-s[l])*f);r.append(max(-32768,min(32767,int(v))))
  s=r
 if sys.byteorder!="little":s.byteswap()
 return s.tobytes()
def _prepare_input_wav(source,target):
 pcm=_read_pcm16_mono_16k(source);target.parent.mkdir(parents=True,exist_ok=True)
 with wave.open(str(target),"wb") as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(TARGET_SAMPLE_RATE);w.writeframes(pcm)
def _windows_status(rc):return rc&0xFFFFFFFF
def _is_windows_portable_recovery_status(rc):return os.name=="nt" and _windows_status(rc) in WINDOWS_PORTABLE_RECOVERY_STATUSES
def _portable_backend_available(root):return (root/PORTABLE_CPU_BACKEND).is_file()
def _force_portable_cpu_backend(root,*,trigger_status=None):
 portable=root/PORTABLE_CPU_BACKEND
 if not portable.is_file():return []
 disabled=[]
 for c in sorted(root.glob("ggml-cpu-*.dll")):
  d=c.with_suffix(c.suffix+".orion-disabled");d.unlink(missing_ok=True);c.replace(d);disabled.append(d)
 (root/"ORION_PORTABLE_CPU_BACKEND.txt").write_text(f"ORION is using the pinned generic ggml-cpu.dll backend after a Windows whisper.cpp backend crash ({f'0x{trigger_status:08X}' if trigger_status is not None else 'unknown'}).\n",encoding="utf-8");return disabled
def _run_whisper(command):return subprocess.run(command,capture_output=True,text=True,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
def _failure_detail(c,*,recovered=False):
 detail=c.stderr.strip() or c.stdout.strip() or "no process output";status=_windows_status(c.returncode) if os.name=="nt" else c.returncode;return f"{'generic CPU retry failed' if recovered else 'process failed'}; exit={c.returncode} status={f'0x{status:08X}' if os.name=='nt' else status}; {detail}"
def recognize_wav(path,*,language="auto"):
 if not runtime_ready():raise RuntimeError("Whisper medium is not prepared. Install speech recognition from Launcher first.")
 cli=whisper_cli_path();model=whisper_model_path()
 with tempfile.TemporaryDirectory(prefix="orion-whisper-") as t:
  td=Path(t);prepared=td/"input-16k.wav";out=td/"transcript";_prepare_input_wav(path,prepared);cmd=[str(cli),"--model",str(model),"--file",str(prepared),"--threads",str(configured_threads()),"--processors","1","--no-gpu","--no-timestamps","--no-prints","--output-txt","--output-file",str(out),"--language",language];c=_run_whisper(cmd)
  if c.returncode!=0 and _is_windows_portable_recovery_status(c.returncode):
   root=cli.parent;status=_windows_status(c.returncode)
   if _portable_backend_available(root):
    _force_portable_cpu_backend(root,trigger_status=status);c=_run_whisper(cmd)
    if c.returncode!=0:raise RuntimeError(f"Whisper STT failed: {_failure_detail(c,recovered=True)}")
   else:raise RuntimeError(f"Whisper STT failed with recoverable Windows backend status 0x{status:08X}, and the pinned ggml-cpu.dll backend is unavailable")
  elif c.returncode!=0:raise RuntimeError(f"Whisper STT failed: {_failure_detail(c)}")
  tp=out.with_suffix(".txt");text=tp.read_text(encoding="utf-8",errors="replace").strip() if tp.is_file() else c.stdout.strip();return " ".join(text.split())
