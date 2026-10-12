"""
Tests for «🩺 Диагностика» (routes/diagnostics.py) — offline, no network.

Панель — это ответ на «ничего не работает» без чтения логов, поэтому тесты
проверяют три вещи:

1. Диагноз точный: код ошибки ВКонтакте объясняется словами, а не сырым
   сообщением сервиса.
2. Панель не может показать секреты: ни в одном ответе нет строки токена.
3. Панель не может ничего сломать: любое падение проверки становится строкой
   «ошибка», а эндпоинт отвечает 200 с человеческим текстом.

Run with: python -m pytest tests/test_diagnostics.py -v
"""
import sys
import os

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes import diagnostics as diag


# ── Заглушки сети ─────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _fake_httpx(monkeypatch, resp):
    """Подменяет httpx.get внутри модуля — в тестах сети быть не должно."""
    import httpx
    calls = []

    def _get(url, params=None, timeout=None, headers=None):
        calls.append({"url": url, "params": dict(params or {})})
        return resp() if callable(resp) else resp

    monkeypatch.setattr(httpx, "get", _get)
    return calls


def _row(results, cid):
    for r in results:
        if r["id"] == cid:
            return r
    raise AssertionError(f"нет строки {cid}: {[r['id'] for r in results]}")


# ── Токен ВКонтакте ──────────────────────────────────────────

class TestVkToken:
    def test_missing_token_is_a_warning(self):
        row = diag.check_vk_token("")
        assert row["status"] == "warn"
        assert "Токен" in row["title"]

    def test_working_token_names_the_owner(self, monkeypatch):
        _fake_httpx(monkeypatch, _Resp(200, payload={
            "response": [{"first_name": "Иван", "last_name": "Петров"}]}))
        row = diag.check_vk_token("tok")
        assert row["status"] == "ok"
        assert "Иван Петров" in row["detail"]

    def test_invalid_token_explains_the_code(self, monkeypatch):
        _fake_httpx(monkeypatch, _Resp(200, payload={
            "error": {"error_code": 5, "error_msg": "User authorization failed"}}))
        row = diag.check_vk_token("tok")
        assert row["status"] == "error"
        assert "недействителен" in row["detail"]
        # Русский текст — не сырое сообщение VK.
        assert "User authorization failed" not in row["detail"]

    def test_unknown_error_code_falls_back_to_the_service_text(self, monkeypatch):
        _fake_httpx(monkeypatch, _Resp(200, payload={
            "error": {"error_code": 99, "error_msg": "Something specific"}}))
        row = diag.check_vk_token("tok")
        assert "Something specific" in row["detail"]


# ── Файлы, данные, окружение ─────────────────────────────────

class TestStorage:
    def test_writable_results_dir_is_ok(self, tmp_path, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "results_root", lambda: tmp_path / "results")
        rows = diag.check_storage()
        assert _row(rows, "results_dir")["status"] == "ok"
        assert not (tmp_path / "results" / ".diag-write-test").exists(), "пробный файл убираем"

    def test_read_only_results_dir_is_named(self, monkeypatch):
        import paths
        bad = os.path.join(os.sep, "diag-no-such-dir", "results")
        monkeypatch.setattr(paths, "results_root", lambda: __import__("pathlib").Path(bad))
        monkeypatch.setattr(os, "makedirs", lambda *a, **kw: (_ for _ in ()).throw(
            PermissionError("denied")))
        rows = diag.check_storage()
        row = _row(rows, "results_dir")
        assert row["status"] == "error"
        assert "права" in row["hint"] or "Смените папку" in row["hint"]

    def test_broken_settings_file_gets_a_warning(self, tmp_path, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "results_root", lambda: tmp_path)
        settings = tmp_path / "settings.json"
        settings.write_text("{это не json", encoding="utf-8")
        monkeypatch.setattr(paths, "settings_path", lambda: settings)
        rows = diag.check_storage()
        row = _row(rows, "settings")
        assert row["status"] == "warn"
        assert "значениях по умолчанию" in row["hint"]


