# -*- coding: utf-8 -*-
"""«📝 Шаблоны сообщений»: хранение, нормализация, миграции и подстановка.

Шаблоны общие для команды и живут в settings.json; здесь проверяется то, что
не видно в браузере: сев пресетов, лимиты, версии без потери данных,
подстановка переменных (включая старый {название_бизнеса}) и API.
"""
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]

RECORD = {
    "name": "Клининг-Про",
    "city": "Москва",
    "category": "Клининговые услуги",
    "rating": 4.7,
    "reviews_count": 128,
    "address": "ул. Тверская, 1",
    "phone": "+7 495 123-45-67",
    "lead_score": 85,
    "website": "example.com",
    "vk": "https://vk.com/x",
    "telegram": "https://t.me/y",
}


@pytest.fixture()
def tpl_env(tmp_path, monkeypatch):
    """settings.json → tmp: тесты не трогают реальный файл приложения."""
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def client(tpl_env):
    from routes import api as api_mod

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


# ── Хранилище и пресеты ──────────────────────────────────────
class TestStorage:
    def test_defaults_are_seeded_and_saved_on_first_load(self, tpl_env):
        import paths
        import yandex_maps_parser.message_templates as mt

        state = mt.load_templates()
        assert len(state["templates"]) == 5
        assert {t["category"] for t in state["templates"]} == {"vk", "telegram", "whatsapp"}
        assert all(v is None for v in state["active_template_ids"].values())
        assert state["show_missing_as_var"] is False
        assert mt.TEMPLATES_KEY in paths.load_settings()

    def test_save_and_load_round_trip(self, tpl_env):
        import yandex_maps_parser.message_templates as mt

        state, _ = mt.normalize_state({
            "templates": [{"id": "a", "category": "telegram", "name": "X", "text": "{name}"}],
            "active_template_ids": {"telegram": "a"},
        })
        mt.save_templates(state)
        again = mt.load_templates()
        assert [t["id"] for t in again["templates"]] == ["a"]
        assert again["active_template_ids"]["telegram"] == "a"

    def test_empty_list_is_a_valid_placeholder(self, tpl_env):
        import yandex_maps_parser.message_templates as mt

        mt.save_templates(mt.normalize_state({"templates": []})[0])
        assert mt.load_templates()["templates"] == []

    def test_broken_settings_fall_back_to_defaults(self, tpl_env):
        import yandex_maps_parser.message_templates as mt

        (tpl_env / "settings.json").write_text("{битый", encoding="utf-8")
        assert len(mt.load_templates()["templates"]) == 5


