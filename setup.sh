#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Yandex Maps Parser — Автоустановка     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "[ОШИБКА] Python3 не найден!"
    echo "Установите: sudo apt install python3 python3-venv (Ubuntu/Debian)"
    echo "        или: brew install python3 (macOS)"
    exit 1
fi

PYTHON=$(command -v python3)
echo "Python: $($PYTHON --version)"

echo "[1/4] Создание виртуального окружения..."
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
    echo "      Готово."
else
    echo "      Виртуальное окружение уже существует."
fi

echo "[2/4] Активация venv..."
source .venv/bin/activate

echo "[3/4] Установка зависимостей..."
pip install -r requirements.txt -q

echo "[4/4] Запуск сервера..."
echo ""
echo "══════════════════════════════════════════"
echo " Сервер запущен: http://localhost:5000"
echo " Нажмите Ctrl+C для остановки"
echo "══════════════════════════════════════════"
echo ""
python app.py
