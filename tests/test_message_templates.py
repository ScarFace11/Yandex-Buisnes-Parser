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


# ── API ──────────────────────────────────────────────────────
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


# ── Рассылка VK ──────────────────────────────────────────────
class TestSenderIntegration:
    def test_runner_uses_the_shared_substitute(self):
        src = (ROOT / "vk_sender" / "runner.py").read_text(encoding="utf-8")
        assert "from yandex_maps_parser.message_templates import substitute" in src
        assert "substitute(message_tpl" in src
        assert '.replace("{название_бизнеса}", name)' not in src

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
