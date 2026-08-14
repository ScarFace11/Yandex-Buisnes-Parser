# Yandex Maps Parser + VK Sender

Веб-приложение для парсинга бизнесов с Яндекс.Карт и автоматической рассылки сообщений ВКонтакте.

## Возможности

- 🔍 **Поиск бизнесов** по запросу и городу (с поддержкой сетки координат)
- 📋 **Сбор данных**: название, адрес, телефон, рейтинг, отзывы, ссылки на соцсети
- 📤 **Экспорт** в JSON, Excel, CSV и HTML-карту
- 💬 **VK-рассылка** по найденным бизнесам с настраиваемым шаблоном сообщения
- ⏸️ **Checkpoint / Resume** — продолжение прерванного парсинга
- 🌐 **Веб-интерфейс** — управление запуском, просмотр логов и результатов в реальном времени

## Быстрый старт

### 1. Клонирование

```bash
git clone https://github.com/ВАШ_ПРОФИЛЬ/yandex-maps-parser.git
cd yandex-maps-parser
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка ключа API

```bash
cp .env.example .env
```

Откройте `.env` и вставьте ключ API Яндекс (получить на [Yandex Cloud Developer](https://developer.tech.yandex.ru/)):

```
YANDEX_API_KEY=ваш_ключ_сюда
```

### 4. Запуск

```bash
python app.py
```

Откройте браузер: [http://localhost:5000](http://localhost:5000)

## Конфигурация

Основные настройки — в файле `config.py`:

| Параметр | По умолчанию | Описание |
|---|---|---|
| `SEARCH_QUERIES` | `["Автосервисы", "шиномонтаж"]` | Поисковые запросы |
| `CITY` | `"Ярославль"` | Город поиска |
| `MAX_PAGES` | `1` | Страниц результатов (50 позиций каждая) |
| `USE_GRID` | `False` | Покрытие сеткой координат |
| `FETCH_DETAIL` | `True` | Загружать карточку бизнеса (соцсети) |
| `VALIDATE_SOCIALS` | `False` | Проверять доступность ссылок |
| `OUTPUT_EXCEL` | `True` | Экспорт в Excel |
| `OUTPUT_MAP` | `True` | HTML-карта с точками |

## VK-рассылка

1. Получите токен ВКонтакте с правами `messages`.
2. В веб-интерфейсе перейдите на вкладку **Рассылка**, вставьте токен и выберите Excel-файл с результатами.
3. Настройте шаблон сообщения и запустите рассылку.

## Структура проекта

```
├── app.py                  # Flask-приложение (веб-интерфейс)
├── config.py               # Конфигурация парсера
├── requirements.txt        # Зависимости Python
├── .env.example            # Пример файла с переменными окружения
├── sender_config.json      # Настройки VK-рассылки (сохраняются UI)
├── yandex_maps_parser/     # Модуль парсера
│   ├── runner.py           # Точки входа run() / run_web()
│   ├── search.py           # Поиск на Яндекс.Картах
│   ├── enrichment.py       # Извлечение деталей бизнеса
│   ├── exporters.py        # Экспорт в CSV / JSON / Excel / карту
│   ├── geocoding.py        # Геокодинг и построение сетки
│   ├── http_client.py      # HTTP-клиент с ротацией прокси
│   ├── checkpoint.py       # Checkpoint / Resume
│   └── extractors.py       # Парсинг HTML-карточек
├── vk_sender/              # Модуль VK-рассылки
│   ├── runner.py           # run_send()
│   ├── vk_adapter.py       # VK API
│   └── excel_manager.py    # Чтение Excel-файлов
├── templates/
│   └── index.html          # Веб-интерфейс
└── output/                 # Результаты парсинга (в .gitignore)
```

## Зависимости

- [Flask](https://flask.palletsprojects.com/) — веб-сервер
- [requests](https://docs.python-requests.org/) — HTTP-запросы
- [openpyxl](https://openpyxl.readthedocs.io/) — работа с Excel
- [folium](https://python-visualization.github.io/folium/) — HTML-карты
- [tqdm](https://tqdm.github.io/) — прогресс-бар в консоли
- [colorama](https://github.com/tartley/colorama) — цветной вывод

## Лицензия

MIT
