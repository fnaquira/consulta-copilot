# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Transcriptor en Tiempo Real
# Genera un ejecutable Windows con instalador NSIS (via pyinstaller-versionfile o Inno Setup)

import sys
import os
from pathlib import Path

block_cipher = None

# DLLs de OpenSSL — uv gestiona su propio intérprete; las DLLs no están en
# el .venv sino en la instalación base de Python. PyInstaller no las encuentra
# solo, hay que añadirlas explícitamente para que HTTPS (huggingface_hub,
# torch.hub) funcione en el exe.
_UV_PYTHON_DLLS = Path.home() / "AppData/Roaming/uv/python/cpython-3.11-windows-x86_64-none/DLLs"
_ssl_binaries = []
for _dll in ("libssl-3-x64.dll", "libcrypto-3-x64.dll", "_ssl.pyd"):
    _p = _UV_PYTHON_DLLS / _dll
    if _p.exists():
        _ssl_binaries.append((str(_p), "."))

# Imports ocultos necesarios para faster-whisper, PySide6, sounddevice, etc.
hidden_imports = [
    # PySide6
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # faster-whisper / ctranslate2
    "ctranslate2",
    "faster_whisper",
    "faster_whisper.transcribe",
    "faster_whisper.audio",
    # huggingface_hub (usado por faster-whisper para descargar modelos)
    "huggingface_hub",
    "huggingface_hub.file_download",
    # sounddevice / PyAudioWPatch
    "sounddevice",
    "pyaudiowpatch",
    # silero-vad (paquete pip, v5+)
    "silero_vad",
    "silero_vad.model",
    "silero_vad.utils_vad",
    # torch (requerido por silero-vad)
    "torch",
    "torchaudio",
    # pydantic
    "pydantic",
    "pydantic_settings",
    # SSL (necesario para HTTPS: huggingface_hub, torch.hub)
    "ssl",
    "_ssl",
    "certifi",
    # otros
    "numpy",
    "scipy",
    "scipy.signal",
    "logging",
    "queue",
    "pathlib",
    "typing",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=_ssl_binaries,
    datas=[
        # Incluye el paquete src completo
        ("src", "src"),
        # Certificados CA para HTTPS (huggingface_hub)
        (".venv/Lib/site-packages/certifi/cacert.pem", "certifi"),
        # Modelos de silero-vad empaquetados dentro del paquete pip
        (".venv/Lib/site-packages/silero_vad/data", "silero_vad/data"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tests",
        "tkinter",
        "matplotlib",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriptor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Sin ventana de consola (app GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # Descomenta si tienes un icono
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Transcriptor",
)
