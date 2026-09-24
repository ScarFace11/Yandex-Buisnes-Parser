"""«🚫 Исключить по словам»: парсинг, поиск, лимиты и место в этапе 2.

Blacklist — самый «прямой» фильтр: слово, которое исключает компанию, снимает
запись до остальных проверок, поэтому ошибка здесь тихо вырезает лишних
клиентов из отчёта. Проверяем ровно это:

1. Парсинг слова: сплит по `,;\n`, trim, lowercase, пустые, дубликаты, лимиты.
2. Поиск подстроки в названии/категории/описании — регистр не важен, спецсимволы
   экранируются (`C++` и `[акция]` ищутся буквально).
3. Порядок в apply_filters: после объединения филиалов, до остальных фильтров,
   blacklist побеждает соцсети/оценку/сайты.
4. Счётчик и строка журнала «🚫 Blacklist: исключено N компаний».
5. POST /preview-blacklist считает исключения той же логикой.
"""
import pytest
from flask import Flask


RAW_ROWS = [
    {"city": "Уфа", "name": "Кофейня Ромашка", "query": "кафе", "category": "Кофейня"},
    {"city": "Уфа", "name": "Кофейня Франшиза", "query": "кафе", "category": "Кофейня"},
    {"city": "Уфа", "name": "Бар Виноград", "query": "кафе", "category": "Бар"},
]


def _save_raw(tmp_path, rows=None):
    from yandex_maps_parser.exporters import save_excel
    path = tmp_path / "raw.xlsx"
    save_excel(rows if rows is not None else RAW_ROWS, str(path))
    return str(path)


# ── 1. Парсинг ───────────────────────────────────────────────

class TestParseWords:
    def test_split_trim_lowercase_and_dedupe(self):
        from yandex_maps_parser.processing import parse_blacklist_words
        words = parse_blacklist_words("Франшиза, VIP; сеть\nдубль,  ФРАНШИЗА ,,")
        assert words == ["франшиза", "vip", "сеть", "дубль"]

    def test_accepts_list_and_garbage(self):
        from yandex_maps_parser.processing import parse_blacklist_words
        assert parse_blacklist_words(["Франшиза", "vip"]) == ["франшиза", "vip"]
        assert parse_blacklist_words(None) == []
        assert parse_blacklist_words(42) == []
        assert parse_blacklist_words({"words": ["франшиза"]}) == []
        assert parse_blacklist_words(["", "   ", "\n"]) == []

    def test_limits_words_and_length(self):
        from yandex_maps_parser.processing import (
            BLACKLIST_MAX_LEN, BLACKLIST_MAX_WORDS, parse_blacklist_words,
        )
        long_word = "я" * (BLACKLIST_MAX_LEN + 1)
        assert parse_blacklist_words(["ок", long_word, "x" * BLACKLIST_MAX_LEN]) == [
            "ок", "x" * BLACKLIST_MAX_LEN,
        ]
        many = [f"слово{i}" for i in range(BLACKLIST_MAX_WORDS + 25)]
        assert len(parse_blacklist_words(many)) == BLACKLIST_MAX_WORDS

    def test_is_idempotent(self):
        """Повторный прогон не меняет список — его можно сохранять как есть."""
        from yandex_maps_parser.processing import parse_blacklist_words
        once = parse_blacklist_words("Франшиза, vip")
        assert parse_blacklist_words(once) == once


# ── 2. Поиск ─────────────────────────────────────────────────

class TestMatcher:
    def test_substring_in_name_category_and_description(self):
        from yandex_maps_parser.processing import blacklist_matcher
        hit = blacklist_matcher(["франшиза"])
        assert hit({"name": "Кофейня Франшиза"}) is True
        assert hit({"category": "ФРАНШИЗА кофе"}) is True
        assert hit({"description": "работаем по франшиза"}) is True
        assert hit({"name": "Кофейня Ромашка", "category": "Кофейня"}) is False

    def test_empty_list_returns_no_matcher(self):
        from yandex_maps_parser.processing import blacklist_matcher
        assert blacklist_matcher([]) is None
        assert blacklist_matcher(None) is None

    def test_special_characters_are_escaped(self):
        """`C++` ищется как текст, а не как регулярка: иначе `[акция]` совпал бы
        с любым символом из класса, а `кофе.` — с «кофе» и «кофех»."""
        from yandex_maps_parser.processing import blacklist_matcher
        assert blacklist_matcher(["c++"])({"name": "Салон C++"}) is True
        assert blacklist_matcher(["[акция]"])({"name": "[акция] магазин"}) is True
        assert blacklist_matcher(["[акция]"])({"name": "акция магазин"}) is False
        assert blacklist_matcher(["кофе.ру"])({"name": "кофеХру"}) is False

    def test_missing_fields_do_not_crash(self):
        from yandex_maps_parser.processing import blacklist_matcher
        hit = blacklist_matcher(["франшиза"])
        assert hit({}) is False
        assert hit({"name": None}) is False


# ── 3–4. Место в этапе 2 ─────────────────────────────────────

