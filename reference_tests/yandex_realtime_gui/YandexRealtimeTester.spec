# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import get_module_file_attribute

HERE = Path(SPEC).resolve().parent
samplerate_binary = get_module_file_attribute('samplerate')
license_datas = [
    (str(path), 'licenses')
    for path in (HERE / 'licenses').glob('*')
    if path.is_file()
]

a = Analysis(
    [str(HERE / 'yandex_realtime_tester.py')],
    pathex=[str(HERE)],
    binaries=[
        (str(HERE / 'native' / 'win_amd64' / 'opus.dll'), 'native/win_amd64'),
        (samplerate_binary, '.'),
    ],
    datas=license_datas,
    hiddenimports=['samplerate'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YandexRealtimeTester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YandexRealtimeTester',
)
