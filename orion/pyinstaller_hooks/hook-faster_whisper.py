from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("faster_whisper")
