# 🔍 Yandex Business Parser

Веб-приложение для автоматического сбора баз бизнесов с Яндекс.Карт и 2ГИС:
название, адрес, телефон, рейтинг, отзывы, **соцсети** (VK, Telegram, Instagram,
WhatsApp), сайты — с фильтрами по лидам, оценкой 0–90 и экспортом в Excel.

Собирает в multi-city режиме, живая статистика и таблица результатов, graceful
пауза/стоп, чекпоинт-возобновление. Работает как локально (`python app.py`), так
и из готовых сборок: `.exe` для Windows, `.app` для macOS.

---

## ✨ Ключевые возможности

- **Два источника**: Яндекс.Карты (Search API + загрузка карточек через Chrome
  CDP за 2–6 сек) и 2GIS Catalog API (соцсети, телефоны и рейтинг прямо из
  ответа API).
- **Multi-city**: несколько городов за один запуск, сетка координат для
  покрытия всего города, история поисков по городам, graceful-пауза
  («завершаем город») и продолжение со следующего города.
- **Двухэтапный пайплайн**: этап 1 всегда сохраняет ВСЕ найденные организации
  в `output/raw/`, этап 2 применяет фильтры (соцсети, обязательные сети,
  активность ВКонтакте, оценка лида ≥ N) — другой срез делается без повторного
  парсинга, кнопкой «Применить фильтры заново».
- **Оценка лида 0–90** для каждой организации: нет сайта +30, активный ВК +20,
  рейтинг ≥ 4.5 +15, отзывов ≥ 50 +15, телефон +5, дорогая категория +5.
  Пресеты, сортировка «сначала горячие», подсказка с разбором оценки.
- **Массовый обход соцсетей**: открыть N профилей разом (вкладки не блокируются
  браузером), отметки «Просмотрено» с автосохранением в xlsx.
- **Экспорт**: Excel с форматированием, CSV, JSON, интерактивная HTML-карта.
- **Скорость и устойчивость**: curl-cffi с TLS-отпечатком Chrome, адаптивный
  RPS, прокси-ротация, дедупликация, disk-cache карточек.

## 🚀 Быстрый старт

```bash
git clone https://github.com/ScarFace11/Yandex-Buisnes-Parser.git
cd Yandex-Buisnes-Parser && pip install -r requirements.txt
python app.py
```

Откройте **http://localhost:5000**, вставьте API-ключи (см. ниже) и нажмите
«Найти компании».

## 📥 Установка

### Windows (.exe)

Скачайте `YandexBusinessParser-windows-x64.zip` со страницы
[Releases](https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest),
распакуйте и запустите `YandexBusinessParser.exe`. При первом запуске
SmartScreen может предупредить о неподписанном файле — «Подробнее → Выполнить
в любом случае». Авто-обновление встроено: новая версия скачивается и
устанавливается из самого приложения.

### macOS (.app)

Скачайте `YandexBusinessParser-macos-*.dmg` из
[Releases](https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest)
(arm64 — Apple Silicon, x64 — Intel), перетащите `.app` в `/Applications` и
запустите двойным кликом. Приложение само откроет браузер; данные живут в
`~/Library/Application Support/YandexBusinessParser`.

