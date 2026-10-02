# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec file for Shinri Reviews Ranker (DRO Edition).
Produces a standalone single-file Windows executable with embedded assets,
native Edge WebView2 desktop window, icon, and PE version metadata.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Assets to bundle directly into the binary
datas = [
    ('shinri_ranker/static', 'shinri_ranker/static'),
    ('shinri_ratings_cache.json', '.'),
    ('app_icon.ico', '.'),
]
if os.path.exists('shinri_ratings_cache.json.dat'):
    datas.append(('shinri_ratings_cache.json.dat', '.'))
binaries = []

# Hidden imports for OCR and optional Rich terminal formatting
hiddenimports = [
    'marshal',
    'winrt',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.globalization',
    'winrt.windows.graphics.imaging',
    'winrt.windows.media.ocr',
    'winrt.windows.storage.streams',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFilter',
    'rich',
    'rich.console',
    'rich.table',
    'rich.panel',
    'rich.box',
]

# Collect pywebview and pythonnet dependencies for native Edge WebView2 window
wv_datas, wv_binaries, wv_hidden = collect_all('webview')
pn_datas, pn_binaries, pn_hidden = collect_all('pythonnet')
cl_datas, cl_binaries, cl_hidden = collect_all('clr_loader')

datas += wv_datas + pn_datas + cl_datas
binaries += wv_binaries + pn_binaries + cl_binaries
hiddenimports += wv_hidden + pn_hidden + cl_hidden

# Exclude large unused packages to keep executable compact and fast to unpack
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'numpy',
    'torch',
    'PySide6',
    'PyQt6',
    'customtkinter',
    'IPython',
    'pytest',
    'selenium',
    'playwright',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ShinriRanker',
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
    icon='app_icon.ico',
    version='version_info.txt',
)