# ── Нормализация ─────────────────────────────────────────────
class TestNormalize:
    def test_drops_empty_and_enforces_limits(self):
        import yandex_maps_parser.message_templates as mt

        raw = [
            {"id": "1", "name": "ok", "text": "hi", "category": "weird"},
            {"id": "1", "name": "dup", "text": "hi"},          # дубликат id → новый
            {"id": "", "name": "   ", "text": "hi"},           # пустое имя → выброшен
            {"id": "x", "name": "n", "text": "   "},           # пустой текст → выброшен
            "мусор",
            {"id": "long", "name": "n" * 300, "text": "t" * 9000},
        ]
        out = mt.normalize_templates(raw)
        assert [t["id"] for t in out] == ["1", "tpl_2", "long"]
        assert out[0]["category"] == "vk", "неизвестная категория → vk"
        assert len(out[2]["name"]) == mt.MAX_NAME
        assert len(out[2]["text"]) == mt.MAX_TEXT

    def test_non_list_is_empty(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.normalize_templates("нет") == []
        assert mt.normalize_templates(None) == []
        assert mt.normalize_templates({"templates": []}) == []

    def test_active_ids_keep_only_existing_ones(self):
        import yandex_maps_parser.message_templates as mt

        tmpls = mt.normalize_templates([{"id": "a", "name": "n", "text": "t", "category": "vk"}])
        ids = mt.normalize_active_ids(
            {"vk": "a", "telegram": "ghost", "whatsapp": 123, "bogus": "a"}, tmpls)
        assert ids == {"vk": "a", "telegram": None, "whatsapp": None, "instagram": None}


class TestCustomVariables:
    """Свои переменные: нормализация, лимиты, коллизии со встроенными."""

    def test_ok_variables_survive(self):
        import yandex_maps_parser.message_templates as mt

        out = mt.normalize_custom_variables([
            {"name": "подпись", "value": "С уважением, Иван", "description": "подпись"},
            {"name": "город_клиента", "column": "city", "description": "город"},
        ])
        assert [v["name"] for v in out] == ["подпись", "город_клиента"]
        assert out[0]["value"] == "С уважением, Иван" and out[0]["column"] == ""
        assert out[1]["column"] == "city" and out[1]["value"] == ""

    def test_reserved_and_broken_names_dropped(self):
        import yandex_maps_parser.message_templates as mt

        out = mt.normalize_custom_variables([
            {"name": "name", "value": "x"},          # встроенная
            {"name": "название_бизнеса", "value": "x"},  # алиас
            {"name": "со пробел", "value": "x"},       # пробел в имени
            {"name": "", "value": "x"},               # пустое
            {"name": "bad!"},                          # пустое значение без столбца
            "мусор",
        ])
        assert out == []

    def test_duplicates_case_insensitive(self):
        import yandex_maps_parser.message_templates as mt

        out = mt.normalize_custom_variables([
            {"name": "Подпись", "value": "A"},
            {"name": "подпись", "value": "B"},
        ])
        assert len(out) == 1 and out[0]["value"] == "A"

    def test_limits_enforced(self):
        import yandex_maps_parser.message_templates as mt

        out = mt.normalize_custom_variables([
            {"name": "n" * 100, "value": "x"},
            {"name": "ok", "value": "v" * 5000, "description": "d" * 999},
        ])
        assert out == [] or out[0]["name"] != "n" * 100
        long = next(v for v in out if v["name"] == "ok")
        assert len(long["value"]) == mt.MAX_VAR_VALUE
        assert len(long["description"]) == mt.MAX_VAR_DESC

    def test_cap_on_total_count(self):
        import yandex_maps_parser.message_templates as mt

        raw = [{"name": f"var_{i}", "value": "x"} for i in range(mt.MAX_CUSTOM_VARS + 10)]
        assert len(mt.normalize_custom_variables(raw)) == mt.MAX_CUSTOM_VARS

    def test_non_list_is_empty(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.normalize_custom_variables(None) == []
        assert mt.normalize_custom_variables("мусор") == []


# ── Версии и миграции ────────────────────────────────────────
class TestMigrations:
    def test_missing_version_is_treated_as_current(self):
        import yandex_maps_parser.message_templates as mt

        state, warnings = mt.normalize_state(
            {"templates": [{"id": "a", "name": "n", "text": "t"}]})
        assert state["version"] == mt.CURRENT_TEMPLATE_VERSION
        assert warnings == []

    def test_newer_version_keeps_data_with_a_warning(self):
        import yandex_maps_parser.message_templates as mt

        state, warnings = mt.normalize_state({
            "version": 99,
            "templates": [{"id": "a", "name": "n", "text": "t"}],
        })
        assert len(state["templates"]) == 1, "данные из новой сборки не теряем"
        assert warnings and "99" in warnings[0]

    def test_non_dict_store_is_normalized(self):
        import yandex_maps_parser.message_templates as mt

        state, warnings = mt.normalize_state("мусор")
        assert state["templates"] == []
        assert warnings == []


# ── Подстановка ──────────────────────────────────────────────
class TestSubstitute:
    def test_all_variables(self):
        import yandex_maps_parser.message_templates as mt

        text = ("{name}|{city}|{category}|{rating}|{reviews}|{address}|{phone}|"
                "{lead_score}|{website}|{socials}")
        assert mt.substitute(text, RECORD) == (
            "Клининг-Про|Москва|Клининговые услуги|4.7|128|ул. Тверская, 1|"
            "+7 495 123-45-67|85|example.com|VK, TG"
        )

    def test_aliases_keep_the_old_vk_syntax(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("{название_бизнеса}", RECORD) == "Клининг-Про"
        assert mt.substitute("{reviews_count}", RECORD) == "128"

    def test_empty_value_degrades_to_dash(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("a {city} b", {}) == "a — b"

    def test_show_missing_as_var_keeps_placeholder(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("{city}", {}, show_missing_as_var=True) == "{city}"

    def test_unknown_variable_is_left_untouched(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("{nope} {city}", RECORD) == "{nope} Москва"
        assert mt.substitute("{nope}", {}) == "{nope}"

    def test_specials_in_data_are_inserted_verbatim(self):
        import yandex_maps_parser.message_templates as mt

        # Текст сообщения — не HTML и не URL: экранировать нечего, символы как есть.
        assert mt.substitute("{name}", {"name": "C++ & [акция]"}) == "C++ & [акция]"


class TestSubstituteCustom:
    """Свои переменные в подстановке: статик, столбец, приоритет."""

    CVARS = [
        {"name": "подпись", "column": "", "value": "С уважением, Иван"},
        {"name": "город_клиента", "column": "city", "value": ""},
        {"name": "пустая", "column": "", "value": ""},
    ]

    def test_static_text_value(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("Привет! {подпись}", {}, custom_variables=self.CVARS) \
            == "Привет! С уважением, Иван"

    def test_column_value_taken_from_record(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("{город_клиента}", RECORD, custom_variables=self.CVARS) \
            == "Москва"

    def test_custom_overrides_builtin(self):
        import yandex_maps_parser.message_templates as mt

        cvars = [{"name": "name", "column": "", "value": "НЕ встроенная"}]
        assert mt.substitute("{name}", RECORD, custom_variables=cvars) == "НЕ встроенная"

    def test_empty_value_degrades_to_dash(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("a {пустая} b", {}, custom_variables=self.CVARS) == "a — b"
        # Пустой столбец в записи — то же правило.
        assert mt.substitute("{город_клиента}", {}, custom_variables=self.CVARS) == "—"

    def test_show_missing_keeps_placeholder(self):
        import yandex_maps_parser.message_templates as mt

        assert mt.substitute("{пустая}", {}, True, custom_variables=self.CVARS) == "{пустая}"


class TestSubstituteSpecial:
    """Служебные переменные: вычисляются в момент подстановки."""

    def test_date_and_time_formats(self):
        import yandex_maps_parser.message_templates as mt
        from datetime import datetime

        out = mt.substitute("{дата}|{время}", {})
        now = datetime.now()
        assert out == now.strftime("%d.%m.%Y") + "|" + now.strftime("%H:%M")

    def test_greeting_by_hour(self):
        import yandex_maps_parser.message_templates as mt
        from datetime import datetime

        hour = datetime.now().hour
        expected = ("Доброй ночи" if hour < 5
                    else "Доброе утро" if hour < 12
                    else "Добрый день" if hour < 18
                    else "Добрый вечер" if hour < 22
                    else "Доброй ночи")
        assert mt.substitute("{приветствие}!", {}) == expected + "!"

    def test_specials_are_reserved(self):
        import yandex_maps_parser.message_templates as mt

        out = mt.normalize_custom_variables([
            {"name": "дата", "value": "x"},
            {"name": "приветствие", "value": "x"},
        ])
        assert out == []

    def test_custom_overrides_special(self):
        import yandex_maps_parser.message_templates as mt

        cvars = [{"name": "дата", "column": "", "value": "своё"}]
        assert mt.substitute("{дата}", {}, custom_variables=cvars) == "своё"


# ── API ──────────────────────────────────────────────────────
# ── Случайный выбор шаблонов ─────────────────────────────────
class TestPickModes:
    def test_normalize_modes_defaults_to_single(self):
        from yandex_maps_parser import message_templates as mt

        assert mt.normalize_modes(None) == {c: "single" for c in mt.CATEGORIES}
        assert mt.normalize_modes({"vk": "random"})["vk"] == "random"
        assert mt.normalize_modes({"vk": "мусор", "telegram": 42})["vk"] == "single"
        assert mt.normalize_modes({"не-категория": "random"})["vk"] == "single"

    def test_normalize_random_ids_drops_foreign_and_broken(self):
        from yandex_maps_parser import message_templates as mt

        tpls = mt.normalize_templates(mt.DEFAULT_TEMPLATES)
        raw = {
            "vk": ["tpl_vk_intro", "tpl_tg_short", "tpl_vk_intro", "битый", "", None],
            "telegram": "мусор",
            "whatsapp": ["tpl_wa_official"],
        }
        out = mt.normalize_random_ids(raw, tpls)
        assert out["vk"] == ["tpl_vk_intro"]          # чужая категория и мусор — вон
        assert out["telegram"] == []                   # не-список → пусто
        assert out["whatsapp"] == ["tpl_wa_official"]

    def test_deleted_template_pruned_from_random_set(self):
        from yandex_maps_parser import message_templates as mt

        tpls = [t for t in mt.normalize_templates(mt.DEFAULT_TEMPLATES) if t["id"] != "tpl_vk_intro"]
        out = mt.normalize_random_ids({"vk": ["tpl_vk_intro", "tpl_vk_benefit"]}, tpls)
        assert out["vk"] == ["tpl_vk_benefit"]

    def test_old_settings_get_defaults(self, tpl_env):
        from yandex_maps_parser import message_templates as mt

        old = {
            "version": 1,
            "templates": mt.DEFAULT_TEMPLATES,
            "active_template_ids": {},
            "show_missing_as_var": False,
        }
        state, _ = mt.normalize_state(old)
        assert state["template_modes"] == {c: "single" for c in mt.CATEGORIES}
        assert state["random_template_ids"] == {c: [] for c in mt.CATEGORIES}
        assert state["avoid_repeats"] is False

    def test_v1_store_gains_empty_custom_variables(self, tpl_env):
        from yandex_maps_parser import message_templates as mt

        old = {"version": 1, "templates": mt.DEFAULT_TEMPLATES}
        state, _ = mt.normalize_state(old)
        assert state["custom_variables"] == []

    def test_pick_random_text_contract(self):
        from yandex_maps_parser import message_templates as mt

        assert mt.pick_random_text([]) is None
        assert mt.pick_random_text(["a"]) == "a"
        # avoid_repeats при одном шаблоне — всегда он же (исключение опустошило).
        assert mt.pick_random_text(["a"], "a", True) == "a"
        # avoid_repeats при двух — строго чередование.
        assert all(mt.pick_random_text(["a", "b"], "a", True) == "b" for _ in range(20))
        # Без avoid — оба варианта достижимы.
        assert {mt.pick_random_text(["a", "b"]) for _ in range(40)} == {"a", "b"}

    def test_resolve_pick_state(self, tpl_env):
        from yandex_maps_parser import message_templates as mt

        state = mt.default_state()
        state["template_modes"]["vk"] = "random"
        state["random_template_ids"]["vk"] = ["tpl_vk_intro", "tpl_vk_benefit"]
        state["avoid_repeats"] = True
        pick = mt.resolve_pick_state("vk", state)
        assert pick["mode"] == "random" and pick["avoid"] is True
        assert pick["names"] == ["Первое знакомство", "С акцентом на выгоду"]
        assert len(pick["texts"]) == 2
        # Не настроенная категория — single и пустой набор.
        empty = mt.resolve_pick_state("telegram", state)
        assert empty["mode"] == "single" and empty["texts"] == []


class TestApi:
    def test_get_seeds_defaults(self, client):
        body = client.get("/templates").get_json()
        assert body["ok"] is True
        assert len(body["templates"]) == 5

    def test_post_normalizes_and_persists(self, client):
        r = client.post("/templates", json={
            "templates": [{"id": "a", "category": "telegram", "name": "T", "text": "{name}"}],
            "active_template_ids": {"telegram": "a"},
            "show_missing_as_var": True,
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["templates"][0]["id"] == "a"
        assert body["active_template_ids"]["telegram"] == "a"
        assert body["show_missing_as_var"] is True
        again = client.get("/templates").get_json()
        assert [t["id"] for t in again["templates"]] == ["a"]

    def test_post_rejects_non_list(self, client):
        r = client.post("/templates", json={"templates": "nope"})
        assert r.status_code == 400
        assert r.get_json()["ok"] is False

    def test_reset_returns_the_presets(self, client):
        client.post("/templates", json={"templates": []})
        assert client.get("/templates").get_json()["templates"] == []
        body = client.post("/templates/reset").get_json()
        assert body["ok"] is True
        assert len(body["templates"]) == 5

    def test_bulk_urls_adds_text_when_template_given(self, client, monkeypatch):
        from routes import api as api_mod

        recs = [{"name": "Клининг-Про", "city": "Москва",
                 "vk": "https://vk.com/x", "yandex_maps_url": ""}]
        monkeypatch.setattr(api_mod, "_collect_records", lambda *a, **k: list(recs))
        monkeypatch.setattr(api_mod, "_load_reviewed", lambda: {})
        data = client.post("/bulk/urls", json={
            "view": "raw", "social": "vk", "count": 5,
            "template": "Привет, {name}! Ваш город — {city}.",
        }).get_json()
        assert data["urls"][0]["text"] == "Привет, Клининг-Про! Ваш город — Москва."

    def test_bulk_urls_without_template_keeps_the_contract(self, client, monkeypatch):
        from routes import api as api_mod

        recs = [{"name": "К", "vk": "https://vk.com/x", "yandex_maps_url": ""}]
        monkeypatch.setattr(api_mod, "_collect_records", lambda *a, **k: list(recs))
        monkeypatch.setattr(api_mod, "_load_reviewed", lambda: {})
        data = client.post("/bulk/urls", json={
            "view": "raw", "social": "vk", "count": 5}).get_json()
        assert "text" not in data["urls"][0]

    def test_post_round_trips_pick_settings(self, client):
        r = client.post("/templates", json={
            "templates": [
                {"id": "a", "category": "vk", "name": "A", "text": "xA"},
                {"id": "b", "category": "vk", "name": "B", "text": "xB"},
            ],
            "template_modes": {"vk": "random"},
            "random_template_ids": {"vk": ["a", "b"]},
            "avoid_repeats": True,
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["template_modes"]["vk"] == "random"
        assert body["random_template_ids"]["vk"] == ["a", "b"]
        assert body["avoid_repeats"] is True
        again = client.get("/templates").get_json()
        assert again["random_template_ids"]["vk"] == ["a", "b"]
        assert again["avoid_repeats"] is True

    def test_post_round_trips_custom_variables(self, client):
        r = client.post("/templates", json={
            "templates": [{"id": "a", "category": "vk", "name": "A", "text": "{подпись}"}],
            "custom_variables": [
                {"name": "подпись", "value": "Иван", "description": "подпись"},
                {"name": "name", "value": "занято"},   # встроенная — вон
            ],
        })
        body = r.get_json()
        assert len(body["custom_variables"]) == 1
        assert body["custom_variables"][0]["name"] == "подпись"
        again = client.get("/templates").get_json()
        assert again["custom_variables"][0]["value"] == "Иван"

    def test_post_invalid_ids_are_dropped(self, client):
        r = client.post("/templates", json={
            "templates": [{"id": "a", "category": "vk", "name": "A", "text": "xA"}],
            "template_modes": {"vk": "мусор"},
            "random_template_ids": {"vk": ["a", "нет-такого", "tpl_tg_short"]},
        })
        body = r.get_json()
        assert body["template_modes"]["vk"] == "single"
        assert body["random_template_ids"]["vk"] == ["a"]

    def test_bulk_urls_random_gives_per_record_text_and_name(self, client, monkeypatch):
        from routes import api as api_mod

        # Сеем два шаблона и включаем random для vk.
        client.post("/templates", json={
            "templates": [
                {"id": "a", "category": "vk", "name": "Первое", "text": "Текст-А для {name}"},
                {"id": "b", "category": "vk", "name": "Второе", "text": "Текст-Б для {name}"},
            ],
            "template_modes": {"vk": "random"},
            "random_template_ids": {"vk": ["a", "b"]},
        })
        recs = [{"name": f"Фирма-{i}", "vk": f"https://vk.com/{i}", "yandex_maps_url": ""}
                for i in range(8)]
        monkeypatch.setattr(api_mod, "_collect_records", lambda *a, **k: list(recs))
        monkeypatch.setattr(api_mod, "_load_reviewed", lambda: {})
        data = client.post("/bulk/urls", json={
            "view": "raw", "social": "vk", "count": 10,
            "template_ids": ["a", "b"], "tpl_avoid_repeats": True,
        }).get_json()
        urls = data["urls"]
        assert len(urls) == 8
        for item in urls:
            assert item["tpl_name"] in ("Первое", "Второе")
            assert item["text"].startswith("Текст-")
            assert item["text"].endswith(item["name"])
        # avoid_repeats: тот же текст не повторяется дважды подряд.
        for prev, cur in zip(urls, urls[1:]):
            assert prev["text"] != cur["text"]

    def test_bulk_urls_random_with_empty_pool_falls_back(self, client, monkeypatch):
        from routes import api as api_mod

        recs = [{"name": "К", "vk": "https://vk.com/x", "yandex_maps_url": ""}]
        monkeypatch.setattr(api_mod, "_collect_records", lambda *a, **k: list(recs))
        monkeypatch.setattr(api_mod, "_load_reviewed", lambda: {})
        # id не резолвятся (набор не настроен) — старый контракт без текста.
        data = client.post("/bulk/urls", json={
            "view": "raw", "social": "vk", "count": 5,
            "template_ids": ["нет-такого"],
        }).get_json()
        assert "text" not in data["urls"][0]


# ── Рассылка VK ────────────────────────────────────────────


# ── Рассылка VK ──────────────────────────────────────────────
class TestSenderIntegration:
    def test_runner_uses_the_shared_substitute(self):
        src = (ROOT / "vk_sender" / "runner.py").read_text(encoding="utf-8")
        assert "from yandex_maps_parser.message_templates import" in src
        assert "substitute" in src
        assert "substitute(message_tpl" in src
        assert '.replace("{название_бизнеса}", name)' not in src

    def test_runner_supports_random_ids(self):
        src = (ROOT / "vk_sender" / "runner.py").read_text(encoding="utf-8")
        assert "message_tpl_ids" in src
        assert "pick_random_text" in src
        assert "Использовано шаблонов" in src

    def test_record_cols_maps_known_headers(self):
        from vk_sender import excel_manager as xm

        class _Cell:
            def __init__(self, value, column):
                self.value = value
                self.column = column

        class _Ws:
            def __getitem__(self, key):
                return [_Cell("Название", 1), _Cell("Город", 2),
                        _Cell("ВКонтакте", 3), _Cell("Отправлено", 4)]

        cols = xm._record_cols(_Ws())
        assert cols["name"] == 1 and cols["city"] == 2 and cols["vk"] == 3
        assert "reviewed" not in cols and len(cols) == 3
