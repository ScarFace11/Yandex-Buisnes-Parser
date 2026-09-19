#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  Build the macOS .app bundle with PyInstaller
#
#  Публичная сборка:  ./build-mac.sh
#    → dist-mac/YandexBusinessParser.app
#  Сборка разработчика:  ./build-mac.sh --dev
#    → dist-mac/YandexBusinessParserDev.app  (порт 5010, без авто-обновления)
#
#  Готовая .app перетаскивается в /Applications и запускается двойным
#  кликом: приложение само открывает браузер (app.py), а данные живут в
#  ~/Library/Application Support/YandexBusinessParser[/Dev].
#
#  Архитектуру можно задать явно:  YP_ARCH=arm64 ./build-mac.sh
#  (на Intel-маках — YP_ARCH=x86_64, универсально — YP_ARCH=universal2).
# ══════════════════════════════════════════════════════════════
set -euo pipefail

cd "$(dirname "$0")"

DEV=0
for arg in "$@"; do
    case "$arg" in
        --dev|-d) DEV=1 ;;
        *) echo "[!] Неизвестный аргумент: $arg"; echo "    Использование: ./build-mac.sh [--dev]"; exit 2 ;;
    esac
done

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[!] Эта сборка — только для macOS: PyInstaller не собирает .app на других системах."
    exit 1
fi

echo "[1/5] Проверяю Python и PyInstaller..."
"$PY" -m pip install --quiet --upgrade pyinstaller

echo "[2/5] Проверяю версию..."
"$PY" - <<'PY'
import sys
import config
print(f"  Версия: v{config.APP_VERSION}")
if config.is_dev_build():
    print("  Режим: сборка разработчика (суффикс «-dev» в APP_VERSION)")
else:
    print("  Режим: публичная сборка")
PY

if [ "$DEV" = "1" ] && ! "$PY" -c "import config,sys; sys.exit(0 if config.is_dev_build() else 1)"; then
    echo "[!] Для --dev версия должна быть с суффиксом «-dev» (например 2.3.0-dev)."
    echo "    Сборка продолжится, но метка DEV и отключённое авто-обновление не включатся."
fi

echo "[3/5] Чищу прошлую сборку..."
rm -rf build dist-mac

echo "[4/5] Собираю (несколько минут)..."
if [ "$DEV" = "1" ]; then
    YP_DEV=1 "$PY" -m PyInstaller parser-mac.spec --noconfirm --distpath dist-mac
    NAME="YandexBusinessParserDev"
else
    "$PY" -m PyInstaller parser-mac.spec --noconfirm --distpath dist-mac
    NAME="YandexBusinessParser"
fi

echo "[5/5] Подпись..."
if [ -n "$YP_CODESIGN_IDENTITY" ]; then
    # Сертификат Developer ID есть в связке ключей — подписываем по-настоящему
    # (hardened runtime + entitlements, как для нотаризации).
    codesign --force --deep --sign "$YP_CODESIGN_IDENTITY" --options runtime \
        --entitlements entitlements.plist --timestamp "dist-mac/$NAME.app"
    codesign --verify --deep --strict "dist-mac/$NAME.app" && echo "  Подпись Developer ID в порядке."
    if command -v xcrun >/dev/null 2>&1 && [ -n "$APPLE_ID" ] && [ -n "$APPLE_APP_SPECIFIC_PASSWORD" ] && [ -n "$APPLE_TEAM_ID" ]; then
        echo "  Нотаризация (может занять несколько минут)..."
        WORK="$(mktemp -d)"
        ditto -c -k --sequesterRsrc --keepParent "dist-mac/$NAME.app" "$WORK/notary.zip"
        xcrun notarytool store-credentials YP_NOTARY \
            --apple-id "$APPLE_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" \
            --team-id "$APPLE_TEAM_ID"
        xcrun notarytool submit "$WORK/notary.zip" --keychain-profile YP_NOTARY --wait
        xcrun stapler staple "dist-mac/$NAME.app"
        xcrun stapler validate "dist-mac/$NAME.app" && echo "  Нотаризация в порядке."
    else
        echo "  [i] APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID не заданы — без нотаризации."
    fi
else
    # Ad-hoc: Apple Silicon требует хотя бы её; Gatekeeper попросит подтверждение.
    codesign --force --deep --sign - "dist-mac/$NAME.app" || true
    codesign --verify --deep --strict "dist-mac/$NAME.app" && echo "  Ad-hoc подпись в порядке."
    echo "  [i] Настоящая подпись: YP_CODESIGN_IDENTITY="Developer ID Application: ..." ./build-mac.sh"
fi

PORT=5000
[ "$DEV" = "1" ] && PORT=5010

cat <<EOF

============================================================
 Done: dist-mac/$NAME.app
 Запуск:  open dist-mac/$NAME.app       (или перетащите в /Applications)
 Адрес:   http://127.0.0.1:$PORT
 Данные:  ~/Library/Application Support/$NAME (output/, logs/, .env)

 Если macOS говорит «не удаётся проверить разработчика»
 (сборка не подписана сертификатом Apple), один раз выполните:
   xattr -dr com.apple.quarantine /Applications/$NAME.app
============================================================
EOF
