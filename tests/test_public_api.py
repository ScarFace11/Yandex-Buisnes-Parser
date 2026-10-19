# -*- coding: utf-8 -*-
"""Публичный REST API (/api/v1) — документированный вход для автоматизации.

Приложение — локальный сервис: сервер слушает 127.0.0.1, поэтому у API нет
и не нужно ключа. Здесь фиксируется контракт, на который опирается
интеграция из Python/других языков:

  * /search принимает запрос и возвращает run_id (поиск идёт в фоне);
  * /results отдаёт ОРГАНИЗАЦИИ, а не путь к файлу: JSON-файлы разных
    городов склеиваются, дубли одной организации схлопываются;
  * ?wait=N позволяет дождаться конца прогона одним запросом;
  * ?limit/offset страницами отдают большие ответы (n8n дробит так память);
  * callback_url в /search — POST по завершении: n8n/Webhook получает
    событие вместо опроса статуса;
  * /openapi.json — спецификация для Postman/n8n/генераторов клиентов.
"""
import json
import time

import pytest
from flask import Flask


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    """Flask client + пустой реестр прогонов + изолированная папка output/.

    Запуск браузера заглушается: тест проверяет HTTP-контракт, а не парсинг.
    """
    from run_manager import run_manager
    from routes import public_api

    (tmp_path / "output").mkdir()
    monkeypatch.chdir(tmp_path)           # пути в API относительные (как в exe)
    # API читает результаты из ТОЙ ЖЕ папки, куда пишет движок (RESULTS_DIR),
    # а не из жёсткого "output": папку результатов можно менять в настройках.
    monkeypatch.setattr(public_api, "RESULTS_DIR", str(tmp_path / "output"))
    public_api._RESULTS_CACHE.clear()     # кэш разбора — модульный, чистим между тестами

    monkeypatch.setattr(run_manager, "_runs", {})
    monkeypatch.setattr(run_manager, "start_process", lambda entry: None)
    monkeypatch.setattr(run_manager, "active_run_id", lambda: None)
    monkeypatch.setattr(run_manager, "_last_sweep", 0.0)

    app = Flask(__name__)
    app.register_blueprint(public_api.bp)
    return app.test_client(), run_manager, tmp_path, public_api


def _mk_run(run_manager, files=(), done=True):
    """Прогон в реестре — ровно те поля, что читает API."""
    entry = run_manager.new_run()
    entry["files"] = list(files)
    entry["_done"] = done
    entry["active"] = not done
    entry["queued"] = False
    entry["cities"] = ["Москва"]
    return entry


def _write_records(tmp_path, rel, records):
    path = tmp_path / "output" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(records, ensure_ascii=False),
                    encoding="utf-8")


class TestHealthAndSearch:
    def test_health_is_ok(self, ctx):
        c, *_ = ctx
        body = c.get("/api/v1/health").get_json()
        assert body["status"] == "ok"
        assert body["active_runs"] == 0

    def test_search_requires_queries(self, ctx):
        c, *_ = ctx
        r = c.post("/api/v1/search", json={"cities": ["Москва"]})
        assert r.status_code == 400
        assert "queries" in r.get_json()["error"]

    def test_search_requires_cities(self, ctx):
        c, *_ = ctx
        r = c.post("/api/v1/search", json={"queries": ["кафе"]})
        assert r.status_code == 400
        assert "cities" in r.get_json()["error"]

    def test_search_starts_a_run_and_returns_its_id(self, ctx):
        c, run_manager, *_ = ctx
        r = c.post("/api/v1/search", json={"queries": ["кафе"], "cities": ["Москва"]})
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] is True and body["queued"] is False
        assert run_manager.get(body["run_id"]) is not None

    def test_search_clamps_limits_instead_of_failing(self, ctx):
        c, run_manager, *_ = ctx
        r = c.post("/api/v1/search", json={"queries": ["кафе"], "cities": ["Москва"],
                                           "max_pages": "мусор", "max_workers": 999,
                                           "min_rating": "не число"})
        assert r.status_code == 200, r.get_data(as_text=True)
        params = run_manager.get(r.get_json()["run_id"])["params"]
        assert params["max_pages"] == 15          # мусор → значение по умолчанию
        assert params["max_workers"] == 20        # выход за границу → максимум
        assert params["min_rating"] == 0.0

    def test_search_queues_behind_an_active_run(self, ctx):
        c, run_manager, *_ = ctx
        active = _mk_run(run_manager, done=False)
        monkey_id = active["id"]
        from unittest.mock import patch
        with patch.object(run_manager, "active_run_id", return_value=monkey_id):
            r = c.post("/api/v1/search", json={"queries": ["кафе"], "cities": ["Москва"]})
        body = r.get_json()
        assert body["ok"] is True and body["queued"] is True
        assert body["run_id"] != monkey_id and body["position"] >= 1


