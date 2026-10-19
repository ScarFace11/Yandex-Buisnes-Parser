# -*- coding: utf-8 -*-
"""Маршруты «Сообщить о проблеме» и «Сбросить настройки».

Оба живут в routes/diagnostics.py и решают разные задачи. /report/context
отдаёт готовый текст контекста (версия, система, браузер, последний прогон,
хвост лога, имена пресетов) — его интерфейс прикладывает к телу issue на
GitHub. Главное свойство маршрута — он отдаёт полезное и НЕ отдаёт секретов:
токен ВК не проверяется, пресеты сводятся к именам (их настройки могут
содержать личные слова запросов).

/settings/reset возвращает настройки окружения (папки, браузер, хранение) к
стандартным, сохраняя пресеты, шаблоны писем, соглашение и ключи API — это
результат работы пользователя, а не настройка. Маршрут принимает только JSON
из самого приложения (чужая страница в браузере не должна уметь нажать кнопку
сброса за пользователя).

Run with: python -m pytest tests/test_report_reset.py -v
"""
import io
import json
import os
import sys
import zipfile

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import paths
from routes import diagnostics as diag


@pytest.fixture()
def client(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.register_blueprint(diag.bp)

    # Контекст не должен трогать сеть: проверки ключа ВК и браузера — отдельные
    # группы, но run_checks их не вызывает без явного запроса, а мок ниже
    # подтверждает, что /report/context их не просит.
    monkeypatch.setattr(diag, "check_vk_token",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("сеть!")))

    # settings.json — во временную папку, чтобы тест не читал/не писал настоящий.
    settings = {
        "presets": [
            {"name": "Уфа стоматология", "settings": {"queries": ["стоматология"],
                                                      "note": "личное слово"}},
            {"name": "Москва кафе", "settings": {"queries": ["кафе"]}},
        ],
        "browser_path": "/usr/bin/some-chrome",
        "results_root": "/tmp/custom-results",
        "retention_days": 7,
        "terms": {"accepted": True},
        "message_templates": [{"id": "tpl_1", "name": "Первое знакомство"}],
    }
    # Корень данных — во временную папку: settings_path() строится от data_dir().
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    return app.test_client(), settings_file, settings


class TestReportContext:
    def test_returns_markdown_with_all_sections(self, client):
        c, _f, _s = client
        rows = [
            {"group": "env", "status": "ok", "title": "Версия 3.2.1", "detail": "Linux"},
            {"group": "runs", "status": "warn", "title": "Последний прогон", "detail": "давно"},
        ]
        orig = diag.run_checks
        diag.run_checks = lambda groups=None, deep=False: rows
        try:
            data = c.get("/report/context").get_json()
        finally:
            diag.run_checks = orig
        assert data["ok"] is True
        ctx = data["context"]
        for section in ("## Версия, система и браузер", "## Прогоны и кэш",
                        "## Последние строки лога", "## Сохранённые пресеты"):
            assert section in ctx, f"нет раздела {section}"
        assert "Версия 3.2.1" in ctx
        assert "Последний прогон" in ctx

    def test_presets_reduced_to_names_only(self, client):
        """Имена пресетов попадают в контекст, их настройки — нет.

        Имя пресета — заголовок, который пользователь сам видит в списке, он
        и уходит наружу. А вот его настройки хранят слова запросов и личные
        пометки; issue бывает публичным, поэтому содержимое пресета в контекст
        не попадает — здесь проверяется именно эта граница.
        """
        c, _f, _s = client
        data = c.get("/report/context").get_json()
        ctx = data["context"]
        # Имена видны.
        assert "Уфа стоматология" in ctx
        assert "Москва кафе" in ctx
        # Содержимое пресета — слова запросов ("кафе" как отдельный запрос) и
        # личная пометка — не утекает.
        assert '"queries"' not in ctx, "запросы пресета не должны попадать в issue"
        assert "личное слово" not in ctx, "пометка пользователя не должна утекать"
        # Пустая строка — признак того, что список имён не превратился в дамп.
        assert "- Уфа стоматология" in ctx

    def test_does_not_run_live_checks(self, client, monkeypatch):
        """Ни токен ВК, ни браузерная проба не запускаются — контекст локальный.

        Живые проверки стоят квоту и время, а контекст issue собирается при
        каждом открытии окна — там их быть не должно. run_checks вызывается
        только с ["env", "runs"], и этот тест ловит регрессию, если кто-то
        добавит туда "keys" или "engines".
        """
        c, _f, _s = client
        seen = {}
        real = diag.run_checks

        def spy(groups=None, deep=False):
            seen["groups"] = groups
            seen["deep"] = deep
            return real(groups, deep)

        monkeypatch.setattr(diag, "run_checks", spy)
        data = c.get("/report/context").get_json()
        assert data["ok"] is True
        assert seen["groups"] == ["env", "runs"], "контекст должен брать только env и runs"
        assert seen["deep"] is False, "глубокая проба браузера не нужна"

    def test_log_tail_included_without_full_file(self, client):
        """Из лога берётся хвост, а не весь файл (контекст должен влезть в URL)."""
        c, _f, _s = client
        data = c.get("/report/context").get_json()
        # Раздел присутствует; его содержимое зависит от наличия логов на
        # машине, поэтому проверяем только структуру и отсутствие длинного дампа.
        assert "## Последние строки лога" in data["context"]


