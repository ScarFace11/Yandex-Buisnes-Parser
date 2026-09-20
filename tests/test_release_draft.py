# -*- coding: utf-8 -*-
"""Черновик релиза из CHANGELOG: экстрактор секции + job в build-exe.yml."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_notes  # noqa: E402


CHANGELOG = """# Changelog

Все заметные изменения проекта.

## [2.3.0] — Массовый обход соцсетей, UI-фиксы, macOS-сборка

Итог релиза: macOS-сборка и багфиксы.

### 🔴 Баги

- Фикс 1.
- Фикс 2.

## [2.2.1] — Старый релиз

Старое описание.
"""


class TestExtractSection:
    def test_extracts_body_and_subtitle(self):
        res = release_notes.extract_section(CHANGELOG, "2.3.0")
        assert res is not None
        subtitle, body = res
        assert subtitle == "Массовый обход соцсетей, UI-фиксы, macOS-сборка"
        assert "Итог релиза" in body
        assert "Фикс 1" in body
        # Секция не тянется в предыдущий релиз.
        assert "Старый релиз" not in body

    def test_missing_version_returns_none(self):
        assert release_notes.extract_section(CHANGELOG, "9.9.9") is None

    def test_heading_without_subtitle(self):
        res = release_notes.extract_section(
            "# Changelog\n\n## [2.3.0]\n\nТело.\n", "2.3.0")
        assert res == ("", "Тело.")


class TestScript:
    def test_script_parses(self):
        ast.parse((ROOT / "scripts" / "release_notes.py").read_text("utf-8"))

    def test_real_changelog_has_release_section(self):
        # Релизные теги должны находить свою секцию в живом CHANGELOG.
        import re
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        versions = re.findall(r"^##\s*\[([^\]]+)\]", text, re.M)
        assert versions, "в CHANGELOG нет ни одной секции версии"
        for v in versions:
            assert release_notes.extract_section(text, v) is not None, v


class TestWorkflow:
    def _wf(self):
        return (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(
            encoding="utf-8")

    def test_release_draft_job_exists_and_creates_a_draft(self):
        wf = self._wf()
        assert "release-draft:" in wf
        assert "gh release create" in wf
        assert "--draft" in wf
        assert "--notes-file release_notes.md" in wf
        # Тело берётся из CHANGELOG скриптом.
        assert "scripts/release_notes.py" in wf

    def test_release_draft_runs_only_on_tags_and_before_build(self):
        wf = self._wf()
        assert "if: startsWith(github.ref, 'refs/tags/v')" in wf
        # Сборка ждёт черновик (или его пропуск на workflow_dispatch).
        assert "needs: [test, release-draft]" in wf
        assert "needs.release-draft.result == 'skipped'" in wf

    def test_existing_release_is_not_overwritten(self):
        wf = self._wf()
        assert "gh release view" in wf

    def test_attach_step_no_longer_rewrites_notes(self):
        # Тело уже в черновике — softprops не должен его затирать авто-заметками.
        wf = self._wf()
        assert "generate_release_notes: true" not in wf

    def test_workflow_yaml_parses(self):
        # pyyaml входит в requirements (Dev / Testing) — на CI модуль есть.
        pytest.importorskip("yaml", reason="pyyaml не установлен")
        import yaml
        yaml.safe_load(self._wf())
