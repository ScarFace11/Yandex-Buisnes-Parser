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

echo [1/3] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --quiet pyinstaller || exit /b 1

echo [2/3] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Building (this takes a few minutes)...
.venv\Scripts\python.exe -m PyInstaller parser.spec --noconfirm || exit /b 1

echo.
echo ============================================================
echo  Done: dist\YandexBusinessParser\YandexBusinessParser.exe
echo  Run it and open http://127.0.0.1:5000 in your browser.
echo  output\, logs\ and .env are created next to the exe.
echo ============================================================
endlocal