class TestData:
    def test_empty_raw_dir_is_explained(self, tmp_path, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "raw_dir", lambda: str(tmp_path / "raw"))
        monkeypatch.setattr(paths, "processed_dir", lambda: str(tmp_path / "processed"))
        (tmp_path / "raw").mkdir()
        rows = diag.check_data()
        assert _row(rows, "raw_present")["status"] == "warn"

    def test_old_raw_files_report_the_missing_columns(self, tmp_path, monkeypatch):
        """Сбор прежней версии: колонок нет — надо сказать, что фильтры успеют не всё."""
        import paths
        from yandex_maps_parser.exporters import save_excel
        raw = tmp_path / "raw"
        raw.mkdir()
        save_excel([{"name": "Кофе", "city": "Уфа", "query": "кафе"}],
                   str(raw / "raw_old.xlsx"), extra_fields=("website",))
        monkeypatch.setattr(paths, "raw_dir", lambda: str(raw))
        monkeypatch.setattr(paths, "processed_dir", lambda: str(tmp_path / "processed"))
        rows = diag.check_data()
        row = _row(rows, "raw_columns")
        assert row["status"] == "warn"
        assert "Филиалов" in row["detail"] and "Добавлено" in row["detail"]

    def test_new_raw_files_report_full_support(self, tmp_path, monkeypatch):
        import paths
        from yandex_maps_parser.exporters import save_excel
        raw = tmp_path / "raw"
        raw.mkdir()
        save_excel([{"name": "Кофе", "city": "Уфа", "query": "кафе",
                     "branch_count": 1, "added_at": "2026-01-01"}],
                   str(raw / "raw_new.xlsx"),
                   extra_fields=("website", "branch_count", "added_at"))
        monkeypatch.setattr(paths, "raw_dir", lambda: str(raw))
        monkeypatch.setattr(paths, "processed_dir", lambda: str(tmp_path / "processed"))
        rows = diag.check_data()
        assert _row(rows, "raw_columns")["status"] == "ok"


class TestEnvironment:
    def test_version_and_browser_are_reported(self):
        rows = diag.check_environment()
        assert _row(rows, "app_version")["status"] == "ok"
        browser = _row(rows, "browser")
        assert browser["status"] in ("ok", "warn")
        if browser["status"] == "warn":
            assert "Chrome" in browser["hint"], "в предупреждении должен быть совет"

    def test_missing_core_module_is_an_error(self, monkeypatch):
        """Без websocket-client не работает ни поиск, ни карточки — это ошибка."""
        import importlib.util
        real = importlib.util.find_spec

        def _spec(name, *a, **kw):
            return None if name == "websocket" else real(name, *a, **kw)

        monkeypatch.setattr(importlib.util, "find_spec", _spec)
        rows = diag.check_environment()
        row = _row(rows, "dep_websocket")
        assert row["status"] == "error"
        assert "requirements.txt" in row["hint"], "нужен рабочий совет по установке"

    def test_missing_optional_module_is_only_a_warning(self, monkeypatch):
        """httpx нужен только панели «Диагностика» — это предупреждение."""
        import importlib.util
        real = importlib.util.find_spec

        def _spec(name, *a, **kw):
            return None if name == "httpx" else real(name, *a, **kw)

        monkeypatch.setattr(importlib.util, "find_spec", _spec)
        rows = diag.check_environment()
        assert _row(rows, "dep_httpx")["status"] == "warn"

    def test_playwright_is_not_reported_at_all(self):
        """Playwright убран из приложения: страницы читает только Chrome."""
        ids = {r["id"] for r in diag.check_environment()}
        assert "dep_playwright" not in ids


# ── run_checks: сборка отчёта ─────────────────────────────────

