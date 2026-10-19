# -*- coding: utf-8 -*-
"""Ручная сборка «как есть»: .github/workflows/build-manual.yml.

Пользователь запускает воркфлоу кнопкой в Actions (workflow_dispatch) и
скачивает готовый .exe / .zip из артефактов запуска. Здесь зафиксированы
инварианты, ради которых он и делался:

* срабатывает только вручную — ни push, ни тегов;
* НЕ создаёт релиз и НЕ меняет версию (version.json не трогается);
* артефакты есть и для Windows, и для macOS, и они скачиваемые.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

WORKFLOW = ROOT / ".github" / "workflows" / "build-manual.yml"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def _wf():
    # PyYAML читает ключ `on:` как булево True.
    return yaml.safe_load(_text())


def test_manual_dispatch_is_the_only_trigger():
    assert set(_wf()[True]) == {"workflow_dispatch"}


def test_no_release_and_no_version_bump():
    # Комментарии объясняют, чего workflow НЕ делает, — проверяем только код.
    code = "\n".join(ln for ln in _text().splitlines()
                     if not ln.lstrip().startswith("#"))
    for forbidden in ("softprops/action-gh-release", "gh release",
                      "git tag", "version.json", "CHANGELOG.md"):
        assert forbidden not in code, f"ручная сборка не должна: {forbidden}"
    # Только чтение репозитория — релиз/тег создать нечем.
    assert "contents: read" in code


def test_both_platforms_upload_downloadable_artifacts():
    jobs = _wf()["jobs"]
    assert {"windows", "macos"} <= set(jobs)
    uploads = [step for job in jobs.values() for step in job["steps"]
               if str(step.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(uploads) == 2, "по одному артефакту на Windows и на macOS"
    for step in uploads:
        assert step["with"]["path"], "артефакт без пути нечего качать"
        assert "retention-days" in step["with"]


def test_target_input_lets_you_pick_one_platform():
    inputs = _wf()[True]["workflow_dispatch"]["inputs"]
    assert set(inputs["target"]["options"]) == {"both", "windows", "macos"}
    assert inputs["target"]["default"] == "both"


def test_windows_build_is_smoke_tested_before_uploading():
    steps = _wf()["jobs"]["windows"]["steps"]
    names = [str(s.get("name", "")).lower() for s in steps]
    assert any("smoke" in n for n in names), "без проверки запуска .exe можно выложить битый файл"


def test_build_specs_used_by_the_workflow_exist():
    text = _text()
    assert "parser.spec" in text and "parser-mac.spec" in text
    assert (ROOT / "parser.spec").is_file()
    assert (ROOT / "parser-mac.spec").is_file()


# ── Локальная сборка (build.bat / build-mac.sh) ───────────────

WIN_SCRIPT = ROOT / "build.bat"
MAC_SCRIPT = ROOT / "build-mac.sh"


def _code(path):
    """Строки скрипта без комментариев (rem/#) — проверяем только код."""
    return "\n".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith(("rem ", "#", "::")))


class TestLocalBuildScripts:
    """Сборка на своей машине: без пуша и без смены версии."""

    def test_both_platforms_have_a_local_script(self):
        assert WIN_SCRIPT.is_file(), "нет build.bat для Windows"
        assert MAC_SCRIPT.is_file(), "нет build-mac.sh для macOS"

    def test_windows_script_uses_the_windows_spec(self):
        code = _code(WIN_SCRIPT)
        assert "PyInstaller parser.spec" in code
        assert ".venv\\Scripts\\python.exe" in code, \
            "локальная сборка идёт из venv проекта"

    def test_mac_script_uses_the_mac_spec(self):
        code = _code(MAC_SCRIPT)
        assert "parser-mac.spec" in code
        assert "dist-mac" in code

    def test_mac_script_refuses_other_systems(self):
        assert 'uname -s' in MAC_SCRIPT.read_text(encoding="utf-8")

    @pytest.mark.parametrize("path", [WIN_SCRIPT, MAC_SCRIPT],
                             ids=["windows", "macos"])
    def test_local_builds_touch_no_version_and_push_nothing(self, path):
        """Версия берётся из репозитория как есть: это не релиз."""
        code = _code(path)
        for forbidden in ("stamp_version", "version.json",
                          "git push", "git tag", "gh release"):
            assert forbidden not in code, f"{path.name}: локальная сборка не должна {forbidden}"

    def test_local_builds_are_documented(self):
        """Инструкции по локальной сборке должны быть в репозитории.

        README у пользователя короткий, поэтому инструкции живут в
        docs/build.md — но отсутствовать они не могут: без них собрать
        приложение у себя нечем.
        """
        docs = (ROOT / "docs" / "build.md").read_text(encoding="utf-8")
        assert "build-mac.sh" in docs
        assert "build.bat" in docs, "у локальной сборки Windows нет инструкции"
        assert "build-manual.yml" in docs, "вторая платформа собирается в Actions"

    def test_readme_links_the_build_docs(self):
        """Из короткого README инструкция по сборке должна быть достижима."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "docs/build.md" in readme, "README не ссылается на инструкцию по сборке"