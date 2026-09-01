# 🔍 Yandex Maps Parser v2.2.0

Веб-приложение для автоматического парсинга бизнесов с Яндекс.Карт.

---

## 📋 Возможности

| Функция | Описание |
|---------|----------|
| 🔍 **Поиск бизнесов** | По запросу и городу с поддержкой сетки координат |
| 🏙 **Multi-city** | Поиск по нескольким городам последовательно |
| 📋 **Сбор данных** | Название, адрес, телефон, рейтинг, отзывы, соцсети |
| 📱 **Фильтр соцсетей** | Режим «Все / С соцсетями / Без соцсетей» + AND-фильтр |
| 📤 **Экспорт** | Excel (с форматированием), CSV, JSON |
| 🗺 **HTML-карта** | Интерактивная карта с маркерами |
| ⏭ **Пропуск города** | Кнопка для пропуска текущего города |
| 📜 **Файловые логи** | Подробные логи для анализа и отправки |
| ⚡ **Аналитика** | RPS, latency, ошибки в реальном времени |
| 💾 **Кэш** | Кэширование detail-страниц (24ч TTL) |
| 🔄 **Адаптивный RPS** | Автоподбор скорости (10→40 RPS) |
| 🌐 **Прокси-ротация** | Ротация IP для увеличения пропускной способности |
| 🔔 **Уведомления** | Browser notifications + звук |
| ⏸️ **Checkpoint** | Возобновление прерванного парсинга |

---

## 🚀 Установка

### Быстрая установка

```bash
git clone https://github.com/ScarFace11/Yandex-Buisnes-Parser.git
cd Yandex-Buisnes-Parser

# Создание виртуального окружения
python -m venv .venv

# Активация (Windows)
.venv\Scripts\activate

# Активация (Linux/macOS)
source .venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Запуск
python app.py
```

Откройте браузер: **http://localhost:5000**

### API-ключ

API-ключ Яндекса можно ввести прямо через веб-интерфейс:
1. Откройте **Дополнительные настройки**
2. Вставьте ключ в поле «API-ключ Яндекса»
3. Нажмите **💾 Сохранить** — ключ запишется в `.env`

Или создайте файл `.env` вручную:
```
YANDEX_API_KEY=ваш_ключ_сюда
```

> 🔑 Получить ключ можно на [Yandex Cloud Developer](https://developer.tech.yandex.ru/)

---

## 📁 Структура проекта

```
├── app.py                          # Flask-приложение (точка входа)
├── config.py                       # Конфигурация (версия, настройки)
├── run_manager.py                  # Управление процессами
├── run_logger.py                   # Файловое логирование
├── requirements.txt                # Зависимости Python
│
├── routes/                         # Flask blueprint'ы
│   ├── parser.py                   # /run, /stop, /skip-city, /logs
│   ├── api.py                      # /reviewed, /export, /analytics, /cache
│   └── sender.py                   # /send/* VK-рассылка
│
├── yandex_maps_parser/             # Модуль парсера
│   ├── state.py                    # Состояние и логирование
│   ├── runner.py                   # run() / run_web() / run_process()
│   ├── search.py                   # Поиск на Яндекс.Картах
│   ├── enrichment.py               # Извлечение деталей бизнеса
│   ├── extractors.py               # Парсинг HTML-карточек
│   ├── exporters.py                # Экспорт в Excel / CSV / JSON / карту
│   ├── http_client.py              # httpx HTTP/2 + rate limiting + прокси
│   ├── cache.py                    # Disk cache detail-страниц
│   ├── geocoding.py                # Геокодинг и построение сетки
│   ├── checkpoint.py               # Checkpoint / Resume
│   ├── constants.py                # Константы и шаблоны
│   └── stats.py                    # Статистика в консоли
│
├── static/
│   ├── css/style.css               # Стили
│   ├── js/app.js                   # JavaScript
│   └── version.json                # Метаданные версии
│
├── templates/
│   └── index.html                  # Веб-интерфейс
│
├── tests/                          # Тесты
│   └── test_extractors.py          # 29 smoke-тестов
│
├── logs/                           # Файловые логи (auto-cleanup 30 дней)
├── output/                         # Результаты парсинга
└── output/.cache/                  # Кэш detail-страниц (auto-cleanup 24ч)
```

---

## ⚙️ Конфигурация

Основные настройки — в файле `config.py`:

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `APP_VERSION` | `"2.2.0"` | Текущая версия |
| `MAX_PAGES` | `1` | Страниц результатов (×50 позиций) |
| `MAX_CANDIDATES_PER_CITY` | `200` | Лимит кандидатов на город |
| `USE_GRID` | `False` | Покрытие сеткой координат |
| `FETCH_DETAIL` | `True` | Загружать карточку бизнеса |
| `MAX_WORKERS` | `20` | Параллельных потоков |
| `PROXIES` | `[]` | Прокси для ротации |

> ⚠️ Все настройки также доступны через веб-интерфейс.

---

## 🏙 Multi-city поиск

В поле «Где ищем?» можно указать несколько городов:

1. Начните вводить название — появится выпадающий список
2. Выберите город кликом или Enter
3. Добавьте следующий город
4. Нажмите «Найти компании»

**Как работает:**
- Города обрабатываются последовательно
- При завершении каждого — звуковое уведомление
- Каждый город — отдельный Excel-файл
- Кнопка **⏭ Город** — пропустить текущий город

---

## ⚡ Производительность

| Опция | Описание | Эффект |
|-------|----------|--------|
| **Адаптивный RPS** | Автоподбор 10→40 RPS | +300% скорость |
| **Прокси-ротация** | Ротация IP через пул клиентов | +N× (N = кол-во прокси) |
| **Кэш detail-страниц** | Диск-кэш с TTL 24ч | Повторный поиск мгновенно |
| **httpx HTTP/2** | Лучший connection pooling | -50% latency на хэндшейках |

**Оптимальные настройки для скорости:**
```python
MAX_WORKERS = 20
MAX_PAGES = 15
MAX_CANDIDATES_PER_CITY = 200
PROXIES = ["http://proxy1:8080", "http://proxy2:8080"]  # опционально
```

---

## 🧪 Тесты

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 📦 Зависимости

- [Flask](https://flask.palletsprojects.com/) — веб-сервер
- [httpx](https://www.python-httpx.org/) — HTTP-клиент (HTTP/2 ready)
- [openpyxl](https://openpyxl.readthedocs.io/) — Excel
- [tqdm](https://tqdm.github.io/) — прогресс-бар
- [colorama](https://github.com/tartley/colorama) — цветной вывод
- [folium](https://python-visualization.github.io/folium/) — HTML-карты

---

## 📄 Лицензия

MIT License
