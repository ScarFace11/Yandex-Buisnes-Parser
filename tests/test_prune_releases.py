# -*- coding: utf-8 -*-
"""Уборка архивов старых релизов: удаляются только архивы, релиз остаётся.

Проверяем три обещания инструмента (scripts/prune_releases.py):
  1. порог по версии считается правильно, а непонятная версия не трогается;
  2. без --apply ничего не удаляется — это отчёт;
  3. удаляются ровно выбранные архивы старых версий, а тег, название и
     описание релиза не меняются (в workflow нет ни одного вызова, который
     правит или удаляет релиз).
"""
import json
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import prune_releases as prune  # noqa: E402

WF = ROOT / ".github" / "workflows" / "prune-releases.yml"


def _sample():
    """Набор релизов, как он приходит из API: id ассетов сквозные."""
    uid = iter(range(1, 100))

    def rel(tag, name, assets):
        return {"tag_name": tag, "name": name,
                "assets": [{"id": next(uid), "name": n, "size": s}
                           for n, s in assets]}
    return [
        rel("v2.3.4", "v2.3.4 — Свежая", [
            ("YandexBusinessParser-windows-x64.zip", 90_000_000),
            ("YandexBusinessParser-macos-arm64.dmg", 40_000_000),
            ("CHANGELOG.md", 1000)]),
        rel("v2.3.3", "v2.3.3 — Прошлая", [
            ("YandexBusinessParser-windows-x64.zip", 80_000_000),
            ("CHANGELOG.md", 1000)]),
        rel("v2.2.0", "", [
            ("YandexBusinessParser-windows-x64.zip", 70_000_000)]),
        rel("nightly", "не версия", [
            ("YandexBusinessParser-windows-x64.zip", 10)]),
    ]


SAMPLE = _sample()


class TestVersionOrder:
    def test_long_versions_compare_numerically(self):
        assert prune.is_below("2.3.9", "2.3.10")
        assert not prune.is_below("2.3.10", "2.3.9")

    def test_missing_parts_are_zero(self):
        assert not prune.is_below("2.3", "2.3.0")
        assert prune.is_below("2.3", "2.3.1")

    def test_unparsed_version_is_never_below(self):
        assert not prune.is_below("nightly", "2.3.4")
        assert not prune.is_below("", "2.3.4")

    def test_strip_tag(self):
        assert prune.strip_tag("v2.3.4") == "2.3.4"
        assert prune.strip_tag("2.3.4") == "2.3.4"


class TestPlan:
    def test_only_archives_below_the_threshold_are_chosen(self):
        victims = {(p["tag"], p["asset"]) for p in prune.build_plan(SAMPLE, "2.3.4")
                   if p["delete"]}
        assert victims == {
            ("v2.3.3", "YandexBusinessParser-windows-x64.zip"),
            ("v2.2.0", "YandexBusinessParser-windows-x64.zip"),
        }

    def test_the_threshold_release_itself_is_kept(self):
        plan = prune.build_plan(SAMPLE, "2.3.4")
        assert not [p for p in plan if p["tag"] == "v2.3.4" and p["delete"]]

    def test_changelog_is_never_deleted(self):
        plan = prune.build_plan(SAMPLE, "2.3.4")
        assert not [p for p in plan if p["asset"] == "CHANGELOG.md" and p["delete"]]

    def test_versionless_release_is_left_alone(self):
        plan = prune.build_plan(SAMPLE, "2.3.4")
        assert not [p for p in plan if p["tag"] == "nightly" and p["delete"]]

    def test_pattern_narrows_what_is_deleted(self):
        plan = prune.build_plan(SAMPLE, "2.3.4", ("*.dmg",))
        assert not [p for p in plan if p["delete"]]

    def test_summary_counts_the_freed_space(self):
        s = prune.summarize(prune.build_plan(SAMPLE, "2.3.4"))
        assert s["assets_to_delete"] == 2
        assert s["bytes_to_free"] == 150_000_000
        assert s["versions"] == ["2.2.0", "2.3.3"]


