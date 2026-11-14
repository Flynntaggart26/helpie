# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['config', 'actions', 'brain', 'llm', 'documents', 'memory', 'voice', 'reminders', 'notify', 'secrets', 'autostart', 'updater', 'wintools', 'plugins', 'routines', 'audit', 'history', 'clipboard', 'pyaudio', 'speech_recognition', 'edge_tts', 'pygame', 'pygame.mixer', 'comtypes', 'comtypes.client', 'pycaw', 'pycaw.pycaw', 'pvporcupine', 'keyboard', 'requests', 'PIL', 'PIL.ImageGrab', 'pypdf', 'psutil', 'jsonschema', 'winreg', 'ctypes', 'ctypes.wintypes', 'http.server', 'threading', 'urllib.request', 'urllib.parse', 'zipfile', 'tempfile', 'subprocess', 'webbrowser']
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('plugins')


a = Analysis(
    ['C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/helpie.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/VERSION', '.'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/ui', 'ui'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/core', 'core'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/plugins', 'plugins'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/data', 'data'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/basla.bat', '.'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/requirements.txt', '.'), ('C:/Users/egecr/OneDrive/Desktop/PROJELER/helpie/.env.example', '.')],
    hiddenimports=hiddenimports,
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
    name='Helpie',
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
    name='Helpie',
)
