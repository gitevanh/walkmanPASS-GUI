# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['WPASS_gui.py'],
    pathex=[],
    binaries=[],
    datas=collect_data_files('tkinter'),
    hiddenimports=[
        *collect_submodules('tkinter'),
        'mutagen.mp3', 'mutagen.flac', 'mutagen.wave',
        'mutagen.easymp4', 'mutagen.asf', 'mutagen.oggvorbis',
    ],
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
    a.binaries,
    a.datas,
    [],
    name='WPASS_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['wpass.ico'],
)