class TestRunner:
    def _main(self, *argv):
        old = sys.argv
        sys.argv = ["prune_releases.py", *argv]
        try:
            return prune.main()
        finally:
            sys.argv = old

    def _fixture(self, tmp_path):
        f = tmp_path / "releases.json"
        f.write_text(json.dumps(SAMPLE), encoding="utf-8")
        return f

    def test_report_mode_never_deletes(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(prune, "delete_asset",
                            lambda *a, **k: called.append(a))
        out = tmp_path / "report.json"
        rc = self._main("--from-json", str(self._fixture(tmp_path)),
                        "--below", "2.3.4", "--json", str(out))
        assert rc == 0
        assert called == []
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["assets_to_delete"] == 2
        assert report["deleted"] == 0
        assert report["applied"] is False

    def test_apply_deletes_exactly_the_planned_assets(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(prune, "delete_asset",
                            lambda repo, token, asset_id: seen.append(asset_id))
        fixture = self._fixture(tmp_path)
        out = tmp_path / "report.json"
        rc = self._main("--from-json", str(fixture), "--below", "2.3.4",
                        "--apply", "--token", "test-token", "--json", str(out))
        assert rc == 0
        planned = [p["asset_id"] for p in
                   prune.build_plan(prune.load_releases_from_json(fixture), "2.3.4")
                   if p["delete"]]
        assert seen == planned
        assert json.loads(out.read_text(encoding="utf-8"))["deleted"] == len(planned)

    def test_below_min_reads_the_threshold_from_version_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prune, "delete_asset", lambda *a, **k: None)
        vj = tmp_path / "version.json"
        vj.write_text(json.dumps({"version": "2.3.4", "min_version": "v2.3.4"}),
                      encoding="utf-8")
        out = tmp_path / "report.json"
        rc = self._main("--from-json", str(self._fixture(tmp_path)),
                        "--below-min", "--version-json", str(vj),
                        "--json", str(out))
        assert rc == 0
        assert json.loads(out.read_text(encoding="utf-8"))["threshold"] == "2.3.4"
        assert json.loads(out.read_text(encoding="utf-8"))["assets_to_delete"] == 2

    def test_missing_min_version_is_an_error(self, tmp_path):
        vj = tmp_path / "version.json"
        vj.write_text("{}", encoding="utf-8")
        assert self._main("--from-json", str(self._fixture(tmp_path)),
                          "--below-min", "--version-json", str(vj)) == 1

    def test_summary_is_written_for_the_step_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prune, "delete_asset", lambda *a, **k: None)
        summary = tmp_path / "summary.md"
        rc = self._main("--from-json", str(self._fixture(tmp_path)),
                        "--below", "2.3.4", "--summary", str(summary))
        assert rc == 0
        md = summary.read_text(encoding="utf-8")
        assert "v2.2.0" in md and "v2.3.3" in md
        assert "размер" in md.lower() or "|" in md


class TestWebInventory:
    """Отчёт без токена: теги из git, файлы — из HTML-страницы релиза."""

    HTML = (
        '<a href="/o/r/releases/download/v2.3.3/'
        'YandexBusinessParser-windows-x64.zip">x</a><span>80 MB</span>'
        '<a href="/o/r/releases/download/v2.3.3/CHANGELOG.md">y</a>'
        '<span>12 KB</span>')

    def test_assets_and_sizes_are_parsed(self):
        assets = prune.parse_expanded_assets(self.HTML)
        assert [a["name"] for a in assets] == [
            "YandexBusinessParser-windows-x64.zip", "CHANGELOG.md"]
        assert assets[0]["size"] == 80 * 1024 ** 2
        assert assets[1]["size"] == 12 * 1024
        assert assets[0]["id"] is None

    def test_duplicates_are_collapsed(self):
        assert len(prune.parse_expanded_assets(self.HTML + self.HTML)) == 2

    def test_web_inventory_refuses_to_delete(self):
        # У файла из HTML нет id — удаление через API невозможно, и делать
        # вид, что оно прошло, нельзя.
        old = sys.argv
        sys.argv = ["prune_releases.py", "--from-web", "--apply",
                    "--below", "2.3.4", "--repo", "o/r"]
        try:
            assert prune.main() == 1
        finally:
            sys.argv = old


def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _prune_steps():
    return _wf()["jobs"]["prune"]["steps"]


def _run_script():
    return "\n".join(s.get("run", "") for s in _prune_steps())


class TestWorkflow:
    def test_dry_run_is_the_default(self):
        # yaml 1.1 читает "on" как True — ключ триггера ищем по обоим вариантам.
        wf = _wf()
        triggers = wf.get("on") or wf.get(True) or {}
        inputs = triggers["workflow_dispatch"]["inputs"]
        assert inputs["dry_run"]["default"] is True
        assert inputs["below"]["default"] == ""
        assert inputs["patterns"]["default"] == "*.zip,*.dmg"

    def test_it_can_write_assets_but_only_when_asked(self):
        wf = _wf()
        assert wf["permissions"]["contents"] == "write"
        run = _run_script()
        assert "prune_releases.py" in run
        assert "--apply" in run and "dry_run" in run

    def test_it_never_deletes_or_edits_a_release(self):
        run = _run_script()
        for forbidden in ("gh release delete", "gh release edit", "--delete-tag",
                          "--notes", "--draft=false"):
            assert forbidden not in run, f"уборка не должна трогать релиз: {forbidden}"

    def test_the_report_lands_in_the_step_summary(self):
        assert "GITHUB_STEP_SUMMARY" in _run_script()

    def test_the_script_is_tracked_and_importable(self):
        assert (ROOT / "scripts" / "prune_releases.py").exists()
        assert prune.DEFAULT_PATTERNS == ("*.zip", "*.dmg")
