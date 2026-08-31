@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════════╗
echo ║  Yandex Maps Parser — Автоустановка     ║
echo ╚══════════════════════════════════════════╝
echo.

REM ── Поиск рабочего Python ──
set PYTHON_CMD=

REM 1. Пробуем py (Python Launcher — работает даже если python из Store)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :found
)

REM 2. Пробуем python3
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto :found
)

REM 3. Пробуем python (может быть Store-заглушка)
python --version >nul 2>&1
if %errorlevel% equ 0 (
    REM Проверяем что это не заглушка Store
    for /f "delims=" %%i in ('python --version 2^>^&1') do set PYVER=%%i
    echo %PYVER% | findstr /i "Python 3" >nul
    if %errorlevel% equ 0 (
        set PYTHON_CMD=python
        goto :found
    )
)

echo [ОШИБКА] Python 3.11+ не найден!
echo.
echo Установите Python:
echo   1. Скачайте с https://www.python.org/downloads/
echo   2. При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
echo   3. Запустите setup.bat заново
echo.
pause
exit /b 1

:found
echo Найден: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM ── Установка ──
echo [1/4] Создание виртуального окружения...
if not exist ".venv" (
    %PYTHON_CMD% -m venv .venv
    echo       Готово.
) else (
    echo       Виртуальное окружение уже существует.
)

echo [2/4] Активация venv...
call .venv\Scripts\activate.bat

echo [3/4] Установка зависимостей...
pip install -r requirements.txt -q

echo [4/4] Запуск сервера...
echo.
echo ══════════════════════════════════════════
echo  Сервер запущен: http://localhost:5000
echo  Нажмите Ctrl+C для остановки
echo ══════════════════════════════════════════
echo.
python app.py

pause
