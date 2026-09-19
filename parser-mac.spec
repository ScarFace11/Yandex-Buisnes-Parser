# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Yandex Business Parser on macOS.
#
# Build (публичная сборка):   pyinstaller parser-mac.spec
# Result: dist-mac/YandexBusinessParser.app
#
# Build (сборка разработчика): YP_DEV=1 pyinstaller parser-mac.spec --distpath dist-mac
# Result: dist-mac/YandexBusinessParserDev.app — своё имя, свой порт (5010),
# без авто-обновления. Проще всего — ./build-mac.sh [--dev].
#
# Отличия от Windows-спеки (parser.spec):
#   * результат — .app-бандл (BUNDLE), а не папка с .exe: его можно
#     перетащить в /Applications и запускать двойным кликом;
#   * console=False: окно терминала не нужно, приложение само открывает
#     браузер (app.py, только на macOS);
#   * YP_ARCH=arm64|x86_64 задаёт архитектуру (на CI — своя машина под каждую).
#
# Playwright is deliberately EXCLUDED (~300 MB of browsers + driver).
# The app falls back to Chrome CDP (installed Chrome) and then to httpx,
# so the bundle is fully functional without it.

import os
import re
from PyInstaller.utils.hooks import collect_submodules

# Версия — из config.py без импорта (импорт тянет .env и предупреждения).
APP_VERSION = "0.0.0"
try:
    with open("config.py", encoding="utf-8") as _fh:
        _m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _fh.read())
        if _m:
            APP_VERSION = _m.group(1)
except Exception:
    pass

# YP_DEV=1 → сборка разработчика (другое имя бандла + другая папка данных).
DEV_BUILD = os.environ.get("YP_DEV", "").strip().lower() not in ("", "0", "false", "no")
APP_NAME = "YandexBusinessParserDev" if DEV_BUILD else "YandexBusinessParser"
BUNDLE_ID = ("com.yandexparser.desktop.dev" if DEV_BUILD
             else "com.yandexparser.desktop")
# Arch of the produced binary: arm64 / x86_64 / universal2 (empty → native).
TARGET_ARCH = os.environ.get("YP_ARCH", "").strip() or None
ICON = os.environ.get("YP_ICON", "static/icon.icns")
if not os.path.exists(ICON):
    ICON = None

# Подпись Developer ID: identity и entitlements приходят из окружения — так
# spec остаётся нейтральным. Без них (локальная сборка, CI без секретов)
# PyInstaller подписывает бандл ad-hoc, чего достаточно для запуска (Gatekeeper
# попросит подтверждение — см. README «Как настроить подпись macOS»).
CODESIGN_IDENTITY = os.environ.get("YP_CODESIGN_IDENTITY", "").strip() or None
ENTITLEMENTS = os.environ.get("YP_ENTITLEMENTS", "").strip() or None
if ENTITLEMENTS and not os.path.exists(ENTITLEMENTS):
    ENTITLEMENTS = None

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
            # multiprocessing children re-import the entry module. On macOS
            # the default start method is spawn, so this import is mandatory.
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
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # .app: без окна терминала, браузер открывает app.py
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    # Developer ID из окружения (CI с секретами) или None → ad-hoc подпись.
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=ICON,
    bundle_identifier=BUNDLE_ID,
    version=APP_VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        # Apple Silicon требует macOS 11+; сборку под Intel тоже не ограничиваем
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.business",
        "NSRequiresAquaSystemAppearance": False,
    },
)