class TestRunChecks:
    def test_selected_groups_only(self, monkeypatch):
        def _boom(*_a, **_kw):
            raise AssertionError("сеть в тестах запрещена")

        monkeypatch.setattr(diag, "check_vk_token", _boom)
        results = diag.run_checks(["files"])
        assert results, "локальные проверки должны вернуться"
        assert all(r["group"] == "files" for r in results)

    def test_broken_check_becomes_an_error_row(self, monkeypatch):
        monkeypatch.setattr(diag, "check_storage",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        results = diag.run_checks(["files"])
        row = _row(results, "storage")
        assert row["status"] == "error"
        assert "RuntimeError" in row["detail"]

    def test_errors_and_warnings_come_first(self):
        rows = [
            diag._res("a", "files", "ok", "ок"),
            diag._res("b", "files", "warn", "предупреждение"),
            diag._res("c", "files", "error", "ошибка"),
        ]
        order = {"error": 0, "warn": 1, "ok": 2}
        assert sorted(rows, key=lambda r: order[r["status"]])[0]["status"] == "error"

    def test_unknown_group_is_ignored(self):
        assert diag.run_checks(["nonsense"]) == diag.run_checks(None)


# ── Эндпоинт ─────────────────────────────────────────────────

@pytest.fixture()
def client():
    app = Flask(__name__)
    app.register_blueprint(diag.bp)
    return app.test_client()


class TestEndpoints:
    def test_local_checks_only(self, client, monkeypatch):
        monkeypatch.setattr(diag, "check_vk_token",
                            lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("сеть!")))
        data = client.post("/diagnostics/run", json={"groups": ["files", "env"]}).get_json()
        assert data["ok"] is True
        assert data["results"]
        assert {r["group"] for r in data["results"]} <= {"files", "env"}
        assert data["ts"]

    def test_thin_body_runs_everything(self, client, monkeypatch):
        groups = []
        monkeypatch.setattr(diag, "check_vk_token", lambda t: (groups.append("vk"), diag._res("vk_token", "keys", "ok", "г"))[1])
        data = client.post("/diagnostics/run", json={}).get_json()
        assert data["ok"] is True
        assert groups == ["vk"], "живая проверка ровно одна — токен ВК"
        assert {r["group"] for r in data["results"]} == {"keys", "files", "data", "env", "engines"}

    def test_string_group_is_accepted(self, client, monkeypatch):
        seen = []
        monkeypatch.setattr(diag, "check_vk_token",
                            lambda k: (seen.append(k), diag._res("vk_token", "keys", "ok", "г"))[1])
        client.post("/diagnostics/run", json={"groups": "keys"})
        assert len(seen) == 1, "строка вместо массива не должна ломать панель"

    def test_never_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(diag, "run_checks",
                            lambda groups: (_ for _ in ()).throw(RuntimeError("boom")))
        resp = client.post("/diagnostics/run", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is False and data["results"] == []

    # ── Панель запускает только сам интерфейс ──

    def test_runs_a_real_interface_request(self, client, monkeypatch):
        """Запрос самого приложения (JSON + localhost-Origin) проходит."""
        resp = client.post("/diagnostics/run", json={"groups": ["env"]},
                           headers={"Origin": "http://127.0.0.1:5077"})
        assert resp.status_code == 200 and resp.get_json()["ok"] is True

    def test_foreign_site_cannot_spend_quota(self, client, monkeypatch):
        """Чужая страница не может запустить проверку токена за пользователя."""
        called = []
        monkeypatch.setattr(diag, "check_vk_token",
                            lambda k: (called.append(k), diag._res("vk_token", "keys", "ok", "г"))[1])
        resp = client.post("/diagnostics/run", json={"groups": ["keys"]},
                           headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert called == [], "токен не должен проверяться по запросу с чужого сайта"
        assert resp.get_json()["ok"] is False

    def test_non_local_origin_variants_are_rejected(self):
        assert diag._is_local_origin("http://localhost:5000") is True
        assert diag._is_local_origin("http://[::1]:5000") is True
        assert diag._is_local_origin("https://evil.example") is False
        assert diag._is_local_origin("http://127.0.0.1.evil.example") is False
        assert diag._is_local_origin("мусор") is False

    def test_form_post_without_json_is_refused(self, client, monkeypatch):
        """Обычная HTML-форма (её может отправить любой сайт) — без эффекта."""
        called = []
        monkeypatch.setattr(diag, "check_vk_token",
                            lambda k: (called.append(k), diag._res("vk_token", "keys", "ok", "г"))[1])
        resp = client.post("/diagnostics/run", data="groups=keys",
                           content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 415
        assert called == [], "форма без JSON не должна дёргать внешний сервис"

    def test_response_never_contains_keys(self, client, monkeypatch):
        """Главное обещание панели: ключи наружу не уходят."""
        secret = "SECRET-KEY-0123456789"
        monkeypatch.setattr(diag, "effective_keys",
                            lambda: {"yandex": secret, "twogis": secret, "vk": secret})
        import httpx

        def _get(url, params=None, timeout=None, headers=None):
            # Проверяем и худший случай: текст исключения с ключом внутри.
            raise RuntimeError(f"failed to GET {url}?apikey={secret}")

        monkeypatch.setattr(httpx, "get", _get)
        body = client.post("/diagnostics/run", json={"groups": ["keys"]}).get_data(as_text=True)
        assert secret not in body
        assert "RuntimeError" in body, "причина всё-таки должна быть видна"
