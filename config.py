# ═══════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ парсера Яндекс.Карт
#  Редактируйте этот файл под свои нужды.
# ═══════════════════════════════════════════════════════════════
import os
import sys

# Вывод в UTF-8 и без падений: конфиг импортируется первым в любом
# запуске, а перенаправленный stdout на русской Windows — это cp1251,
# где любое сообщение с эмодзи роняло старт (см. console_io).
from console_io import enable_utf8, say

enable_utf8()

# Версия приложения. Для публичного релиза — без суффиксов: "2.3.4".
APP_VERSION = "2.3.4"


def is_dev_build() -> bool:
    """True для внутренней сборки (версия с суффиксом «-dev»/«-beta»)."""
    v = str(APP_VERSION).strip().lower()
    return v.endswith(("-dev", "-beta")) or "-dev." in v or "-beta." in v


# ── Минимально допустимая версия ──────────────────────────────
# Порог публикуется в static/version.json (min_version) и означает «ниже этой
# версии работать нельзя»: пользователь видит окно обновления, а поиск
# отказывается стартовать. Порог ставит автор релиза — например, когда в
# новой версии появилось пользовательское соглашение, без которого прежние
# сборки работать не должны.
SKIP_MIN_VERSION_ENV = "YP_SKIP_MIN_VERSION"


def skips_min_version() -> bool:
    """True для сборок, которым порог минимальной версии не мешает.

    Так помечены все локальные варианты запуска:

      * внутренняя сборка (версия с суффиксом «-dev»);
      * запуск из исходников (`python app.py`) — это не установленный релиз;
      * готовая сборка из build.bat / build-mac.sh / workflow build-manual.yml:
        рядом с exe (или в корне .app) лежит файл ``.local-build``
        (см. paths.local_build_marker);
      * явная переменная окружения ``YP_SKIP_MIN_VERSION=1``.

    Скачанная с GitHub сборка не проходит ни по одному признаку и порог
    соблюдает — в этом и смысл: ограничение касается пользователей, а не
    автора, который должен иметь возможность запустить любую версию.
    """
    if is_dev_build():
        return True
    if os.environ.get(SKIP_MIN_VERSION_ENV, "").strip().lower() not in (
            "", "0", "false", "no", "off"):
        return True
    try:
        import paths
        if not paths.is_frozen():
            return True                     # из исходников: автор, не релиз
        return paths.local_build_marker().exists()
    except Exception:
        return False


# Порт по умолчанию для внутренней сборки — 5010 вместо 5000, чтобы она не
# боролась за один порт с публичной.
DEV_PORT = 5010

# macOS: порт 5000 занят системным AirPlay Receiver (macOS 12+), поэтому у
# .app-сборки свой порт — иначе первый же запуск упирался бы в «порт занят».
MAC_PORT = 5050


def app_port() -> int:
    """HTTP-порт: переменная YP_PORT → внутренняя сборка 5010 → macOS 5050 → 5000.

    Порядок важен: у внутренней сборки свой порт на любой системе, а публичная
    сборка на macOS не может занять 5000 (там слушает AirPlay Receiver).
    Занятый порт не фатален: app.py возьмёт следующий свободный.
    """
    try:
        from_env = int(os.getenv("YP_PORT", ""))
        if 1 <= from_env <= 65535:
            return from_env
    except (TypeError, ValueError):
        pass
    if is_dev_build():
        return DEV_PORT
    if sys.platform == "darwin":
        return MAC_PORT
    return 5000

# ── Запросы ──────────────────────────────────────────────────
# Один или несколько поисковых запросов. Все выполняются за один запуск.
SEARCH_QUERIES = [
    #"кафе",
    # "ресторан",
    # "парикмахерская",
    # "маникюр",
    # "барбершоп",
    # "Салон красоты",
    # "бровисты",
    # "lash-мастера",
    "Автосервисы",
    "шиномонтаж"
]

# Город поиска
CITY = "Ярославль"

# ── Файлы вывода ─────────────────────────────────────────────
# OUTPUT_DIR — служебная папка приложения (кэш найденного, чекпоинты, история):
# она всегда лежит рядом с данными приложения.
# RESULTS_DIR — папка результатов; по умолчанию это output/, но пользователь
# может указать свою в настройках («Папка для сохранения»). Двухэтапный
# пайплайн:
#   RAW_DIR       — этап 1 «Сбор»: сырые данные без фильтров (<результаты>/raw/)
#   PROCESSED_DIR — этап 2 «Фильтрация»: обработанные файлы по форматам
try:
    import paths as _paths
    OUTPUT_DIR      = _paths.output_dir()
    RESULTS_DIR     = _paths.results_root()
    RAW_DIR         = _paths.raw_dir()
    PROCESSED_DIR   = _paths.processed_dir()
