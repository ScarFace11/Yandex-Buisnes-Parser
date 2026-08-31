# ═══════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ парсера Яндекс.Карт
#  Редактируйте этот файл под свои нужды.
# ═══════════════════════════════════════════════════════════════
APP_VERSION = "2.1.0"

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
OUTPUT_DIR      = "output"
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
MIN_RATING  = 0.0   # 0.0 = без фильтра
MIN_REVIEWS = 0     # 0   = без фильтра

# ── Проверка активности ссылок ───────────────────────────────
# True  — делать HEAD-запрос к каждой найденной соцсети,
#         помечать недоступные. Медленнее, но избавляет от мёртвых ссылок.
# False — не проверять (быстро).
VALIDATE_SOCIALS = False

# ── Сетка координат ──────────────────────────────────────────
# Если False — ищет только в центре города.
# Если True  — покрывает круг радиуса GRID_RADIUS_KM с шагом GRID_STEP_KM.
USE_GRID       = False
GRID_RADIUS_KM = 20    # км от центра
GRID_STEP_KM   = 5     # шаг сетки, км

# ── Скорость и надёжность ────────────────────────────────────
MAX_WORKERS = 20        # параллельных потоков при загрузке деталей
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
MAX_PAGES    = 1    # страниц результатов (50 позиций каждая)
FETCH_DETAIL = True  # загружать карточку бизнеса для извлечения соцсетей

# Ключ API Яндекс (для геокодинга и поиска)
# Берётся из переменной окружения YANDEX_API_KEY.
# Задайте её в Replit Secrets или в файле .env (для локальной разработки).
import os
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
load_env()

# ── Получение переменной из .env ─────────────────────────────
# Теперь можно получать переменную через os.getenv()
YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")

if not YANDEX_API_KEY:
    import warnings
    warnings.warn(
        "YANDEX_API_KEY не задан — задайте переменную окружения YANDEX_API_KEY "
        "в файле .env или в системных переменных.",
        stacklevel=2,
    )