class TestResults:
    def test_results_merges_city_files_and_drops_duplicates(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/moscow.json", [
            {"name": "Кафе у входа", "city": "Москва", "address": "ул. Мира, 1",
             "yandex_maps_url": "https://yandex.ru/maps/org/1"},
            {"name": "Однотип", "city": "Москва", "address": "", "phone": ""},
        ])
        _write_records(tmp_path, "raw/nn.json", [
            {"name": "Кафе у входа", "city": "Москва", "address": "ул. Мира, 1",
             "yandex_maps_url": "https://yandex.ru/maps/org/1", "phone": "+7 900 000-00-00"},
            {"name": "Второе", "city": "Нижний Новгород", "address": "ул. Ленина, 2"},
        ])
        entry = _mk_run(run_manager, files=["raw/moscow.json", "raw/nn.json"])

        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["status"] == "done"
        assert body["count"] == 3, "дубль одной организации схлопнут"
        names = [r["name"] for r in body["results"]]
        assert names == ["Кафе у входа", "Однотип", "Второе"]
        # Более поздний файл победил — телефоны из него.
        assert body["results"][0]["phone"] == "+7 900 000-00-00"
        assert body["files"] == ["raw/moscow.json", "raw/nn.json"]

    def test_results_without_run_id_uses_the_active_run(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/only.json", [{"name": "А", "city": "Казань"}])
        _mk_run(run_manager, files=["raw/only.json"], done=False)   # активный

        body = c.get("/api/v1/results").get_json()
        assert body["status"] == "running"
        assert body["count"] == 1

    def test_results_unknown_run_is_404(self, ctx):
        c, *_ = ctx
        assert c.get("/api/v1/results?run_id=nope").status_code == 404

    def test_results_without_any_run_is_404(self, ctx):
        c, *_ = ctx
        assert c.get("/api/v1/results").status_code == 404

    def test_results_wait_is_clamped_and_returns_immediately_when_done(self, ctx):
        c, run_manager, *_ = ctx
        api = ctx[3]
        assert api._int_arg("99999", 0, 0, api._WAIT_MAX_S) == api._WAIT_MAX_S
        entry = _mk_run(run_manager, files=[])
        t0 = time.monotonic()
        body = c.get(f"/api/v1/results?run_id={entry['id']}&wait=30").get_json()
        assert time.monotonic() - t0 < 1, "готовый прогон не должен ждать"
        assert body["status"] == "done" and body["results"] == []

    def test_results_limit_and_offset_page_the_records(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/big.json",
                       [{"name": f"Орг{i}", "city": "Москва"} for i in range(5)])
        entry = _mk_run(run_manager, files=["raw/big.json"])

        page1 = c.get(f"/api/v1/results?run_id={entry['id']}&limit=2").get_json()
        assert page1["count"] == 2 and page1["total"] == 5
        assert page1["limit"] == 2 and page1["offset"] == 0
        assert [r["name"] for r in page1["results"]] == ["Орг0", "Орг1"]

        page2 = c.get(f"/api/v1/results?run_id={entry['id']}&limit=2&offset=2").get_json()
        assert [r["name"] for r in page2["results"]] == ["Орг2", "Орг3"]

        tail = c.get(f"/api/v1/results?run_id={entry['id']}&limit=2&offset=4").get_json()
        assert [r["name"] for r in tail["results"]] == ["Орг4"]

        past = c.get(f"/api/v1/results?run_id={entry['id']}&offset=99").get_json()
        assert past["results"] == [] and past["total"] == 5

    def test_results_without_limit_returns_everything(self, ctx):
        """Обратная совместимость: без limit/offset полный список, count == total."""
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/a.json",
                       [{"name": f"Орг{i}", "city": "Казань"} for i in range(3)])
        entry = _mk_run(run_manager, files=["raw/a.json"])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["count"] == body["total"] == 3 and len(body["results"]) == 3

    def test_private_files_are_never_served(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/_state.json", [{"name": "СЛУЖЕБНЫЙ"}])
        _write_records(tmp_path, "raw/ok.json", [{"name": "Настоящая"}])
        entry = _mk_run(run_manager, files=["raw/_state.json", "raw/ok.json",
                                            "raw/notes.txt"])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert [r["name"] for r in body["results"]] == ["Настоящая"]
        assert body["files"] == ["raw/ok.json"]


class TestStatusAndRuns:
    def test_status_reports_run_state_and_files(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, files=["raw/a.json"], done=False)
        body = c.get(f"/api/v1/status?run_id={entry['id']}").get_json()
        assert body["status"] == "running"
        assert body["active"] is True
        assert body["files"] == ["raw/a.json"]

    def test_status_unknown_run_is_404(self, ctx):
        c, *_ = ctx
        assert c.get("/api/v1/status?run_id=nope").status_code == 404

    def test_status_without_run_id_is_the_global_queue(self, ctx):
        c, *_ = ctx
        body = c.get("/api/v1/status").get_json()
        assert c.get("/api/v1/status").status_code == 200
        assert "queued" in body and "paused" in body, "это общий статус очереди"

    def test_runs_lists_the_session(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, files=["raw/a.json"])
        runs = c.get("/api/v1/runs").get_json()["runs"]
        assert [r["id"] for r in runs] == [entry["id"]]

    def test_stop_is_accepted(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        from unittest.mock import patch
        with patch.object(run_manager, "stop_run", return_value=[]):
            r = c.post(f"/api/v1/stop?run_id={entry['id']}")
        assert r.status_code == 200 and r.get_json()["ok"] is True


class TestCallbackUrl:
    """callback_url: n8n/Webhook получает событие по завершении прогона."""

    def test_search_stores_valid_http_callback(self, ctx):
        c, run_manager, *_ = ctx
        r = c.post("/api/v1/search", json={
            "queries": ["кафе"], "cities": ["Москва"],
            "callback_url": "https://n8n.example/webhook/yp",
        })
        assert r.status_code == 200, r.get_data(as_text=True)
        params = run_manager.get(r.get_json()["run_id"])["params"]
        assert params["callback_url"] == "https://n8n.example/webhook/yp"

    def test_search_rejects_non_http_callback(self, ctx):
        """Мусорная строка не должна осесть в params — отказываем сразу, 400."""
        c, *_ = ctx
        for bad in ("file:///etc/passwd", "ftp://x/y", "n8n.example/hook", ""):
            r = c.post("/api/v1/search", json={
                "queries": ["кафе"], "cities": ["Москва"],
                "callback_url": bad,
            })
            if bad == "":
                assert r.status_code == 200      # пустой = «не задан», это ок
            else:
                assert r.status_code == 400, bad
                assert "callback_url" in r.get_json()["error"]

    def test_fire_callback_posts_payload_and_is_one_shot(self, ctx, monkeypatch):
        """По завершении прогона на callback_url уходит POST с итогами."""
        _, run_manager, *_ = ctx
        import run_manager as rm_mod
        posted = []

        def fake_post(url, payload):
            posted.append((url, payload))

        monkeypatch.setattr(rm_mod, "_post_callback", fake_post)
        entry = _mk_run(run_manager, files=["raw/x.json"])
        entry["params"]["callback_url"] = "http://127.0.0.1:9/hook"
        entry["count"] = 7

        rm_mod._fire_api_callback(entry)
        # запуск в фоне — дожидаемся письма
        for _ in range(50):
            if posted:
                break
            time.sleep(0.02)
        assert posted, "callback не отправлен"
        url, payload = posted[0]
        assert url == "http://127.0.0.1:9/hook"
        assert payload["event"] == "run.finished"
        assert payload["run_id"] == entry["id"]
        assert payload["status"] == "done"
        assert payload["count"] == 7
        assert payload["files"] == ["raw/x.json"]

    def test_fire_callback_without_url_does_nothing(self, ctx, monkeypatch):
        _, run_manager, *_ = ctx
        import run_manager as rm_mod
        calls = []
        monkeypatch.setattr(rm_mod, "_post_callback",
                            lambda u, p: calls.append(u))
        entry = _mk_run(run_manager)
        rm_mod._fire_api_callback(entry)
        time.sleep(0.05)
        assert calls == [], "без callback_url уведомлять некого"

    def test_unreachable_callback_does_not_break_the_run(self, ctx, monkeypatch):
        """Недоступный адрес — это лог, а не исключение наружу."""
        _, run_manager, *_ = ctx
        import run_manager as rm_mod
        entry = _mk_run(run_manager)
        entry["params"]["callback_url"] = "http://127.0.0.1:1/nothing"
        monkeypatch.setattr(rm_mod, "_CB_RETRIES", 1)
        monkeypatch.setattr(rm_mod, "_CB_RETRY_DELAY_S", 0)
        rm_mod._post_callback(entry["params"]["callback_url"],
                              rm_mod._callback_payload(entry))  # не должен поднять

    def test_callback_payload_marks_stopped_and_paused(self, ctx):
        _, run_manager, *_ = ctx
        import run_manager as rm_mod
        entry = _mk_run(run_manager, done=False)
        assert rm_mod._callback_payload(entry)["status"] == "done"
        entry["stop_event"].set()
        assert rm_mod._callback_payload(entry)["status"] == "stopped"
        entry["paused"] = True
        assert rm_mod._callback_payload(entry)["status"] == "paused"

    def test_bridge_fires_callback_when_run_finishes(self, ctx, monkeypatch):
        """Проводка: done-сообщение моста реально уведомляет callback_url.

        Это последняя нить между «прогон кончился» и «n8n получил событие» —
        ломается молча только если кто-то уберёт вызов в _bridge_reader.
        """
        _, run_manager, *_ = ctx
        import queue as queue_mod
        import threading
        import run_manager as rm_mod

        posted = []
        monkeypatch.setattr(rm_mod, "_post_callback",
                            lambda u, p: posted.append((u, p)))
        monkeypatch.setattr(rm_mod, "_FINISH_DELAY", 0.01)  # не ждать 6с в тесте

        mp_q, reg_q = queue_mod.Queue(), queue_mod.Queue()
        entry = _mk_run(run_manager, done=False)
        entry["params"]["callback_url"] = "http://127.0.0.1:9/hook"
        entry["count"] = 3

        t = threading.Thread(target=rm_mod._bridge_reader,
                             args=(mp_q, reg_q, entry))
        t.start()
        mp_q.put({"type": "done", "files": ["raw/a.json"], "count": 3,
                  "stopped": False, "paused": False})
        mp_q.put(None)                               # sentinel — продюмер мёртв
        t.join(timeout=5)
        assert not t.is_alive(), "мост не завершился"

        for _ in range(50):
            if posted:
                break
            time.sleep(0.02)
        assert posted, "мост не вызвал callback"
        url, payload = posted[0]
        assert url == "http://127.0.0.1:9/hook"
        assert payload["run_id"] == entry["id"]
        assert payload["status"] == "done"
        assert payload["count"] == 3


class TestOpenApi:
    def test_openapi_json_is_served_and_valid(self, ctx):
        c, *_ = ctx
        r = c.get("/api/v1/openapi.json")
        assert r.status_code == 200
        spec = r.get_json()
        assert spec["openapi"].startswith("3.")
        assert spec["info"]["title"]
        for path in ("/api/v1/health", "/api/v1/search", "/api/v1/results",
                     "/api/v1/status", "/api/v1/runs", "/api/v1/stop",
                     "/api/v1/skip-city"):
            assert path in spec["paths"], path

    def test_openapi_documents_new_capabilities(self, ctx):
        """Спецификация — источник правды для n8n: callback и страницы описаны."""
        c, *_ = ctx
        spec = c.get("/api/v1/openapi.json").get_json()
        props = (spec["paths"]["/api/v1/search"]["post"]["requestBody"]
                 ["content"]["application/json"]["schema"]["properties"])
        assert "callback_url" in props
        assert props["callback_url"]["format"] == "uri"
        params = {p["name"] for p in
                  spec["paths"]["/api/v1/results"]["get"]["parameters"]}
        assert {"run_id", "wait", "limit", "offset"} <= params

    def test_openapi_documents_batch_and_failed(self, ctx):
        """Пачка записей и статус failed описаны — иначе n8n про них не узнает."""
        c, *_ = ctx
        spec = c.get("/api/v1/openapi.json").get_json()
        for path in ("/api/v1/batch", "/api/v1/batch/{batch_id}",
                     "/api/v1/batch/{batch_id}/results"):
            assert path in spec["paths"], path
        schema = (spec["paths"]["/api/v1/batch"]["post"]["requestBody"]
                  ["content"]["application/json"]["schema"])
        assert schema["properties"]["records"]["items"]["properties"]["query"]
        props = (spec["paths"]["/api/v1/results"]["get"]["responses"]["200"]
                 ["content"]["application/json"]["schema"]["properties"])
        assert "failed" in props["status"]["enum"]
        assert "progress" in props and "error" in props


class TestFailedRuns:
    """Упавший прогон — это failed с текстом ошибки, а не «done, count: 0»."""

    def test_status_reports_failed_with_error_message(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["error"] = "browser closed unexpectedly"
        body = c.get(f"/api/v1/status?run_id={entry['id']}").get_json()
        assert body["status"] == "failed"
        assert body["error"] == "browser closed unexpectedly"

    def test_results_of_a_failed_run_carry_the_error(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, files=[])
        entry["error"] = "boom"
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["status"] == "failed"
        assert body["error"] == "boom"
        assert body["results"] == []

    def test_wait_returns_as_soon_as_a_run_failed(self, ctx):
        """Не ждать же 30 с «running», если прогон уже упал."""
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["error"] = "boom"
        t0 = time.monotonic()
        body = c.get(f"/api/v1/results?run_id={entry['id']}&wait=30").get_json()
        assert time.monotonic() - t0 < 1
        assert body["status"] == "failed"

    def test_progress_is_reported_while_running(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["cities"] = ["Москва", "Казань", "Уфа"]
        entry["cities_done"] = 1
        entry["cities_total"] = 3
        entry["records_so_far"] = 42
        st = c.get(f"/api/v1/status?run_id={entry['id']}").get_json()
        rs = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert st["progress"] == {"cities_done": 1, "cities_total": 3,
                                  "records_so_far": 42}
        assert rs["progress"]["records_so_far"] == 42

    def test_progress_total_falls_back_to_city_list(self, ctx):
        """
        Счётчик моста появляется с первым городом: до него всего городов
        берём из списка прогона.
        """
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["cities"] = ["Москва", "Казань"]
        body = c.get(f"/api/v1/status?run_id={entry['id']}").get_json()
        assert body["progress"]["cities_total"] == 2


class TestWaitUsesDoneFlag:
    """Корневой баг long-polling: active снимается через 6 с после конца.

    Мост выставляет _done сразу, а active=False — только по таймеру
    _FINISH_DELAY. Без проверки _done запрос с wait возвращал «running» и
    пустой список, хотя поиск уже закончился (и n8n получал пустоту).
    """

    def test_wait_does_not_hang_on_a_finished_run(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/done.json", [{"name": "Орг", "city": "Казань"}])
        entry = _mk_run(run_manager, files=["raw/done.json"], done=False)
        entry["_done"] = True            # мост уже получил done, active ещё True
        t0 = time.monotonic()
        body = c.get(f"/api/v1/results?run_id={entry['id']}&wait=30").get_json()
        assert time.monotonic() - t0 < 1, "готовый прогон не должен ждать"
        assert body["status"] == "done"
        assert body["count"] == 1

    def test_status_reports_done_before_active_is_cleared(self, ctx):
        c, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["_done"] = True
        body = c.get(f"/api/v1/status?run_id={entry['id']}").get_json()
        assert body["status"] == "done"
        assert body["active"] is True      # поле осталось прежним (совместимость)


class TestResultsDedupAndCache:
    def test_duplicates_collapse_across_utm_parameters(self, ctx):
        """Ссылка с ?utm_source= и без — одна и та же организация."""
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/a.json", [
            {"name": "Кафе", "city": "Москва",
             "yandex_maps_url": "https://Yandex.ru/maps/org/kafe/123/"},
        ])
        _write_records(tmp_path, "raw/b.json", [
            {"name": "Кафе", "city": "Москва", "phone": "+7 900 111-22-33",
             "yandex_maps_url": "https://yandex.ru/maps/org/kafe/123?utm_source=serp"},
        ])
        entry = _mk_run(run_manager, files=["raw/a.json", "raw/b.json"])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["total"] == 1
        assert body["results"][0]["phone"] == "+7 900 111-22-33"

    def test_fallback_key_normalizes_spaces_and_case(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        _write_records(tmp_path, "raw/a.json", [
            {"name": "ООО  Ромашка", "city": "москва", "address": "ул.  Мира, 1"},
        ])
        _write_records(tmp_path, "raw/b.json", [
            {"name": "ооо ромашка", "city": "Москва", "address": "ул. мира, 1",
             "phone": "+7 495 000-00-00"},
        ])
        entry = _mk_run(run_manager, files=["raw/a.json", "raw/b.json"])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["total"] == 1
        assert body["results"][0].get("phone") == "+7 495 000-00-00"

    def test_url_canonical_form(self, ctx):
        api = ctx[3]
        assert api._canon_url("https://Yandex.ru/maps/org/x/1/?utm_source=a#top") \
            == "https://yandex.ru/maps/org/x/1"
        assert api._canon_url("yandex.ru/maps/org/x/1") == "https://yandex.ru/maps/org/x/1"
        assert api._canon_url("") == ""

    def test_results_files_are_read_once_until_they_change(self, ctx, monkeypatch):
        """Polling не должен перечитывать мегабайты JSON на каждый запрос."""
        c, run_manager, tmp_path, api = ctx
        _write_records(tmp_path, "raw/a.json", [{"name": "Орг", "city": "Москва"}])
        calls = []
        real = api._read_results

        def counting(files):
            calls.append(list(files))
            return real(files)

        monkeypatch.setattr(api, "_read_results", counting)
        entry = _mk_run(run_manager, files=["raw/a.json"])
        for _ in range(3):
            body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
            assert body["count"] == 1
        assert len(calls) == 1, "три запроса — одно чтение файлов"

    def test_cache_is_dropped_when_a_file_changes(self, ctx, monkeypatch):
        c, run_manager, tmp_path, api = ctx
        entry = _mk_run(run_manager, files=["raw/a.json"])
        _write_records(tmp_path, "raw/a.json", [{"name": "Первая", "city": "М"}])
        assert c.get(f"/api/v1/results?run_id={entry['id']}").get_json()["count"] == 1
        time.sleep(0.01)
        _write_records(tmp_path, "raw/a.json", [
            {"name": "Первая", "city": "М"}, {"name": "Вторая", "city": "М"}])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert body["count"] == 2, "изменённый файл должен попасть в ответ"

    def test_results_are_read_from_the_configured_results_dir(self, ctx, monkeypatch, tmp_path):
        """Папку результатов меняют в настройках — API должен читать её же."""
        c, run_manager, _tmp, api = ctx
        custom = tmp_path / "custom-results"
        custom.mkdir()
        (custom / "raw").mkdir()
        (custom / "raw" / "x.json").write_text(
            json.dumps([{"name": "Своя папка", "city": "Уфа"}], ensure_ascii=False),
            encoding="utf-8")
        monkeypatch.setattr(api, "RESULTS_DIR", str(custom))
        entry = _mk_run(run_manager, files=["raw/x.json"])
        body = c.get(f"/api/v1/results?run_id={entry['id']}").get_json()
        assert [r["name"] for r in body["results"]] == ["Своя папка"]


class TestSearchWarnings:
    def test_clamped_value_is_reported(self, ctx):
        c, *_ = ctx
        body = c.post("/api/v1/search", json={
            "queries": ["кафе"], "cities": ["Москва"], "max_pages": 999,
            "output_formats": ["excel", "pdf"], "min_rating": "не число",
        }).get_json()
        assert "max_pages=999 clamped to 50" in body["warnings"]
        assert any("pdf" in w for w in body["warnings"])
        assert any("min_rating" in w for w in body["warnings"])

    def test_garbage_instead_of_number_is_reported(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/search", json={
            "queries": ["кафе"], "cities": ["Москва"], "max_workers": "abc",
        }).get_json()
        assert any("max_workers" in w for w in body["warnings"])
        assert run_manager.get(body["run_id"])["params"]["max_workers"] == 10

    def test_valid_request_has_empty_warnings(self, ctx):
        c, *_ = ctx
        body = c.post("/api/v1/search", json={
            "queries": ["кафе"], "cities": ["Москва"], "max_pages": 5,
        }).get_json()
        assert body["warnings"] == []

    def test_single_string_query_is_not_split_into_letters(self, ctx):
        """n8n и curl часто присылают строку вместо массива."""
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/search", json={
            "queries": "кафе", "cities": "Пермь",
        }).get_json()
        params = run_manager.get(body["run_id"])["params"]
        assert params["queries"] == ["кафе"]
        assert params["cities"] == ["Пермь"]

    def test_explicit_empty_output_formats_means_no_files(self, ctx):
        """Обратная совместимость: [] — «не выгружать ничего», а не дефолт."""
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/search", json={
            "queries": ["кафе"], "cities": ["Москва"], "output_formats": [],
        }).get_json()
        params = run_manager.get(body["run_id"])["params"]
        assert not any(params[f] for f in ("output_excel", "output_json",
                                           "output_csv", "output_map"))


