# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
models = root / 'pdflinker' / 'models'
if not (models / 'medium-v1' / 'installed.json').is_file():
    raise RuntimeError('Run python scripts/prepare_models.py before building the application.')
a = Analysis(
    [str(root / 'launcher.py')],
    pathex=[],
    binaries=[],
    datas=[(str(root / 'pdflinker' / 'assets'), 'pdflinker/assets'),
           (str(models / 'medium-v1'), 'pdflinker/models/medium-v1')],
    hiddenimports=['pdflinker.semantic_engine', 'rapidfuzz'],
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
    name='PDFLinker',
    icon=str(root / 'pdflinker' / 'assets' / 'icon.ico'),
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
    name='PDFLinker',
)
