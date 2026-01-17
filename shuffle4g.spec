# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os
import sys

datas = []
binaries = []
hiddenimports = []

# Collect customtkinter data
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

if sys.platform == 'darwin':
    icon_path = 'src/shuffle4g/assets/icons/icon.icns' if os.path.exists('src/shuffle4g/assets/icons/icon.icns') else None
elif sys.platform == 'win32':
    icon_path = 'src/shuffle4g/assets/icons/icon.ico' if os.path.exists('src/shuffle4g/assets/icons/icon.ico') else None
else:
    icon_path = None

datas.append(('src/shuffle4g/assets', 'shuffle4g/assets'))

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='shuffle4g',
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
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='shuffle4g',
    )

    # App bundle for macOS
    app = BUNDLE(
        coll,
        name='shuffle4g.app',
        icon=icon_path,
        bundle_identifier='com.shuffle4g.app',
        info_plist={
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleName': 'shuffle4g',
            'NSHighResolutionCapable': True,
        },
    )
else:
    # Onefile for Windows and Linux
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='shuffle4g',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path,
    )
