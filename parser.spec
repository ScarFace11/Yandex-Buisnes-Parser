# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Yandex Business Parser (Windows).
#
# Build:  pyinstaller parser.spec
# Result: dist/YandexBusinessParser/YandexBusinessParser.exe  (onedir —
# starts fast and trips fewer antivirus false positives than onefile).
#
# Playwright is deliberately EXCLUDED (~300 MB of browsers + driver).
# The app falls back to Chrome CDP (installed Chrome) and then to httpx,
# so the exe is fully functional without it.

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[os.path.abspath('.')],
    binaries=[],
    datas=[
        # Read-only resources served by Flask
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=(
        # Search/enrichment pipeline modules are imported dynamically
        # inside runner.run_web — make sure they are bundled.
        collect_submodules('yandex_maps_parser')
        + collect_submodules('routes')
        + [
            'vk_sender',
            'run_manager',
            'run_logger',
            'search_history',
            'paths',
            # multiprocessing children re-import the entry module
            '__main__',
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed at runtime, cuts ~100+ MB combined
        'playwright',
        'tkinter',
        'pytest',
        'matplotlib',
        'numpy',
        'PIL',
        'IPython',
        'jedi',
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
    name='YandexBusinessParser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # server log stays visible; browser opens manually
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
    upx=False,
    name='YandexBusinessParser',
)