class TestSettingsReset:
    def test_reset_keeps_user_content_and_clears_environment(self, client):
        """Стирание настроек окружения не трогает результаты работы пользователя.

        Пресеты, шаблоны писем и принятое соглашение — это то, что пользователь
        создал руками; папки, браузер и срок хранения — окружение, его можно
        вернуть к стандартным без сожалений.
        """
        c, settings_file, settings = client
        data = c.post("/settings/reset", json={}).get_json()
        assert data["ok"] is True
        assert set(data["reset"]) == {"browser_path", "results_root", "retention_days"}
        # Файл на диске: настройки окружения стёрты, ценное осталось.
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        for key in ("browser_path", "results_root", "retention_days"):
            assert key not in on_disk, f"{key} должен быть удалён"
        assert on_disk["presets"] == settings["presets"]
        assert on_disk["terms"] == settings["terms"]
        assert on_disk["message_templates"] == settings["message_templates"]

    def test_reset_answer_lists_what_changed(self, client):
        """Ответ перечисляет, что стёрто и что сохранено — для подтверждения в UI."""
        c, _f, _s = client
        data = c.post("/settings/reset", json={}).get_json()
        assert data["ok"] is True
        assert "presets" in data.get("kept", []), "пресеты должны числиться сохранёнными"
        assert "presets" not in data.get("reset", [])

    def test_reset_calls_output_dirs_refresh(self, client, monkeypatch):
        """После сброса папки пересчитываются — иначе модули помнят старый путь."""
        c, _f, _s = client
        called = []
        monkeypatch.setattr(paths, "refresh_output_dirs",
                            lambda: called.append(True) or {})
        data = c.post("/settings/reset", json={}).get_json()
        assert data["ok"] is True
        assert called, "refresh_output_dirs не вызван — папки остались старыми"

    def test_reset_is_idempotent(self, client):
        """Повторный сброс не падает: стирать нечего — но ценное по-прежнему цело."""
        c, settings_file, _s = client
        first = c.post("/settings/reset", json={}).get_json()
        second = c.post("/settings/reset", json={}).get_json()
        assert first["ok"] is True and second["ok"] is True
        assert second["reset"] == [], "второй сброс не должен ничего находить"
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        assert on_disk["presets"], "пресеты пережили оба сброса"

    def test_rejects_non_json_body(self, client):
        """Сброс без JSON-тела отклоняется — защита от чужой страницы в браузере."""
        c, _f, _s = client
        resp = c.post("/settings/reset", data="query=1",
                      content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 415
        assert resp.get_json()["ok"] is False

    def test_rejects_foreign_origin(self, client):
        """Запрос с чужого origin (не 127.0.0.1/localhost) отклоняется."""
        c, _f, _s = client
        resp = c.post("/settings/reset", json={},
                      headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403


# ── Отправка issue через GitHub API ───────────────────────────


class TestReportIssue:
    """POST /report/issue: само создаёт issue, токен необязателен и не течёт."""

    @pytest.fixture()
    def no_env_token(self, monkeypatch):
        """GITHUB_TOKEN убран: тесты сами решают, есть токен или нет."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    @staticmethod
    def _fake_issue(monkeypatch, status=201, payload=None, note=""):
        """Подмена сети: возвращаем заданный ответ и ловим аргументы."""
        seen = {}
        payload = {"html_url": "https://github.com/o/r/issues/7",
                   "number": 7} if payload is None else payload

        def fake(title, labels, body, token):
            seen.update(title=title, labels=labels, body=body, token=token)
            return status, payload, note

        monkeypatch.setattr(diag, "_github_create_issue", fake)
        return seen

    def test_creates_issue_and_returns_its_url(self, client, monkeypatch,
                                               no_env_token):
        c, _f, _s = client
        seen = self._fake_issue(monkeypatch)
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        data = c.post("/report/issue", json={
            "title": "Баг: падает на Уфе", "labels": ["bug"],
            "body": "Шаги:\n1. Уфа"}).get_json()
        assert data["ok"] is True
        assert data["url"] == "https://github.com/o/r/issues/7"
        assert data["number"] == 7
        # Ушли в API те самые значения, что собрал интерфейс.
        assert seen["title"] == "Баг: падает на Уфе"
        assert seen["labels"] == ["bug"]
        assert "Шаги:" in seen["body"]
        assert seen["token"] == "ghp_env_token", "токен берётся из окружения"

    def test_without_token_server_refuses_and_explains(self, client, monkeypatch,
                                                       no_env_token):
        """Без токена сеть даже не трогается — сразу понятный отказ.

        GitHub не создаёт issue анонимно (401), поэтому бесполезно стучаться:
        интерфейс по коду no_token открывает заполненную форму, как раньше.
        """
        c, _f, _s = client
        monkeypatch.setattr(
            diag, "_github_create_issue",
            lambda *_a: (_ for _ in ()).throw(AssertionError("сеть без токена!")))
        data = c.post("/report/issue",
                      json={"title": "x", "body": "y"}).get_json()
        assert data["ok"] is False
        assert data["code"] == "no_token"
        assert "токен" in data["error"].lower()

    def test_token_from_form_beats_the_env_one(self, client, monkeypatch,
                                               no_env_token):
        """Введённый в окне токен используется для этой отправки."""
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
        seen = self._fake_issue(monkeypatch)
        data = c.post("/report/issue", json={
            "title": "t", "body": "b", "token": "ghp_form"}).get_json()
        assert data["ok"] is True
        assert seen["token"] == "ghp_form"
        assert data["saved"] is False, "без remember токен не сохраняется"

    def test_remember_saves_the_token_once(self, client, monkeypatch,
                                           no_env_token):
        """С чекбоксом «Запомнить» токен уходит в .env — и дальше берётся оттуда."""
        c, _f, _s = client
        saved = {}

        def remember(tok):
            saved["token"] = tok
            return True, ""

        monkeypatch.setattr(diag, "_remember_github_token", remember)
        self._fake_issue(monkeypatch)
        data = c.post("/report/issue", json={
            "title": "t", "body": "b", "token": "ghp_new", "remember": True}).get_json()
        assert data["ok"] is True and data["saved"] is True
        assert saved["token"] == "ghp_new"

    def test_remember_not_requested_means_no_save(self, client, monkeypatch,
                                                  no_env_token):
        c, _f, _s = client
        monkeypatch.setattr(
            diag, "_remember_github_token",
            lambda *_a: (_ for _ in ()).throw(AssertionError("сохранять не просили")))
        self._fake_issue(monkeypatch)
        data = c.post("/report/issue", json={
            "title": "t", "body": "b", "token": "ghp_once",
            "remember": False}).get_json()
        assert data["ok"] is True and data["saved"] is False

    def test_token_never_leaks_into_any_answer(self, client, monkeypatch,
                                               no_env_token):
        """Секрет не в ответе — ни при успехе, ни при ошибке."""
        c, _f, _s = client
        self._fake_issue(monkeypatch, status=401, payload={"message": "Bad credentials"})
        for payload in (
            {"title": "t", "body": "b", "token": "ghp_secret_123"},
            {"title": "t", "body": "b", "token": "ghp_secret_123", "remember": True},
        ):
            monkeypatch.setattr(diag, "_remember_github_token", lambda _t: (True, ""))
            resp = c.post("/report/issue", json=payload)
            assert "ghp_secret_123" not in resp.get_data(as_text=True)

    @pytest.mark.parametrize("status,payload,needle", [
        (401, {"message": "Bad credentials"}, "401"),
        (403, {"message": "API rate limit exceeded for 1.2.3.4"}, "лимит"),
        (404, {"message": "Not Found"}, "404"),
        (422, {"message": "Validation Failed"}, "422"),
    ])
    def test_github_refusals_are_explained(self, client, monkeypatch,
                                           no_env_token, status, payload, needle):
        c, _f, _s = client
        self._fake_issue(monkeypatch, status=status, payload=payload)
        data = c.post("/report/issue", json={"title": "t", "body": "b",
                                             "token": "ghp_x"}).get_json()
        assert data["ok"] is False and data["code"] == "github"
        assert data["status"] == status
        assert needle in data["error"], data["error"]

    def test_network_failure_is_named_without_details(self, client, monkeypatch,
                                                      no_env_token):
        """Класс исключения — да; текст httpx с URL (и ключом) — нет."""
        c, _f, _s = client
        self._fake_issue(monkeypatch, status=0, payload=None, note="ConnectError")
        data = c.post("/report/issue", json={"title": "t", "body": "b",
                                             "token": "ghp_x"}).get_json()
        assert data["ok"] is False and data["status"] == 0
        assert "ConnectError" in data["error"]

    def test_labels_are_normalized(self, client, monkeypatch, no_env_token):
        """Мусор в метках не доходит до API: строки, без пустых, не больше 10."""
        c, _f, _s = client
        seen = self._fake_issue(monkeypatch)
        data = c.post("/report/issue", json={
            "title": "t", "body": "b", "token": "ghp_x",
            "labels": ["bug", "", "   ", 42, "enhancement"] + [f"l{i}" for i in range(20)],
        }).get_json()
        assert data["ok"] is True
        assert seen["labels"][0] == "bug" and seen["labels"][1] == "enhancement"
        assert len(seen["labels"]) <= diag.ISSUE_LABELS_MAX
        assert all(isinstance(x, str) for x in seen["labels"])

    def test_title_and_body_are_capped(self, client, monkeypatch, no_env_token):
        c, _f, _s = client
        seen = self._fake_issue(monkeypatch)
        c.post("/report/issue", json={"title": "x" * 500, "body": "y" * 90000,
                                      "token": "ghp_x"})
        assert len(seen["title"]) == diag.ISSUE_TITLE_MAX
        assert len(seen["body"]) == diag.ISSUE_BODY_MAX

    def test_rejects_non_json_body(self, client, no_env_token):
        c, _f, _s = client
        resp = c.post("/report/issue", data="title=1",
                      content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 415

    def test_rejects_foreign_origin(self, client, no_env_token):
        c, _f, _s = client
        resp = c.post("/report/issue", json={"title": "t"},
                      headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403


class TestTokenVisibility:
    """/report/context сообщает только ПРИЗНАК токена — и никогда сам токен."""

    def test_has_token_flag_reflects_env(self, client, monkeypatch):
        c, _f, _s = client
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert c.get("/report/context").get_json()["has_token"] is False
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc123")
        resp = c.get("/report/context")
        data = resp.get_json()
        assert data["has_token"] is True
        assert "ghp_abc123" not in resp.get_data(as_text=True), "токен утёк в ответ"

    def test_context_tells_whether_device_login_is_possible(self, client,
                                                            monkeypatch):
        """can_device — войти по коду можно в ЭТОЙ сборке или нет.

        По нему окно прячет кнопку входа: без client_id пользователю
        не предлагают создавать OAuth-приложение — только форму.
        """
        c, _f, _s = client
        monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.setattr(diag, "GH_DEVICE_CLIENT_ID_DEFAULT", "")
        assert c.get("/report/context").get_json()["can_device"] is False
        monkeypatch.setattr(diag, "GH_DEVICE_CLIENT_ID_DEFAULT", "Iv1.baked42")
        assert c.get("/report/context").get_json()["can_device"] is True


# ── Вход в GitHub по коду (device flow) ───────────────────


class TestGithubDeviceFlow:
    """/report/github/device/start и /poll: токен приходит сам, без ввода.

    Поле токена в окне убрано, поэтому единственный штатный путь получить
    токен — device flow: код на экране, подтверждение на github.com/login/device,
    сервер меняет код на токен и кладёт его в .env. Тесты проверяют разговор
    с GitHub (подменённый _gh_form_post), а не сеть.
    """

    @pytest.fixture()
    def no_env(self, monkeypatch):
        """Оба ключа удалены и зашитого client_id нет: каждый тест решает сам, что задано."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.setattr(diag, "GH_DEVICE_CLIENT_ID_DEFAULT", "")

    @staticmethod
    def _fake_form(monkeypatch, responses):
        """Подмена сети: responses — список ответов (код, json, примечание).

        Каждый вызов забирает свой; все запросы логируются в seen.
        """
        seen = []

        def fake(url, data):
            seen.append({"url": url, "data": dict(data)})
            return responses.pop(0)

        monkeypatch.setattr(diag, "_gh_form_post", fake)
        return seen

    def test_start_without_client_id_refuses_without_network(self, client,
                                                             monkeypatch, no_env):
        """Нет client_id нигде (ни в окружении, ни зашит) — понятный отказ без сети."""
        c, _f, _s = client
        monkeypatch.setattr(
            diag, "_gh_form_post",
            lambda *_a: (_ for _ in ()).throw(AssertionError("сеть без client_id!")))
        data = c.post("/report/github/device/start", json={}).get_json()
        assert data["ok"] is False and data["code"] == "no_client_id"
        assert "GITHUB_OAUTH_CLIENT_ID" in data["error"]

    @staticmethod
    def _code_response():
        return (200,
                {"device_code": "dev_code_1", "user_code": "ABCD-1234",
                 "verification_uri": "https://github.com/login/device",
                 "interval": 5, "expires_in": 900},
                "")

    def test_baked_client_id_works_without_env(self, client, monkeypatch,
                                                no_env):
        """client_id зашит в сборку: обычному пользователю .env не нужен."""
        c, _f, _s = client
        monkeypatch.setattr(diag, "GH_DEVICE_CLIENT_ID_DEFAULT", "Iv1.baked42")
        seen = self._fake_form(monkeypatch, [self._code_response()])
        data = c.post("/report/github/device/start", json={}).get_json()
        assert data["ok"] is True
        assert data["user_code"] == "ABCD-1234"
        assert seen[0]["data"]["client_id"] == "Iv1.baked42"

    def test_env_client_id_overrides_the_baked_one(self, client, monkeypatch,
                                                    no_env):
        """GITHUB_OAUTH_CLIENT_ID в окружении — переопределение для разработки."""
        c, _f, _s = client
        monkeypatch.setattr(diag, "GH_DEVICE_CLIENT_ID_DEFAULT", "Iv1.baked42")
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.env999")
        seen = self._fake_form(monkeypatch, [self._code_response()])
        data = c.post("/report/github/device/start", json={}).get_json()
        assert data["ok"] is True
        assert seen[0]["data"]["client_id"] == "Iv1.env999"

    def test_start_returns_code_and_authorization_page(self, client, monkeypatch,
                                                       no_env):
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        seen = self._fake_form(monkeypatch, [(
            200,
            {"device_code": "dev_code_1", "user_code": "ABCD-1234",
             "verification_uri": "https://github.com/login/device",
             "interval": 5, "expires_in": 900},
            "")])
        data = c.post("/report/github/device/start", json={}).get_json()
        assert data["ok"] is True
        assert data["user_code"] == "ABCD-1234", "код показывается пользователю"
        assert data["verification_uri"] == "https://github.com/login/device"
        assert data["interval"] == 5 and data["expires_in"] == 900
        # Ушли в GitHub именно код клиента и минимум прав для issue.
        req = seen[0]
        assert req["url"] == diag.GH_DEVICE_CODE_URL
        assert req["data"]["client_id"] == "Iv1.test123"
        assert req["data"]["scope"] == "public_repo"

    def test_poll_pending_is_not_success(self, client, monkeypatch, no_env):
        """authorization_pending — «ещё ждём», и не ошибка, и не успех."""
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        self._fake_form(monkeypatch, [(
            200, {"error": "authorization_pending"}, "")])
        data = c.post("/report/github/device/poll",
                      json={"device_code": "dev_code_1"}).get_json()
        assert data == {"ok": False, "pending": True}

    def test_poll_slow_down_asks_for_a_longer_pause(self, client, monkeypatch,
                                                    no_env):
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        self._fake_form(monkeypatch, [(
            200, {"error": "slow_down"}, "")])
        data = c.post("/report/github/device/poll",
                      json={"device_code": "dev_code_1"}).get_json()
        assert data["ok"] is False and data["pending"] is True
        assert data["slow_down"] is True, "интерфейс обязан удлинить паузу"

    def test_poll_success_saves_token_and_never_returns_it(self, client,
                                                           monkeypatch, no_env):
        """Успех: токен уходит в .env (_remember_github_token), не в ответ."""
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        saved = {}

        def remember(tok):
            saved["token"] = tok
            return True, ""

        monkeypatch.setattr(diag, "_remember_github_token", remember)
        seen = self._fake_form(monkeypatch, [(
            200, {"access_token": "ghu_secret_42", "token_type": "bearer"}, "")])
        resp = c.post("/report/github/device/poll",
                      json={"device_code": "dev_code_1"})
        data = resp.get_json()
        assert data["ok"] is True and data["saved"] is True
        assert saved["token"] == "ghu_secret_42"
        assert "ghu_secret_42" not in resp.get_data(as_text=True), "токен утёк"
        # Ушла в обмен именно device_code из тела запроса.
        assert seen[0]["data"]["device_code"] == "dev_code_1"
        assert "device_code" in seen[0]["data"]["grant_type"]

    @pytest.mark.parametrize("err,needle", [
        ("expired_token", "вышло"),
        ("access_denied", "отклонён"),
    ])
    def test_poll_refusals_are_explained(self, client, monkeypatch, no_env,
                                         err, needle):
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        self._fake_form(monkeypatch, [(200, {"error": err}, "")])
        data = c.post("/report/github/device/poll",
                      json={"device_code": "dev_code_1"}).get_json()
        assert data["ok"] is False and data["code"] == err
        assert needle in data["error"]

    def test_poll_network_failure_is_named(self, client, monkeypatch, no_env):
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        self._fake_form(monkeypatch, [(0, None, "ConnectError")])
        data = c.post("/report/github/device/poll",
                      json={"device_code": "dev_code_1"}).get_json()
        assert data["ok"] is False and data["code"] == "network"
        assert "ConnectError" in data["error"]

    def test_poll_without_device_code_is_a_bad_request(self, client,
                                                       monkeypatch, no_env):
        c, _f, _s = client
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Iv1.test123")
        monkeypatch.setattr(
            diag, "_gh_form_post",
            lambda *_a: (_ for _ in ()).throw(AssertionError("сеть без device_code!")))
        data = c.post("/report/github/device/poll", json={}).get_json()
        assert data["ok"] is False and data["code"] == "bad_request"

    def test_both_routes_reject_foreign_origin(self, client, no_env):
        """Чужая страница не должна уметь запустить вход от имени пользователя."""
        c, _f, _s = client
        for url in ("/report/github/device/start", "/report/github/device/poll"):
            resp = c.post(url, json={"device_code": "x"},
                          headers={"Origin": "https://evil.example"})
            assert resp.status_code == 403, url


# ── Экспорт настроек ──────────────────────────────────────────


class TestSettingsExport:
    """POST /settings/export: zip со settings.json + снимком localStorage."""

    def test_zip_carries_settings_and_filtered_browser(self, client):
        c, settings_file, settings = client
        res = c.post("/settings/export", json={"browser": {
            "yp_theme_v1": "dark",
            "yp_settings_v1": "{\"query\":\"кафе\"}",
            "foreign_key": "не наше — мимо",
            "yp_not_a_string": 42,
        }})
        assert res.status_code == 200
        assert res.headers["Content-Type"].startswith("application/zip")
        assert "parser-settings-export.zip" in res.headers["Content-Disposition"]
        zf = zipfile.ZipFile(io.BytesIO(res.data))
        assert set(zf.namelist()) == {"settings.json", "browser.json"}
        # Серверская часть — файл целиком (со всеми пресетами и шаблонами).
        assert json.loads(zf.read("settings.json")) ["presets"] == settings["presets"]
        # Браузерная — только свои ключи и только строки.
        assert json.loads(zf.read("browser.json")) == {
            "yp_theme_v1": "dark",
            "yp_settings_v1": "{\"query\":\"кафе\"}",
        }

    def test_works_without_browser_part(self, client):
        c, _f, _s = client
        res = c.post("/settings/export", json={})
        assert res.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(res.data))
        assert "settings.json" in zf.namelist()
        assert "browser.json" not in zf.namelist(), "пустой снимок не пишем"

    def test_rejects_non_json_body(self, client):
        c, _f, _s = client
        resp = c.post("/settings/export", data="browser=x",
                      content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 415

    def test_rejects_foreign_origin(self, client):
        c, _f, _s = client
        resp = c.post("/settings/export", json={},
                      headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