class TestApplyFilters:
    def test_words_are_dropped_and_counted(self, tmp_path):
        from yandex_maps_parser import processing
        logs = []
        res = processing.apply_filters(
            [_save_raw(tmp_path)],
            {"blacklist_words": ["франшиза"]},
            log_fn=lambda level, msg: logs.append((level, msg)),
        )
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Кофейня Ромашка", "Бар Виноград"}
        assert res["count"] == 2
        assert res["blacklist_excluded"] == 1
        assert any("🚫 Blacklist: исключено 1 компаний" in msg for _, msg in logs)

    def test_blacklist_wins_over_the_other_filters(self, tmp_path):
        """Запись, которую пропустил бы social_mode=with_socials, снимается
        словом: «исключено» не должно зависеть от остальных галочек."""
        from yandex_maps_parser import processing
        rows = [{"city": "Уфа", "name": "Franchise Bar", "query": "кафе",
                 "category": "Бар", "vk": "https://vk.com/fb"}]
        raw = _save_raw(tmp_path, rows)
        # Контроль: без списка запись проходит фильтр по соцсетям.
        keep = processing.apply_filters([raw], {"social_mode": "with_socials"})
        assert keep["count"] == 1
        res = processing.apply_filters(
            [raw],
            {"social_mode": "with_socials", "blacklist_words": ["franchise"]},
        )
        assert res.get("empty") is True and res["count"] == 0
        assert res["blacklist_excluded"] == 1

    def test_runs_after_the_chain_merge(self, tmp_path):
        """Сначала объединение филиалов, потом blacklist: две ветки одной сети —
        это одна запись, а не две («исключено» не должно задваиваться)."""
        from yandex_maps_parser import processing
        rows = [
            {"city": "Уфа", "name": "Сеть Кофе", "query": "кафе", "phone": "+7 111"},
            {"city": "Уфа", "name": "Сеть Кофе", "query": "кафе", "phone": "+7 222"},
        ]
        res = processing.apply_filters(
            [_save_raw(tmp_path, rows)],
            {"collapse_chains": True, "blacklist_words": ["сеть"]},
        )
        assert res.get("empty") is True
        assert res["blacklist_excluded"] == 1
        assert res["count"] == 0

    def test_without_a_list_nothing_changes(self, tmp_path):
        from yandex_maps_parser import processing
        logs = []
        res = processing.apply_filters(
            [_save_raw(tmp_path)],
            {},
            log_fn=lambda level, msg: logs.append((level, msg)),
        )
        assert res["count"] == 3
        assert res["blacklist_excluded"] == 0
        assert not any("Blacklist" in msg for _, msg in logs)

    def test_direct_and_network_spellings_agree(self, tmp_path):
        """Строку и список нормализует один и тот же парсер."""
        from yandex_maps_parser import processing
        raw = _save_raw(tmp_path)
        by_list = processing.apply_filters([raw], {"blacklist_words": ["франшиза"]})
        by_string = processing.apply_filters([raw], {"blacklist_words": "ФРАНШИЗА;"})
        assert by_list["count"] == by_string["count"] == 2
        assert by_list["blacklist_excluded"] == by_string["blacklist_excluded"] == 1


# ── 5. POST /preview-blacklist ───────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    from routes import api as api_mod

    rows = [
        {"name": "Кофейня Франшиза", "category": "Кофейня"},
        {"name": "Кофейня Ромашка", "category": "Кофейня"},
        {"name": "Бар Виноград", "category": "Бар"},
        {"name": "Бар VIP", "category": "Бар"},
    ]
    monkeypatch.setattr(api_mod, "_collect_records",
                        lambda view, rel_file=None, scope="current": list(rows))
    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


class TestPreviewBlacklist:
    def test_counts_excluded_and_remaining(self, client):
        resp = client.post("/preview-blacklist", json={"words": ["франшиза", "VIP"]})
        data = resp.get_json()
        assert data["ok"] is True
        assert data["words"] == ["франшиза", "vip"]
        assert data["total"] == 4
        assert data["excluded"] == 2
        assert data["remaining"] == 2

    def test_empty_list_excludes_nothing(self, client):
        data = client.post("/preview-blacklist", json={"words": []}).get_json()
        assert (data["excluded"], data["total"], data["remaining"]) == (0, 4, 4)

    def test_thin_body_is_safe(self, client):
        data = client.post("/preview-blacklist", json={}).get_json()
        assert data["ok"] is True and data["excluded"] == 0

    def test_matches_the_pipeline_logic(self, client):
        """Счётчик в подсказке и результат этапа 2 — одна и та же логика."""
        from yandex_maps_parser.processing import blacklist_matcher, parse_blacklist_words
        words = parse_blacklist_words("франшиза, vip")
        hit = blacklist_matcher(words)
        mine = sum(1 for r in [
            {"name": "Кофейня Франшиза", "category": "Кофейня"},
            {"name": "Кофейня Ромашка", "category": "Кофейня"},
            {"name": "Бар Виноград", "category": "Бар"},
            {"name": "Бар VIP", "category": "Бар"},
        ] if hit(r))
        assert client.post("/preview-blacklist", json={"words": words}).get_json()["excluded"] == mine