> Без подписи Developer ID macOS спросит подтверждение при первом запуске:
> правый клик → «Открыть» → «Открыть», либо
> `xattr -dr com.apple.quarantine /Applications/YandexBusinessParser.app`.
> Сборки с подписью и нотаризацией запускаются без предупреждений —
> см. [«Как настроить подпись macOS»](#-как-настроить-подпись-macos).

### Из исходников

```bash
git clone https://github.com/ScarFace11/Yandex-Buisnes-Parser.git
cd Yandex-Buisnes-Parser
python -m venv .venv
.venv\Scripts\activate        # Windows (source .venv/bin/activate — Linux/macOS)
pip install -r requirements.txt
python app.py
```

> 💡 Если Python 3.14, где Playwright падает с 0xC0000005 — парсер
> автоматически переключится на CDP-клиент (Chrome DevTools Protocol).

## 🔑 Настройка API-ключей

Ключи вводятся прямо в веб-интерфейсе — блок **«API-ключи»** сверху боковой
панели. Вставьте ключи Яндекса, 2GIS и/или VK и нажмите **«💾 Сохранить ключи
в .env»** — ключи заработают сразу, без перезапуска. Смена ключа 2GIS сбрасывает
счётчик потраченных токенов (новый ключ = новая месячная квота).

Где взять ключи: Яндекса — [developer.tech.yandex.ru](https://developer.tech.yandex.ru/),
2GIS — [dev.2gis.ru](https://dev.2gis.ru) → Platform Manager → ключ с
разрешением Places API, VK — [vk.com/dev](https://vk.com/dev) (нужен только для
проверки активности ВКонтакте и рассылки; без него поиск работает как обычно).

## 📖 Основные сценарии

1. **Собрать базу кафе по нескольким городам.** Вкладка «Глубина поиска»:
   города, запрос, страниц ×50. Результат — Excel на каждый город в
   `output/raw/` + обработанные файлы с фильтрами.
2. **Отобрать горячих лидов.** Аккордеон «Фильтрация результата»: обязательные
   соцсети, «Оценка лида ≥ 70», сортировка «сначала горячие». В таблице —
   колонка «Оценка» с разбором в подсказке, отметки «Просмотрено» сохраняются
   в файл автоматически.
3. **Массовый обход профилей перед рассылкой.** В таблице выберите сеть и
   «🚀 Открыть 5 профилей» — откроется ровно N вкладок с непросмотренными
   профилями; кнопка активна, пока есть непросмотренные.
4. **Перефильтровать без повторного парсинга.** Сырые данные всегда
   сохраняются: меняете фильтры → «🔄 Применить фильтры заново» → новые файлы
   этапа 2 из уже собранного.

## ⚙️ Конфигурация

Все настройки доступны в веб-интерфейсе; продвинутые — в `config.py`
(`MAX_PAGES`, `MAX_WORKERS`, `PROXIES`, `USE_GRID`, `RESUME_MODE` и др.).
Порт задаётся переменной окружения `YP_PORT` (по умолчанию dev `5010` /
Windows-релиз `5000` / macOS-релиз `5050` — на macOS 5000 занят AirPlay
Receiver; занятый порт не фатален: приложение берёт следующий свободный).

---

## 🍎 Сборка для macOS (.app)

Собирается тот же код, но результат — **`.app`-бандл** для `/Applications`.

**Автоматически:** тег `v*` → `.github/workflows/build-macos.yml` соберёт две
сборки (Apple Silicon `arm64` и Intel `x64`), прогонит смоук-тест бандла и
приложит `.zip` + `.dmg` к GitHub Release:

```
YandexBusinessParser-macos-arm64.zip / .dmg
YandexBusinessParser-macos-x64.zip   / .dmg
```

**Локально (на Mac):**

```bash
./build-mac.sh          # публичная сборка → dist-mac/YandexBusinessParser.app
./build-mac.sh --dev    # сборка разработчика → dist-mac/YandexBusinessParserDev.app
```

Отдельная архитектура: `YP_ARCH=arm64| x86_64|universal2 ./build-mac.sh`.

**Чем macOS-версия отличается:**

- приложение **само открывает браузер** — у `.app` нет окна терминала с адресом
  (отключается `YP_OPEN_BROWSER=0`);
- данные лежат в `~/Library/Application Support/YandexBusinessParser[/Dev]` —
  `.app` из `/Applications` может быть только для чтения (см. `paths.py`);
- **порт 5050**, а не 5000 — на macOS 5000 слушает системный AirPlay Receiver;
- авто-обновление изнутри не работает (запущенный бандл подменить нельзя) —
  вместо «Обновить сейчас» баннер «Скачать vX ↗» со страницей релизов.

## 🔐 Как настроить подпись macOS

По умолчанию сборка подписывается **ad-hoc**: macOS запускает её, но просит
подтверждение при первом открытии (Gatekeeper). Чтобы пользователи получали
приложение **без предупреждений**, нужен аккаунт
[Apple Developer Program](https://developer.apple.com/programs/) ($99/год) и
два шага:

**1. Сертификат → секреты репозитория.**

- В Xcode/Keychain создайте сертификат **Developer ID Application** и экспортируйте
  его в `.p12` (с паролем).
- В репозитории: Settings → Secrets and variables → Actions → New repository
  secret:

| Секрет | Значение |
|---|---|
| `MACOS_CERTIFICATE_P12` | `.p12`-сертификат, закодированный в base64: `base64 -i cert.p12 \| pbcopy` (macOS) или `certutil -encode cert.p12 out.txt` (Windows) |
| `MACOS_CERTIFICATE_PASSWORD` | пароль, под которым экспортирован `.p12` |
| `APPLE_ID` | Apple ID, привязанный к App Store Connect |
| `APPLE_APP_SPECIFIC_PASSWORD` | пароль приложения Apple: appleid.apple.com → «Вход и безопасность» → «Пароли для приложений» |
| `APPLE_TEAM_ID` | 10-символьный Team ID: developer.apple.com → Membership details |

**2. Готово.** `build-macos.yml` сам заметит секреты: импортирует сертификат во
временный keychain, подпишет бандл **Developer ID + hardened runtime** с
`entitlements.plist` (нужен загрузчику PyInstaller), отправит бандл в Apple
(`notarytool submit --wait`) и пришьёт тикет (`stapler staple`). Без секретов
workflow печатает `::warning::` и собирает ad-hoc — сборка не падает.

**Локальная подпись** (сертификат уже в keychain):

```bash
YP_CODESIGN_IDENTITY="Developer ID Application: Имя (TEAMID)" ./build-mac.sh
# + нотаризация:
APPLE_ID=you@example.com APPLE_APP_SPECIFIC_PASSWORD=xxxx APPLE_TEAM_ID=TEAMID \
  YP_CODESIGN_IDENTITY="Developer ID Application: Имя (TEAMID)" ./build-mac.sh
```

---

## ⚙️ Сборка разработчика (ветка `dev`)

Чтобы не выкладывать каждое изменение в `main`, работа ведётся в ветке `dev`:

```bash
git checkout -b dev          # один раз
git push -u origin dev       # дальше просто git push
```

Dev-сборка включается суффиксом `-dev` в версии (`config.py`):
`APP_VERSION = "2.3.0-dev"`. Отличия: метка **⚙ DEV** в шапке, авто-обновление
выключено, порт **5010**, своё имя exe/бандла и своя папка данных — dev- и
публичная сборки не мешают друг другу.

- Локально (Windows): `build-dev.bat` → `dist-dev\YandexBusinessParserDev\`.
- Локально (macOS): `./build-mac.sh --dev`.
- В CI: push в `dev` запускает `build-dev.yml` (Windows) и `build-macos.yml`
  (`.app`-артефакт); Release не создаётся.

**Выпуск в публику:** влить `dev` в `main`, убрать суффикс
(`APP_VERSION = "2.3.0"`), обновить `static/version.json`, поставить тег
`v2.3.0` и запушить — сборки и релиз сделают workflow. CI не даст выпустить
релиз случайно: на теге проверяется, что тег, `APP_VERSION` и
`static/version.json` совпадают и не содержат `-dev`.

## 🤖 Автоматизация в GitHub

| Workflow | Когда запускается | Что делает |
|---|---|---|
| `ci.yml` | каждый PR, push в `main`/`dev` | тесты на трёх системах (Ubuntu, Windows, macOS) + node-тесты UI + проверка, что `.spec`-файлы и workflow-YAML парсятся |
| `build-exe.yml` | тег `v*` | гейт версии, тесты, Windows `.exe`, смоук-тест, GitHub Release |
| `build-macos.yml` | тег `v*`, push в `dev` | `.app` для arm64 и x64, подпись Developer ID **или ad-hoc**, нотаризация, смоук-тест, `.zip` + `.dmg` |
| `build-dev.yml` | push в `dev` | dev-`exe` (порт 5010, без релиза) |

Плюс `dependabot.yml`: еженедельные PR на обновление pip-зависимостей и
версий GitHub Actions (мажоры PyInstaller игнорируются — они ломают spec'и).

## 🧪 Тесты

```bash
python -m pytest tests -q          # backend: пайплайн, фильтры, пауза, API
node --test tests/ui/              # UI: лог, таблица, пресеты, история файлов
```

CI прогоняет оба набора на Ubuntu, Windows и macOS.

## 📄 Документация

- [CHANGELOG.md](CHANGELOG.md) — история изменений по версиям.
- [Issues](https://github.com/ScarFace11/Yandex-Buisnes-Parser/issues) — баги
  и предложения.

## 📄 Лицензия

MIT License
