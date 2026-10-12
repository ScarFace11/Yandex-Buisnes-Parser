# -*- coding: utf-8 -*-
"""История изменений: CHANGELOG.md — единственный источник заметок релиза.

Инвариант проекта: каждая версия сборки описана разделом «## [версия] — …»
в CHANGELOG.md. На этом держится релиз: тело GitHub Release берётся из этого
раздела (scripts/release_notes.py), а сам файл прикладывается к релизу ассетом.

Технического дневника (CHANGES-DEV.md) в проекте больше нет: он жил локально,
не поставлялся и не коммитился. Тесты следят, чтобы он не вернулся в
релизный пайплайн и в отслеживание git.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_notes  # noqa: E402

USER_LOG = ROOT / "CHANGELOG.md"
DEV_LOG = ROOT / "CHANGES-DEV.md"
WORKFLOW = ROOT / ".github" / "workflows" / "build-exe.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def versions(text: str) -> list:
    """Номера версий в порядке появления: «## [2.3.4] — …»."""
    return re.findall(r"^##\s*\[([^\]]+)\]", text, re.M)


class TestUserChangelog:
    def test_changelog_is_in_the_repo(self):
        assert USER_LOG.exists(), "нет CHANGELOG.md"

    def test_changelog_starts_with_a_title(self):
        assert _read(USER_LOG).splitlines()[0].startswith("# ")

    def test_every_version_has_a_body(self):
        text = _read(USER_LOG)
        for v in versions(text):
            found = release_notes.extract_section(text, v)
            assert found is not None, f"нет раздела {v}"
            assert found[1].strip(), f"раздел {v} пуст"

    def test_current_app_version_is_documented(self):
        """Версия сборки обязана быть описана — иначе релиз уедет без заметок."""
        import config

        version = str(config.APP_VERSION).strip()
        assert version in versions(_read(USER_LOG)), (
            f"версия {version} из config.py не описана в CHANGELOG.md")

    def test_nothing_is_left_unreleased_after_a_release_section(self):
        """[Unreleased] — только сверху: он ещё не выпущен."""
        vs = versions(_read(USER_LOG))
        if "Unreleased" in vs:
            assert vs[0] == "Unreleased", "раздел [Unreleased] должен быть первым"


class TestDevLogIsGone:
    """CHANGES-DEV.md — локальный дневник: он никуда не поставляется."""

    def test_dev_log_is_not_tracked_by_git(self):
        import subprocess
        out = subprocess.run(["git", "ls-files", "CHANGES-DEV.md"],
                             capture_output=True, text=True, cwd=ROOT,
                             timeout=30).stdout.strip()
        assert out == "", "CHANGES-DEV.md снова попал под git"

    def test_dev_log_is_ignored(self):
        assert "CHANGES-DEV.md" in _read(ROOT / ".gitignore")

    def test_local_copy_would_not_be_committed(self, tmp_path):
        """Даже если дневник лежит рядом локально — git его не увидит."""
        import subprocess
        res = subprocess.run(["git", "check-ignore", "-q", "CHANGES-DEV.md"],
                             capture_output=True, cwd=ROOT, timeout=30)
        assert res.returncode == 0, "CHANGES-DEV.md не в .gitignore"

    def test_the_pipeline_never_mentions_the_dev_log(self):
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            assert "CHANGES-DEV" not in _read(path), path.name
        for path in (ROOT / "scripts").glob("*.py"):
            assert "CHANGES-DEV" not in path.read_text(encoding="utf-8"), path.name

    def test_release_notes_script_has_no_dev_flag(self):
        assert "--dev-changelog" not in (ROOT / "scripts" / "release_notes.py").read_text(
            encoding="utf-8")


class TestReleaseIncludesTheChangelog:
    def _wf(self) -> str:
        return _read(WORKFLOW)

    def test_release_notes_script_gets_the_changelog(self):
        assert "--changelog CHANGELOG.md" in self._wf()

    def test_changelog_is_attached_to_the_release(self):
        assert "CHANGELOG.md" in self._wf()

    def test_links_point_at_the_release_tag(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        links = release_notes.changelog_links("2.3.1", "v2.3.1")
        assert "/blob/v2.3.1/CHANGELOG.md" in links


class TestBuildBody:
    """Полное тело релиза: пользовательский текст + ссылка на CHANGELOG."""

    def test_body_carries_user_text_and_link(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        title, body = release_notes.build_body("v2.3.1", USER_LOG)
        assert title.startswith("v2.3.1 — ")
        assert "Кнопка обновления" in body        # текст для пользователей
        assert "owner/name/blob/v2.3.1/CHANGELOG.md" in body
        assert "<details>" not in body            # dev-блока больше нет

    def test_unknown_version_falls_back_to_links(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        title, body = release_notes.build_body("v9.9.9", USER_LOG)
        assert title == "v9.9.9"
        assert "CHANGELOG.md" in body

    def test_missing_changelog_does_not_break_the_release(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        title, body = release_notes.build_body("v2.3.1", ROOT / "nope.md")
        assert title == "v2.3.1"
        assert "CHANGELOG.md" in body


def test_changelog_has_a_title():
    first = _read(USER_LOG).splitlines()[0]
    assert first.startswith("# "), "CHANGELOG.md должен начинаться с заголовка"
