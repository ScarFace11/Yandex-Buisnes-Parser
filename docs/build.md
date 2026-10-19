# 🏗️ Сборка и запуск из исходников

Документ для автора релиза и для того, кто хочет собрать приложение у себя.
Пользователю достаточно [README](../README.md): там — что приложение делает и
как его скачать.

---

## ▶️ Запуск из исходников

```bash
git clone https://github.com/ScarFace11/Yandex-Buisnes-Parser.git
cd Yandex-Buisnes-Parser
python -m venv .venv
.venv\Scripts\activate        # Windows (source .venv/bin/activate — Linux/macOS)
pip install -r requirements.txt
python app.py
```

Приложение откроет **http://localhost:5000**. Ключи вводить не нужно; на
машине должен быть **Chrome** (или Chromium) — страницы выдачи и карточек
открывает он.

Запуск из исходников не подчиняется порогу минимальной версии и не трогает
установленную сборку: порт 5000, данные — в папке проекта.

## ⚙️ Конфигурация

Все настройки доступны в веб-интерфейсе; продвинутые — в `config.py`
(`MAX_PAGES`, `MAX_CANDIDATES_PER_CITY`, `FETCH_DETAIL`, `RESUME_MODE` и др.).
Порт задаётся переменной окружения `YP_PORT` (по умолчанию Windows-релиз `5000`,
macOS-релиз `5050` — на macOS 5000 занят AirPlay Receiver, сборка разработчика
`5010`; занятый порт не фатален: приложение берёт следующий свободный).

## 🏗️ Локальная сборка (.exe / .app)

Собрать приложение у себя — без релиза, без тега и без смены версии (версия
берётся из `config.py` как есть): в GitHub ничего не отправляется, а порог
минимальной версии к такой сборке не применяется — автор может собрать и
запустить любую версию.

```bat
build.bat              :: Windows → dist\YandexBusinessParser\YandexBusinessParser.exe
```

```bash
./build-mac.sh         # macOS → dist-mac/YandexBusinessParser.app
./build-mac.sh --dev   # сборка разработчика: имя с суффиксом Dev, порт 5010
```

PyInstaller не собирает под чужую ОС, поэтому для второй платформы есть ручной
workflow — его можно запустить из консоли, ничего не коммитя:

```bash
gh workflow run build-manual.yml -f target=both   # windows | macos | both
gh run watch
gh run download --name YandexBusinessParser-windows-x64
```

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
```

Отдельная архитектура: `YP_ARCH=arm64| x86_64|universal2 ./build-mac.sh`.

**Чем macOS-версия отличается:**

- приложение **само открывает браузер** — у `.app` нет окна терминала с адресом
  (отключается `YP_OPEN_BROWSER=0`);
- данные лежат в `~/Library/Application Support/YandexBusinessParser` —
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

## 🤖 Автоматизация в GitHub

| Workflow | Когда запускается | Что делает |
|---|---|---|
| `ci.yml` | каждый PR, push в `main` | тесты на трёх системах (Ubuntu, Windows, macOS) + node-тесты UI + проверка, что `.spec`-файлы и workflow-YAML парсятся |
| `build-exe.yml` | тег `v*` | гейт версии, тесты, Windows `.exe` (в него штампуется версия тега), смоук-тест, черновик GitHub Release |
| `build-macos.yml` | тег `v*` | `.app` для arm64 и x64, подпись Developer ID **или ad-hoc**, нотаризация, смоук-тест, `.zip` + `.dmg` |
| `build-manual.yml` | вручную (Actions → Run workflow или `gh workflow run build-manual.yml -f target=both`) | сборка «как есть» без релиза и без смены версии: Windows `.exe` и macOS `.zip` (arm64/x64) в артефактах запуска — файл просто скачивается и порог минимальной версии к нему не применяется |
| `publish-release.yml` | завершение сборок Windows/macOS | публикует черновик **сам**, когда у тега зелёные обе сборки и на релизе лежат все файлы; dev/rc-теги не публикует. Ручной запуск (`workflow_dispatch` с тегом) — для уже собранных релизов |
| `announce-release.yml` | публикация релиза | объявляет версию в `static/version.json` на `main` — только после того, как релиз опубликован и архив на месте |

> Порядок релиза: тег → зелёные билды обеих платформ → **публикация
> автоматически** (`publish-release.yml`) → версия попадает в `version.json`
> (`announce-release.yml`). Ручных шагов нет: приложения видят обновление
> ровно тогда, когда его можно скачать (иначе ссылка `releases/latest`
> отдаёт предыдущий релиз — «скачал, а версия та же»).
>
> Если автоматика почему-то не сработала — Actions → «Publish release
> (auto)» → Run workflow и указать тег: воркфлоу перепроверит обе сборки,
> наличие файлов и опубликует черновик, ничего не пересобирая.

## 🚦 Порог минимальной версии

Порог публикуется в [static/version.json](../static/version.json) полем
`min_version` и означает: сборки старше этой версии не должны работать вообще.
Сейчас там **2.3.4** — версия, в которой появилось обязательное соглашение.

### Как поставить или поднять порог

Порог задаёт автор релиза, одной командой (версию и историю она не портит):

```bash
python scripts/stamp_version.py --version 2.3.4 --min-version 2.3.4 --no-history
git commit -am "chore(release): минимальная версия 2.3.4" && git push
```

Действует он сразу после пуша в `main` — установленные приложения читают этот
файл оттуда. Обычное обновление версии (`announce-release.yml`) порог **не
сбрасывает**: поднять его можно только осознанно, а опустить — правкой файла.
Что порог не ниже 2.3.4, проверяет [tests/test_min_version_gate.py](../tests/test_min_version_gate.py).

### Когда блокировки нет

Это осознанные исключения, чтобы ограничение не мешало там, где оно вредно:

| Случай | Поведение |
|---|---|
| GitHub недоступен | не блокируем: пропавшая сеть не должна «кирпитить» приложение у пользователя. Если порог уже был получен ранее, он применяется |
| Пункт `min_version` пуст | блокировки нет |
| Сборка разработчика (версия с `-dev`) | никогда не блокируется: это рабочая ветка |
| Запуск из исходников (`python app.py`) | не блокируется — это не установленный релиз |
| Локальная сборка (`build.bat`, `build-mac.sh`, `build-manual.yml`) | не блокируется: рядом с exe (или в корне `.app`) лежит метка `.local-build` |
| Переменная `YP_SKIP_MIN_VERSION=1` | не блокируется — ручной способ снять порог в любой копии |

### Старые версии в открытом доступе

Прошлые релизы остаются на GitHub как история: скачать их можно, но запуститься
они не смогут — окно обновления закрывает интерфейс, а поиск отказывается
стартовать. Для автора это не проблема: локальная сборка любой версии (метка
`.local-build` или `YP_SKIP_MIN_VERSION=1`) работает без ограничения, поэтому
архивы нужны скорее для разбора и отката, чем для пользователей. Релизные
сборки специально снимают метку перед упаковкой
([build-exe.yml](../.github/workflows/build-exe.yml),
[build-macos.yml](../.github/workflows/build-macos.yml)),
чтобы скачанный архив никогда не обходил порог.

## 📜 История изменений

[CHANGELOG.md](../CHANGELOG.md) — единственное место с заметками о версиях:
1–2 абзаца на фичу, что стало удобнее и что починили. Тело GitHub Release
собирается из него (`scripts/release_notes.py`), и он же прикладывается к
релизу ассетом. Нерелизнутые правки живут в разделе `[Unreleased]` и при
выпуске переименовываются в номер версии — что версия сборки описана,
проверяет `tests/test_changelogs.py`.

Плюс `dependabot.yml`: еженедельные PR на обновление pip-зависимостей и
версий GitHub Actions (мажоры PyInstaller игнорируются — они ломают spec'и).

## 🧪 Тесты

```bash
python -m pytest tests -q          # backend: пайплайн, фильтры, пауза, API
node --test tests/ui/               # UI: лог, таблица, пресеты, история файлов
```

CI прогоняет оба набора на Ubuntu, Windows и macOS.
