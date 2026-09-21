# -*- coding: utf-8 -*-
"""Релизный конвейер: пользователи видят только то, что можно скачать.

Главный инвариант проекта (его нарушение и было причиной бага «скачал
обновление — версия та же»):

    version в static/version.json на main = ОПУБЛИКОВАННЫЙ релиз,
    архив которого реально скачивается,
    а download_url привязан к конкретному тегу, а не к `releases/latest`.

Проверяем три вещи: сам файл-инвариант, скрипт штамповки версии (им пользуются
и сборка, и анонс релиза) и разводку шагов в workflow.
"""
import json
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stamp_version  # noqa: E402

VERSION_JSON = ROOT / "static" / "version.json"


def ver(s):
    return tuple(int(x) for x in str(s).split(".") if x.isdigit())


def load_version_json(path=VERSION_JSON):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


# ── Инвариант «объявлено только опубликованное» ───────────────

class TestAdvertisedVersion:
    def test_version_json_is_not_ahead_of_the_app_version(self):
        import config
        advertised = load_version_json().get("version", "")
        assert ver(advertised) <= ver(config.APP_VERSION), (
            f"version.json объявляет {advertised}, а приложение выпускается как "
            f"{config.APP_VERSION}: релиза ещё нет, а пользователям уже "
            "предлагается обновление"
        )

    def test_advertised_version_matches_a_published_release(self):
        """Версия в файле должна существовать как опубликованный тег.

        Без сети тест пропускается (как и остальные сетевые проверки).
        """
        import requests
        try:
            from routes.api import GITHUB_REPO
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/"
                f"v{load_version_json()['version']}", timeout=10,
                headers={"Accept": "application/vnd.github+json"})
        except Exception:
            pytest.skip("нет доступа к GitHub API")
        if r.status_code != 200:
            pytest.skip("GitHub API недоступен (лимит запросов)")
        data = r.json()
        assert data.get("draft") is False, "объявлена версия, чей релиз — черновик"
        names = [a.get("name") for a in data.get("assets", [])]
        assert "YandexBusinessParser-windows-x64.zip" in names, (
            "у объявленного релиза нет windows-архива — обновление не скачать"
        )

    def test_download_url_is_pinned_to_the_advertised_tag(self):
        data = load_version_json()
        url = data.get("download_url", "")
        assert url, "без download_url старые сборки не найдут архив"
        assert "/releases/latest/" not in url, (
            "алиас releases/latest отдаёт ПРЕДЫДУЩИЙ релиз, пока новый — "
            "черновик: обновление превращается в установку той же версии"
        )
        assert f"/releases/download/v{data['version']}/" in url


# ── Скрипт штамповки версии ───────────────────────────────────

class TestStampScript:
    def _mod(self):
        return stamp_version

    def test_strip_tag(self):
        mod = self._mod()
        assert mod.strip_tag("v2.3.1") == "2.3.1"
        assert mod.strip_tag("2.3.1") == "2.3.1"

    def test_versioned_url_never_uses_the_alias(self):
        mod = self._mod()
        url = mod.versioned_download_url("o/r", "2.3.1")
        assert url == ("https://github.com/o/r/releases/download/v2.3.1/"
                       "YandexBusinessParser-windows-x64.zip")
        assert "/releases/latest/" not in url

    def test_summarize_takes_the_first_feature_line(self):
        mod = self._mod()
        body = ("\n**Авто-обновление работает.** Раньше ставилась\n"
                "предыдущая версия.\n\n**Ещё что-то.** Меньше важное.\n")
        text = mod.summarize(body)
        assert text.startswith("Авто-обновление работает.")
        assert "Ещё что-то" not in text
        assert "\n" not in text

    def test_apply_version_writes_everything(self, tmp_path):
        mod = self._mod()
        target = tmp_path / "version.json"
        target.write_text(json.dumps({
            "version": "2.3.0", "min_version": "2.0.0",
            "history": [{"version": "2.3.0", "changelog": "старое"}],
        }), encoding="utf-8")
        data = mod.apply_version(target, "v2.3.1", repo="o/r")
        assert data["version"] == "2.3.1"
        assert data["min_version"] == "2.0.0"                  # чужое не трогаем
        assert data["download_url"].endswith("/v2.3.1/YandexBusinessParser-windows-x64.zip")
        assert [h["version"] for h in data["history"]] == ["2.3.1", "2.3.0"]
        assert load_version_json(target)["version"] == "2.3.1"  # записано на диск

    def test_apply_version_does_not_duplicate_history(self, tmp_path):
        mod = self._mod()
        target = tmp_path / "version.json"
        target.write_text("{}", encoding="utf-8")
        mod.apply_version(target, "2.3.1", repo="o/r")
        data = mod.apply_version(target, "2.3.1", repo="o/r")
        assert [h["version"] for h in data["history"]].count("2.3.1") == 1


# ── Разводка workflow ─────────────────────────────────────────

class TestBuildWorkflow:
    def _steps(self):
        return load_workflow("build-exe.yml")["jobs"]["build"]["steps"]

    def test_version_is_stamped_into_the_bundle_before_the_build(self):
        steps = self._steps()
        names = [s.get("name", "") for s in steps]
        stamp = next(i for i, n in enumerate(names) if "bundled version.json" in n)
        build = next(i for i, n in enumerate(names) if n.startswith("Build exe"))
        assert stamp < build, "в .exe должна попасть версия тега"
        assert "scripts/stamp_version.py" in str(steps[stamp].get("run", ""))

    def test_the_build_no_longer_pushes_version_json_to_main(self):
        """Раньше версия попадала в main ДО публикации релиза — отсюда и баг."""
        text = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        assert "git push origin HEAD:main" not in text
        assert "releases/latest/download" not in text


class TestAnnounceWorkflow:
    def _wf(self):
        return load_workflow("announce-release.yml")

    def test_triggers_on_published_release(self):
        # Событие `published` приходит, когда черновик опубликован, то есть
        # когда архивы уже скачиваются: раньше этого момента версию объявлять
        # нельзя. (PyYAML читает ключ `on` как True — берём оба варианта.)
        wf = self._wf()
        triggers = wf.get("on", wf.get(True))
        assert triggers["release"]["types"] == ["published"]

    def test_waits_for_the_windows_asset_before_announcing(self):
        steps = self._wf()["jobs"]["announce"]["steps"]
        names = " | ".join(s.get("name", "") for s in steps)
        assert "Wait for the published release" in names
        text = (ROOT / ".github" / "workflows" / "announce-release.yml").read_text(encoding="utf-8")
        assert "YandexBusinessParser-windows-x64.zip" in text
        assert "isDraft" in text

    def test_writes_version_json_from_the_tag_and_pushes_to_main(self):
        steps = self._wf()["jobs"]["announce"]["steps"]
        run = "\n".join(str(s.get("run", "")) for s in steps)
        assert "scripts/stamp_version.py" in run
        assert "--repo" in run
        assert "git push origin HEAD:main" in run
