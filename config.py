# ═══════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ парсера Яндекс.Карт
import os
import sys

# Вывод в UTF-8 и без падений: конфиг импортируется первым в любом запуске, а перенаправленный stdout на русской Windows — это cp1251, где любое сообщение с эмодзи роняло старт (см. console_io).
from console_io import enable_utf8, say

enable_utf8()

# Версия приложения. Для публичного релиза — без суффиксов: "2.3.4.2".
APP_VERSION = "2.3.4.2"


def is_dev_build() -> bool:
    """True для внутренней сборки (версия с суффиксом «-dev»/«-beta»)."""
    v = str(APP_VERSION).strip().lower()
    return v.endswith(("-dev", "-beta")) or "-dev." in v or "-beta." in v


# ── Минимально допустимая версия ──────────────────────────────
SKIP_MIN_VERSION_ENV = "YP_SKIP_MIN_VERSION"


def skips_min_version() -> bool:
    """True для сборок, которым порог минимальной версии не мешает."""
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


# Порт по умолчанию для внутренней сборки — 5010 вместо 5000, чтобы она не боролась за один порт с публичной.
DEV_PORT = 5010

# macOS: порт 5000 занят системным AirPlay Receiver (macOS 12+), поэтому у .app-сборки свой порт — иначе первый же запуск упирался бы в «порт занят».
MAC_PORT = 5050


def app_port() -> int:
    """HTTP-порт: переменная YP_PORT → внутренняя сборка 5010 → macOS 5050 → 5000. Порядок важен: у внутренней сборки свой порт на любой системе, а публичная сборка на macOS не может занять 5000 (там слушает AirPlay Receiver)."""
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
SEARCH_QUERIES = [
    # "кафе", "ресторан", "парикмахерская", "маникюр", "барбершоп", "Салон красоты", "бровисты", "lash-мастера",
    "Автосервисы",
    "шиномонтаж"
]

# Город поиска
CITY = "Ярославль"

# ── Файлы вывода ─────────────────────────────────────────────
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
RESUME_MODE = False

# ── Фильтры качества ─────────────────────────────────────────

# ── Сетка координат ──────────────────────────────────────────
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
PROXIES: list[str] = [
    # "http://user:pass@host:port",
]

# ── Поиск ────────────────────────────────────────────────────
USE_BROWSER  = True   # True = реальный Chrome/Chromium через CDP — единственный
                       # способ загрузки страниц (HTTP-путь удалён: антибот режет не-браузерные запросы и светит IP/аккаунт)
MAX_PAGES    = 1    # страниц результатов (до 50 организаций каждая)
FETCH_DETAIL = True  # загружать карточку бизнеса для извлечения соцсетей
MAX_CANDIDATES_PER_CITY = 200  # максимум кандидатов на город (0 = без лимита)

# Ключей API Яндекса в приложении нет и не требуется: и поиск организаций, и геокодер — платные сервисы, а их бесплатные версии запрещают сохранять полученные данные.
from pathlib import Path

# ── Загрузка .env ─────────────────────────────────────────────
def load_env(file_path=".env"):
    """Загружает переменные из .env файла в окружение."""
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

# Загружаем .env сразу при импорте конфига В frozen-сборке .env лежит рядом с exe (paths.env_path), а не в каталоге распаковки — подменяем путь до загрузки.
try:
    import paths as _paths
    load_env(str(_paths.env_path()))
except Exception:
    load_env()

# ── ВКонтакте (проверка активности сообществ, этап 2) ────────
VK_TOKEN: str = os.getenv("VK_TOKEN", "")
