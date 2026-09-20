# ═══════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ парсера Яндекс.Карт
#  Редактируйте этот файл под свои нужды.
# ═══════════════════════════════════════════════════════════════
import os
import sys

# Версия приложения. Для публичного релиза — без суффиксов: "2.3.1".
APP_VERSION = "2.3.1"


def is_dev_build() -> bool:
    """True для внутренней сборки (версия с суффиксом «-dev»/«-beta»)."""
    v = str(APP_VERSION).strip().lower()
    return v.endswith(("-dev", "-beta")) or "-dev." in v or "-beta." in v


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
# Из frozen-сборки (.exe) output/ указывает на папку рядом с exe.
# Двухэтапный пайплайн:
#   RAW_DIR       — этап 1 «Сбор»: сырые данные без фильтров (output/raw/)
#   PROCESSED_DIR — этап 2 «Фильтрация»: обработанные файлы по форматам
try:
    import paths as _paths
    OUTPUT_DIR      = _paths.output_dir()
    RAW_DIR         = _paths.raw_dir()
    PROCESSED_DIR   = _paths.processed_dir()
except Exception:
    OUTPUT_DIR      = "output"
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
USE_BROWSER  = True   # True = Playwright для detail-страниц (быстро, без throttling)
                       # False = httpx (требует прокси для скорости)
MAX_PAGES    = 1    # страниц результатов (50 позиций каждая)
FETCH_DETAIL = True  # загружать карточку бизнеса для извлечения соцсетей
MAX_CANDIDATES_PER_CITY = 200  # максимум кандидатов на город (0 = без лимита)

# Ключ API Яндекс (для геокодинга и поиска)
# Берётся из переменной окружения YANDEX_API_KEY.
# Задайте её в Replit Secrets или в файле .env (для локальной разработки).
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
        print(f"⚠️  Файл {file_path} не найден, используются системные переменные")
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
        print(f"❌ Ошибка загрузки .env: {e}")
        return False

# Загружаем .env сразу при импорте конфига
# В frozen-сборке .env лежит рядом с exe (paths.env_path), а не в каталоге
# распаковки — подменяем путь до загрузки.
try:
    import paths as _paths
    load_env(str(_paths.env_path()))
except Exception:
    load_env()

# ── Получение переменной из .env ─────────────────────────────
# Теперь можно получать переменную через os.getenv()
YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")

# ── 2GIS (альтернативный источник данных) ────────────────────
# Бесплатный демо-ключ: https://dev.2gis.ru → Platform Manager → создать ключ.
# Ключ должен иметь разрешение на Places API (поиск организаций).
TWOGIS_API_KEY: str = os.getenv("TWOGIS_API_KEY", "")

# ── ВКонтакте (проверка активности сообществ, этап 2) ────────
# Пользовательский токен с правами wall,groups,offline (vkhost.github.io).
# Не задан → фильтр по активности ВК пропускается с предупреждением.
VK_TOKEN: str = os.getenv("VK_TOKEN", "")

if not YANDEX_API_KEY:
    import warnings
    warnings.warn(
        "YANDEX_API_KEY не задан — задайте переменную окружения YANDEX_API_KEY "
        "в файле .env или в системных переменных.",
        stacklevel=2,
    )
