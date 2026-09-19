@echo off
rem ══════════════════════════════════════════════════════════════
rem  Build the DEVELOPER .exe with PyInstaller (Windows)
rem  Result: dist-dev\YandexBusinessParserDev\YandexBusinessParserDev.exe
rem
rem  Отличия от публичной сборки (build.bat):
rem    * другое имя exe и своя папка dist-dev\ — публичная сборка не затирается
rem    * порт 5010 вместо 5000 — обе сборки могут работать одновременно
rem    * в шапке горит метка DEV, авто-обновление отключено
rem  Публичный релиз делается из версии без суффикса «-dev»: build.bat.
rem ══════════════════════════════════════════════════════════════
setlocal

if not exist .venv\Scripts\python.exe (
    echo [!] Virtual environment not found. Run setup.bat first.
    exit /b 1
)

echo [1/4] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --quiet pyinstaller || exit /b 1

echo [2/4] Checking the version...
.venv\Scripts\python.exe -c "import config,sys; print('  Версия: v' + config.APP_VERSION); sys.exit(0 if config.is_dev_build() else 3)"
if errorlevel 3 (
    echo [!] APP_VERSION в config.py без суффикса "-dev".
    echo     Сборка соберётся, но метка DEV и отключённое авто-обновление
    echo     включятся только при версии вида "2.3.0-dev".
)

echo [3/4] Cleaning previous dev build...
if exist build rmdir /s /q build
if exist dist-dev rmdir /s /q dist-dev

echo [4/4] Building (this takes a few minutes)...
set YP_DEV=1
.venv\Scripts\python.exe -m PyInstaller parser.spec --noconfirm --distpath dist-dev || exit /b 1
set YP_DEV=

echo.
echo ============================================================
echo  Done: dist-dev\YandexBusinessParserDev\YandexBusinessParserDev.exe
echo  Run it and open http://127.0.0.1:5010 in your browser.
echo  Данные (output\, logs\, .env) создаются рядом с exe,
echo  поэтому dev-сборка не пересекается с публичной.
echo ============================================================
endlocal