class TestBatch:
    """Пакетный режим: список записей одним запросом (записи вместо консоли)."""

    def _active_from_registry(self, run_manager, monkeypatch):
        """active_run_id как в жизни: стартовавший прогон занимает движок."""
        def _active():
            for rid, r in run_manager._runs.items():
                if r.get("active") and not r.get("queued"):
                    return rid
            return None
        monkeypatch.setattr(run_manager, "active_run_id", _active)

    def test_batch_starts_first_and_queues_the_rest(self, ctx, monkeypatch):
        c, run_manager, *_ = ctx
        self._active_from_registry(run_manager, monkeypatch)
        body = c.post("/api/v1/batch", json={"records": [
            {"query": "кафе", "city": "Москва"},
            {"query": "автосервис", "city": "Казань"},
            {"queries": ["стоматология"], "cities": ["Уфа", "Самара"]},
        ]}).get_json()
        assert body["ok"] is True and body["count"] == 3
        assert body["queued"] == 2 and body["runs"][0]["queued"] is False
        assert body["runs"][1]["position"] == 1
        # Короткая форма развернута в обычные queries/cities.
        first = run_manager.get(body["runs"][0]["run_id"])["params"]
        assert first["queries"] == ["кафе"] and first["cities"] == ["Москва"]
        assert first["batch_id"] == body["batch_id"] and first["batch_index"] == 0

    def test_batch_defaults_apply_to_every_record(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/batch", json={
            "defaults": {"max_pages": 3, "social_mode": "all"},
            "records": [{"query": "кафе", "city": "Москва"},
                        {"query": "кафе", "city": "Тверь", "max_pages": 7}],
        }).get_json()
        params = [run_manager.get(r["run_id"])["params"] for r in body["runs"]]
        assert params[0]["max_pages"] == 3 and params[0]["social_mode"] == "all"
        assert params[1]["max_pages"] == 7

    def test_batch_rejects_everything_when_one_record_is_bad(self, ctx, monkeypatch):
        """Ошибка в одной записи не должна запускать остальные."""
        c, run_manager, *_ = ctx
        started = []
        monkeypatch.setattr(run_manager, "start_process",
                            lambda e: started.append(e["id"]))
        r = c.post("/api/v1/batch", json={"records": [
            {"query": "кафе", "city": "Москва"},
            {"city": "Казань"},
        ]})
        assert r.status_code == 400
        assert any("records[1]" in e for e in r.get_json()["errors"])
        assert run_manager._runs == {} and started == []

    def test_batch_requires_records(self, ctx):
        c, *_ = ctx
        assert c.post("/api/v1/batch", json={}).status_code == 400
        assert c.post("/api/v1/batch", json={"records": []}).status_code == 400

    def test_non_object_body_is_400_not_500(self, ctx):
        """Тело-массив — это ошибка клиента, а не падение сервера."""
        c, *_ = ctx
        assert c.post("/api/v1/batch", json=[1, 2, 3]).status_code == 400
        assert c.post("/api/v1/search", json=["кафе"]).status_code == 400

    def test_batch_caps_the_number_of_records(self, ctx):
        c, *_ = ctx
        api = ctx[3]
        too_many = [{"query": "кафе", "city": f"Город{i}"}
                    for i in range(api._BATCH_MAX_RECORDS + 1)]
        r = c.post("/api/v1/batch", json={"records": too_many})
        assert r.status_code == 400
        assert str(api._BATCH_MAX_RECORDS) in r.get_json()["error"]

    def test_batch_warnings_are_numbered_by_record(self, ctx):
        c, *_ = ctx
        body = c.post("/api/v1/batch", json={"records": [
            {"query": "кафе", "city": "Москва"},
            {"query": "кафе", "city": "Тверь", "max_pages": 999},
        ]}).get_json()
        assert any(w.startswith("records[1]:") and "clamped" in w
                   for w in body["warnings"])
        assert body["runs"][1]["warnings"] == ["max_pages=999 clamped to 50"]

    def test_batch_callback_url_is_inherited(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/batch", json={
            "callback_url": "https://n8n.example/webhook/yp",
            "records": [{"query": "кафе", "city": "Москва"},
                        {"query": "кафе", "city": "Тверь",
                         "callback_url": "https://n8n.example/webhook/other"}],
        }).get_json()
        params = [run_manager.get(r["run_id"])["params"] for r in body["runs"]]
        assert params[0]["callback_url"] == "https://n8n.example/webhook/yp"
        assert params[1]["callback_url"] == "https://n8n.example/webhook/other"

    def test_batch_status_aggregates_progress_and_errors(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/batch", json={"records": [
            {"query": "кафе", "city": "Москва"},
            {"query": "кафе", "city": "Тверь"},
        ]}).get_json()
        first, second = (run_manager.get(r["run_id"]) for r in body["runs"])
        first.update({"count": 5, "cities_done": 1, "cities_total": 1,
                      "records_so_far": 5, "_done": True, "active": False})
        second.update({"error": "boom", "_done": True, "active": False})

        st = c.get(f"/api/v1/batch/{body['batch_id']}").get_json()
        assert st["count"] == 2 and st["status"] == "partial"
        assert st["done"] == 1 and st["failed"] == 1
        assert st["progress"]["records_so_far"] == 5
        assert st["errors"][0]["index"] == 1 and st["errors"][0]["error"] == "boom"
        assert [r["index"] for r in st["runs"]] == [0, 1]

    def test_batch_status_is_all_failed_when_nothing_succeeded(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/batch", json={
            "records": [{"query": "кафе", "city": "Москва"}],
        }).get_json()
        entry = run_manager.get(body["runs"][0]["run_id"])
        entry.update({"error": "boom", "_done": True, "active": False})
        st = c.get(f"/api/v1/batch/{body['batch_id']}").get_json()
        assert st["status"] == "failed"

    def test_batch_results_merge_every_record_without_duplicates(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        body = c.post("/api/v1/batch", json={"records": [
            {"query": "кафе", "city": "Москва"},
            {"query": "кафе", "city": "Казань"},
        ]}).get_json()
        _write_records(tmp_path, "raw/moscow.json", [
            {"name": "Кафе", "city": "Москва",
             "yandex_maps_url": "https://yandex.ru/maps/org/1"},
        ])
        _write_records(tmp_path, "raw/kazan.json", [
            {"name": "Кафе", "city": "Москва",
             "yandex_maps_url": "https://yandex.ru/maps/org/1?utm_source=x",
             "phone": "+7 843 000-00-00"},
            {"name": "Другая", "city": "Казань"},
        ])
        run_manager.get(body["runs"][0]["run_id"])["files"] = ["raw/moscow.json"]
        run_manager.get(body["runs"][1]["run_id"])["files"] = ["raw/kazan.json"]
        for r in body["runs"]:
            run_manager.get(r["run_id"]).update({"_done": True, "active": False})

        rs = c.get(f"/api/v1/batch/{body['batch_id']}/results").get_json()
        assert rs["total"] == 2 and rs["status"] == "done"
        names = [r["name"] for r in rs["results"]]
        assert names == ["Кафе", "Другая"]
        assert rs["results"][0]["phone"] == "+7 843 000-00-00"
        assert rs["files"] == ["raw/moscow.json", "raw/kazan.json"]

    def test_batch_results_support_paging(self, ctx):
        c, run_manager, tmp_path, _ = ctx
        body = c.post("/api/v1/batch", json={
            "records": [{"query": "кафе", "city": "Москва"}],
        }).get_json()
        _write_records(tmp_path, "raw/a.json",
                       [{"name": f"Орг{i}", "city": "М"} for i in range(3)])
        run_manager.get(body["runs"][0]["run_id"])["files"] = ["raw/a.json"]
        page = c.get(f"/api/v1/batch/{body['batch_id']}/results?limit=2&offset=2").get_json()
        assert page["total"] == 3 and page["count"] == 1
        assert [r["name"] for r in page["results"]] == ["Орг2"]

    def test_unknown_batch_is_404(self, ctx):
        c, *_ = ctx
        assert c.get("/api/v1/batch/nope").status_code == 404
        assert c.get("/api/v1/batch/nope/results").status_code == 404

    def test_batch_wait_returns_when_all_runs_are_done(self, ctx):
        c, run_manager, *_ = ctx
        body = c.post("/api/v1/batch", json={
            "records": [{"query": "кафе", "city": "Москва"}],
        }).get_json()
        run_manager.get(body["runs"][0]["run_id"])["_done"] = True
        t0 = time.monotonic()
        st = c.get(f"/api/v1/batch/{body['batch_id']}?wait=30").get_json()
        assert time.monotonic() - t0 < 1
        assert st["status"] == "done"


class TestCorsAndStopPause:
    def test_cors_headers_for_a_local_browser_client(self, ctx):
        c, *_ = ctx
        r = c.get("/api/v1/health", headers={"Origin": "http://localhost:8080"})
        assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:8080"

    def test_foreign_origin_is_not_allowed(self, ctx):
        """Сервер локальный: чужим сайтам отвечать не нужно."""
        c, *_ = ctx
        r = c.get("/api/v1/health", headers={"Origin": "https://evil.example"})
        assert not r.headers.get("Access-Control-Allow-Origin")

    def test_stop_with_pause_flag_asks_for_a_pause(self, ctx, monkeypatch):
        c, run_manager, *_ = ctx
        calls = []
        monkeypatch.setattr(run_manager, "stop_run",
                            lambda run_id="", pause=False: calls.append(pause) or [])
        assert c.post("/api/v1/stop?pause=1").status_code == 200
        assert calls == [True]


class TestBridgePersistsRunState:
    """Мост переносит итоги дочернего процесса в родительский entry.

    Дочерний процесс не может писать в реестр родителя, а /api/v1/results
    читает entry["files"]: без этой проводки API всегда отдавал пустой
    список, а статус навсегда оставался «running».
    """

    def _run_bridge(self, monkeypatch, entry, messages):
        import queue as queue_mod
        import threading
        import run_manager as rm_mod
        monkeypatch.setattr(rm_mod, "_FINISH_DELAY", 0.01)
        mp_q, reg_q = queue_mod.Queue(), queue_mod.Queue()
        t = threading.Thread(target=rm_mod._bridge_reader,
                             args=(mp_q, reg_q, entry))
        t.start()
        for m in messages:
            mp_q.put(m)
        mp_q.put(None)
        t.join(timeout=5)
        assert not t.is_alive(), "мост не завершился"
        return reg_q

    def test_done_message_fills_files_count_and_cities(self, ctx, monkeypatch):
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        self._run_bridge(monkeypatch, entry, [
            {"type": "done", "files": ["raw/a.json", "raw/b.json"],
             "count": 12, "cities": ["Москва", "Казань"],
             "stopped": False, "paused": False, "resume": None},
        ])
        assert entry["files"] == ["raw/a.json", "raw/b.json"]
        assert entry["count"] == 12
        assert entry["cities"] == ["Москва", "Казань"]
        assert entry["_done"] is True and entry["finished_at"] > 0

    def test_error_message_marks_the_run_failed(self, ctx, monkeypatch):
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        reg_q = self._run_bridge(monkeypatch, entry, [
            {"type": "error", "message": "chrome died"},
        ])
        assert entry["error"] == "chrome died"
        # Служебное сообщение не уходит в SSE-поток фронтенда.
        assert reg_q.empty() or reg_q.get_nowait().get("type") == "done"

    def test_error_inside_done_is_kept(self, ctx, monkeypatch):
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        self._run_bridge(monkeypatch, entry, [
            {"type": "done", "files": [], "count": 0, "error": "boom",
             "stopped": False, "paused": False, "resume": None},
        ])
        assert entry["error"] == "boom"

    def test_crash_without_done_is_reported_as_failed(self, ctx, monkeypatch):
        """Молча умерший процесс — это не «ничего не найдено»."""
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        self._run_bridge(monkeypatch, entry, [])            # только сентинел
        assert entry["error"] and "done" in entry["error"]

    def test_progress_messages_are_parsed(self, ctx, monkeypatch):
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        self._run_bridge(monkeypatch, entry, [
            {"type": "log", "level": "progress", "msg": "city_list|Москва/Казань"},
            {"type": "log", "level": "progress", "msg": "city/1/2/Москва"},
            {"type": "log", "level": "progress", "msg": "city_done|1|2|Москва|done|7"},
            {"type": "log", "level": "progress", "msg": "city/2/2/Казань"},
            {"type": "progress", "cities_done": 2, "cities_total": 2,
             "records_so_far": 9},
        ])
        assert entry["cities"] == ["Москва", "Казань"]
        assert entry["cities_total"] == 2
        assert entry["cities_done"] == 2
        assert entry["records_so_far"] == 9

    def test_stopped_run_is_not_reported_as_failed(self, ctx, monkeypatch):
        """Пользовательский стоп без done — это стоп, а не падение."""
        _, run_manager, *_ = ctx
        entry = _mk_run(run_manager, done=False)
        entry["stop_event"].set()
        self._run_bridge(monkeypatch, entry, [])
        assert entry["error"] is None

    def test_callback_payload_carries_error_progress_and_batch(self, ctx):
        _, run_manager, *_ = ctx
        import run_manager as rm_mod
        entry = _mk_run(run_manager)
        entry.update({"error": "boom", "records_so_far": 3, "cities_total": 2})
        entry["params"].update({"batch_id": "b1", "batch_index": 2})
        payload = rm_mod._callback_payload(entry)
        assert payload["status"] == "failed"
        assert payload["error"] == "boom"
        assert payload["progress"]["records_so_far"] == 3
        assert payload["batch_id"] == "b1" and payload["batch_index"] == 2


class TestProgressWiring:
    """run_process сообщает прогресс явными сообщениями.

    У одного города движок промежуточных сообщений не шлёт (они нужны полосе
    городов в интерфейсе), поэтому знаменатель и итог приходят отдельно —
    иначе progress всегда был бы 0/0 и по нему нельзя было бы судить о ходе.
    """

    def test_run_process_reports_start_and_finish_progress(self, tmp_path, monkeypatch):
        import queue as queue_mod
        import yandex_maps_parser.exporters as exporters
        import yandex_maps_parser.runner as runner
        import yandex_maps_parser.state as state

        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "a.json").write_text(
            json.dumps([{"name": "Орг", "city": "Москва"}], ensure_ascii=False),
            encoding="utf-8")
        monkeypatch.setattr(state, "RESULTS_DIR", str(tmp_path))
        monkeypatch.setattr(state, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(runner, "run_web", lambda *a, **k: ["raw/a.json"])
        monkeypatch.setattr(exporters, "write_frontend_json", lambda *a, **k: None)

        mp_q = queue_mod.Queue()
        runner.run_process({"queries": ["кафе"], "cities": ["Москва"],
                            "output_json": True}, mp_q)
        messages = []
        while not mp_q.empty():
            messages.append(mp_q.get_nowait())
        progress = [m for m in messages
                    if isinstance(m, dict) and m.get("type") == "progress"]
        assert progress[0]["cities_total"] == 1 and progress[0]["cities_done"] == 0
        assert progress[-1]["cities_done"] == 1
        assert progress[-1]["records_so_far"] == 1
        done = [m for m in messages
                if isinstance(m, dict) and m.get("type") == "done"]
        assert done and done[0]["files"] == ["raw/a.json"] and done[0]["count"] == 1


class TestRunRegistrySweep:
    """Реестр прогонов не растёт бесконечно (TTL + лимит завершённых)."""

    def _entry(self, run_manager, started_at, **kw):
        entry = run_manager.new_run()
        entry["started_at"] = started_at
        entry.update(kw)
        return entry

    def _force_sweep(self, run_manager, monkeypatch):
        monkeypatch.setattr(run_manager, "_last_sweep", 0.0)
        return run_manager._sweep()

    def test_old_finished_runs_are_dropped(self, ctx, monkeypatch):
        import run_manager as rm_mod
        _, run_manager, *_ = ctx
        old = self._entry(run_manager, time.time() - rm_mod._RUN_TTL_S - 10,
                          active=False)
        fresh = self._entry(run_manager, time.time(), active=False)
        removed = self._force_sweep(run_manager, monkeypatch)
        assert removed >= 1
        assert run_manager.get(old["id"]) is None
        assert run_manager.get(fresh["id"]) is not None

    def test_active_and_paused_runs_survive(self, ctx, monkeypatch):
        import run_manager as rm_mod
        _, run_manager, *_ = ctx
        long_ago = time.time() - rm_mod._RUN_TTL_S - 10
        active = self._entry(run_manager, long_ago)                  # ещё идёт
        paused = self._entry(run_manager, long_ago, active=False, paused=True)
        self._force_sweep(run_manager, monkeypatch)
        assert run_manager.get(active["id"]) is not None
        assert run_manager.get(paused["id"]) is not None

    def test_finished_runs_are_capped(self, ctx, monkeypatch):
        import run_manager as rm_mod
        _, run_manager, *_ = ctx
        now = time.time()
        kept = []
        for i in range(rm_mod._MAX_FINISHED_RUNS + 5):
            e = self._entry(run_manager, now + i, active=False)   # свежие
            kept.append(e["id"])
        self._force_sweep(run_manager, monkeypatch)
        remaining = [r for r in kept if run_manager.get(r)]
        assert len(remaining) == rm_mod._MAX_FINISHED_RUNS
        # Уехали самые старые.
        assert kept[0] not in remaining and kept[-1] in remaining

    def test_sweep_is_throttled(self, ctx):
        """Перебирать реестр на каждый new_run() дорого — не чаще раза в минуту."""
        import run_manager as rm_mod
        _, run_manager, *_ = ctx
        run_manager._last_sweep = time.time()
        old = self._entry(run_manager, time.time() - rm_mod._RUN_TTL_S - 10,
                          active=False)
        assert run_manager._sweep() == 0
        assert run_manager.get(old["id"]) is not None
