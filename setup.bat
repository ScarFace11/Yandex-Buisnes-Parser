@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════════╗
echo ║  Yandex Maps Parser — Автоустановка     ║
echo ╚══════════════════════════════════════════╝
echo.

REM Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден!
    echo Скачайте Python 3.11+ с https://www.python.org/downloads/
    echo При установке отметьте "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/4] Создание виртуального окружения...
if not exist ".venv" (
    python -m venv .venv
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