except Exception:
    OUTPUT_DIR      = "output"
    RESULTS_DIR     = "output"
    RAW_DIR         = os.path.join("output", "raw")
    PROCESSED_DIR   = os.path.join("output", "processed")
OUTPUT_FILENAME = None    # None = авто (город + время)
APPEND_MODE     = False   # True = дозаписывать в существующий файл

OUTPUT_CSV   = False
OUTPUT_JSON  = True
OUTPUT_EXCEL = True
OUTPUT_MAP   = True   # HTML-карта с точками на Яндекс.Картах

# ── Checkpoint / resume ──────────────────────────────────────
# True  — при запуске искать checkpoint-файл и продолжить с места остановки.
# False — начинать сначала (checkpoint всё равно сохраняется для защиты).
RESUME_MODE = False

# ── Фильтры качества ─────────────────────────────────────────

# ── Сетка координат ──────────────────────────────────────────
# Если False — ищет только в центре города.
# Если True  — покрывает круг радиуса GRID_RADIUS_KM с шагом GRID_STEP_KM.
USE_GRID       = False
GRID_RADIUS_KM = 20    # км от центра
GRID_STEP_KM   = 5     # шаг сетки, км

# ── Скорость и надёжность ────────────────────────────────────
MAX_WORKERS = 10        # параллельных потоков при загрузке деталей (10 оптимально для 1 IP)
SEARCH_WORKERS = 2      # параллельных поисковых запросов (категорий)
RETRY_COUNT = 3         # попыток при ошибке сети
RETRY_DELAY = 1.0       # базовая задержка между попытками, сек
DELAY_MIN   = 0.3       # минимальная пауза между запросами деталей
DELAY_MAX   = 0.8       # максимальная пауза

# ── Прокси-ротация ───────────────────────────────────────────
# Список прокси для ротации. Оставьте пустым если не нужно.
# Формат: "http://user:pass@host:port"
PROXIES: list[str] = [
    # "http://user:pass@host:port",
]

# ── Поиск ────────────────────────────────────────────────────
USE_BROWSER  = True   # True = реальный Chrome/Chromium через CDP — единственный
                       # способ загрузки страниц (HTTP-путь удалён: антибот
                       # режет не-браузерные запросы и светит IP/аккаунт)
MAX_PAGES    = 1    # страниц результатов (до 50 организаций каждая)
FETCH_DETAIL = True  # загружать карточку бизнеса для извлечения соцсетей
MAX_CANDIDATES_PER_CITY = 200  # максимум кандидатов на город (0 = без лимита)

# Ключей API Яндекса в приложении нет и не требуется: и поиск организаций,
# и геокодер — платные сервисы, а их бесплатные версии запрещают сохранять
# полученные данные. Страницы читает браузер (см. browser_search.py).
from pathlib import Path

# ── Загрузка .env ─────────────────────────────────────────────
def load_env(file_path=".env"):
    """Загружает переменные из .env файла в окружение.

    Ищет .env сначала в рабочей папке, затем в yandex_maps_parser/ —
    это единственный источник ключей (дубль-файл удалён).
    """
    env_path = Path(file_path)
    if not env_path.exists():
        env_path = Path(__file__).parent / "yandex_maps_parser" / ".env"
    if not env_path.exists():
        say(f"[!] Файл {file_path} не найден, используются системные переменные")
        return False

    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Поддержка значений в кавычках
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Убираем кавычки, если они есть
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    os.environ[key] = value
        return True
    except Exception as e:
        say(f"[x] Ошибка загрузки .env: {e}")
        return False

# Загружаем .env сразу при импорте конфига
# В frozen-сборке .env лежит рядом с exe (paths.env_path), а не в каталоге
# распаковки — подменяем путь до загрузки.
try:
    import paths as _paths
    load_env(str(_paths.env_path()))
except Exception:
    load_env()

# ── ВКонтакте (проверка активности сообществ, этап 2) ────────
# Пользовательский токен с правами wall,groups,offline (vkhost.github.io).
# Не задан → фильтр по активности ВК пропускается с предупреждением.
# Токен только читает данные сообществ — отправки сообщений в приложении нет.
VK_TOKEN: str = os.getenv("VK_TOKEN", "")
