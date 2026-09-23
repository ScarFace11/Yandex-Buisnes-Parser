# -*- coding: utf-8 -*-
"""Две истории изменений: CHANGELOG.md (пользователям) и CHANGES-DEV.md (нам).

Инвариант проекта: одна правка заводит два раздела — пользовательский и
технический, с одним и тем же номером версии. На совпадении номеров держится
сборка релиза: тело GitHub Release берётся из CHANGELOG.md, а раздел
CHANGES-DEV.md той же версии уезжает свёрнутым блоком «Для разработчиков» —
и оба файла прикладываются к релизу как ассеты.
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
    """Номера версий в порядке появления: «## [2.3.1] — …»."""
    return re.findall(r"^##\s*\[([^\]]+)\]", text, re.M)


class TestFilesExist:
    def test_both_changelogs_are_in_the_repo(self):
        assert USER_LOG.exists(), "нет CHANGELOG.md"
        assert DEV_LOG.exists(), "нет CHANGES-DEV.md"

    def test_dev_log_points_to_the_user_log(self):
        assert "CHANGELOG.md" in _read(DEV_LOG)

    def test_user_log_points_to_the_dev_log(self):
        assert "CHANGES-DEV.md" in _read(USER_LOG)


class TestVersionInvariant:
    def test_both_files_cover_the_same_versions(self):
        user = versions(_read(USER_LOG))
        dev = versions(_read(DEV_LOG))
        assert user, "в CHANGELOG.md нет ни одной секции версии"
        assert dev, "в CHANGES-DEV.md нет ни одной секции версии"
        # Порядок тоже сверяем: свежие разделы сверху в обоих файлах.
        assert set(user) == set(dev), (
            "версии расходятся: только в CHANGELOG.md — "
            f"{sorted(set(user) - set(dev))}, только в CHANGES-DEV.md — "
            f"{sorted(set(dev) - set(user))}")

    def test_every_version_has_a_body_in_both_files(self):
        for path in (USER_LOG, DEV_LOG):
            text = _read(path)
            for v in versions(text):
                found = release_notes.extract_section(text, v)
                assert found is not None, f"{path.name}: нет раздела {v}"
                assert found[1].strip(), f"{path.name}: раздел {v} пуст"

    def test_current_app_version_is_documented_in_both_files(self):
        """Версия сборки обязана быть описана — иначе релиз уедет без заметок."""
        import config

        version = str(config.APP_VERSION).strip()
        for path in (USER_LOG, DEV_LOG):
            assert version in versions(_read(path)), (
                f"версия {version} из config.py не описана в {path.name}")

    def test_nothing_is_left_unreleased_after_a_release_section(self):
        """[Unreleased] — только сверху: он ещё не выпущен."""
        for path in (USER_LOG, DEV_LOG):
            vs = versions(_read(path))
            if "Unreleased" in vs:
                assert vs[0] == "Unreleased", (
                    f"{path.name}: раздел [Unreleased] должен быть первым")


class TestReleaseIncludesBothFiles:
    def _wf(self) -> str:
        return _read(WORKFLOW)

    def test_release_notes_script_gets_the_dev_changelog(self):
        assert "--dev-changelog" in self._wf()
        assert "CHANGES-DEV.md" in self._wf()

    def test_both_changelogs_are_attached_to_the_release(self):
        assert "CHANGELOG.md" in self._wf()

    def test_dev_section_is_collapsed_in_the_release_body(self):
        dev = release_notes.dev_section(DEV_LOG, "2.3.1")
        assert dev.startswith("<details>")
        assert "<summary>" in dev and "</details>" in dev
        assert "routes/update.py" in dev, "в блоке нет технических строк версии 2.3.1"

    def test_missing_dev_file_or_version_does_not_break_the_release(self):
        assert release_notes.dev_section(ROOT / "nope.md", "2.3.1") == ""
        assert release_notes.dev_section(DEV_LOG, "9.9.9") == ""
        assert release_notes.dev_section("", "2.3.1") == ""

    def test_links_point_at_the_release_tag(self):
        links = release_notes.changelog_links("2.3.1", "v2.3.1")
        assert "/blob/v2.3.1/CHANGELOG.md" in links
        assert "/blob/v2.3.1/CHANGES-DEV.md" in links


class TestBuildBody:
    """Полное тело релиза: пользовательский текст + dev-блок + ссылки."""

    def test_body_carries_user_text_dev_notes_and_links(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        title, body = release_notes.build_body("v2.3.1", USER_LOG, DEV_LOG)
        assert title.startswith("v2.3.1 — ")
        assert "Кнопка обновления" in body        # текст для пользователей
        assert "<details>" in body                # технические подробности
        assert "owner/name/blob/v2.3.1/CHANGES-DEV.md" in body

    def test_unknown_version_falls_back_to_links_and_no_dev_block(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/name")
        title, body = release_notes.build_body("v9.9.9", USER_LOG, DEV_LOG)
        assert title == "v9.9.9"
        assert "CHANGELOG.md" in body
        assert "<details>" not in body


@pytest.mark.parametrize("name", ["CHANGELOG.md", "CHANGES-DEV.md"])
def test_changelogs_have_a_title(name):
    first = _read(ROOT / name).splitlines()[0]
    assert first.startswith("# "), f"{name} должен начинаться с заголовка"
