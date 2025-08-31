# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os
from pathlib import Path

# Derive project root from current working directory (build script sets cwd)
project_root = Path(os.getcwd()).resolve()
assets = (project_root / 'assets').resolve()
config = (project_root / 'config').resolve()

hidden = [
    'arelle',
    'arelle.Cntlr',
    'arelle.CntlrCmdLine',
    'arelle.PluginManager',
    'cryptography',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
]

a = Analysis([
    str(project_root / 'gui' / 'xbrl_validator_app.py'),
],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(assets), 'assets'),
        (str(config), 'config'),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='XBRLValidatorGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='XBRLValidatorGUI')
