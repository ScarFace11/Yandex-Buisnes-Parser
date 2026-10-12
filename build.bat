@echo off
rem ══════════════════════════════════════════════════════════════
rem  Build YandexBusinessParser.exe with PyInstaller (Windows)
rem  Result: dist\YandexBusinessParser\YandexBusinessParser.exe
rem ══════════════════════════════════════════════════════════════
setlocal

if not exist .venv\Scripts\python.exe (
    echo [!] Virtual environment not found. Run setup.bat first.
    exit /b 1
)

echo [1/4] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --quiet pyinstaller || exit /b 1

echo [2/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/4] Building (this takes a few minutes)...
.venv\Scripts\python.exe -m PyInstaller parser.spec --noconfirm || exit /b 1

echo [4/4] Marking this build as local...
rem Метка .local-build: это не «установленный релиз», поэтому порог
rem минимальной версии (min_version в version.json) к такой сборке не
rem применяется — автор может собрать и запустить любую версию у себя
rem (см. config.skips_min_version).
if not exist dist\YandexBusinessParser mkdir dist\YandexBusinessParser
type nul > dist\YandexBusinessParser\.local-build || exit /b 1

echo.
echo ============================================================
echo  Done: dist\YandexBusinessParser\YandexBusinessParser.exe
echo  Run it and open http://127.0.0.1:5000 in your browser.
echo  output\, logs\ and .env are created next to the exe.
echo  Local build: the minimum-version limit does not apply to it.
echo ============================================================
endlocal
