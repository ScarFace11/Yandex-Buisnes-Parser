# -*- coding: utf-8 -*-
"""Объявление версии: шаги announce-release.yml прогоняются на настоящих тегах.

Регресс, ради которого это написано: ручной запуск с тегом «2.3.4» (человек
пишет версию без «v», как она называется в CHANGELOG) уходил в
`gh release view 2.3.4`, такого тега в репозитории нет — шаг ожидания молча не
находил релиз и падал с «релиз не опубликован или без windows-архива», хотя
релиз v2.3.4 уже лежал опубликованным и с архивом. Поэтому проверяем:

  * тег нормализуется к «vX.Y.Z» и мусор гасится с внятной ошибкой;
  * шаг ожидания различает «не читается», «черновик», «нет windows-архива» и
    «готово», а не сообщает одну фразу на все случаи.

Шаги берутся прямо из workflow (один источник правды), bash-выражения
`${{ ... }}` подставляются как значения соответствующих env.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "announce-release.yml"
WINDOWS_ZIP = "YandexBusinessParser-windows-x64.zip"


def _wf():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(name_part: str) -> dict:
    for job in _wf()["jobs"].values():
        for step in job["steps"]:
            if name_part in step.get("name", ""):
                return step
    raise AssertionError(f"в announce-release.yml нет шага «{name_part}»")


def _bash():
    """Рабочий bash (в PATH на Windows раньше Git Bash может стоять WSL-шим)."""
    candidates = [shutil.which("bash"), os.environ.get("BASH"),
                  r"D:\Git\usr\bin\bash.exe",
                  r"C:\Program Files\Git\bin\bash.exe", "/bin/bash"]
    for cand in candidates:
        if not cand or not Path(cand).is_file():
            continue
        try:
            res = subprocess.run([cand, "-c", "echo ok"], capture_output=True,
                                 text=True, timeout=30)
        except Exception:
            continue
        if res.returncode == 0 and "ok" in res.stdout:
            return cand
    pytest.skip("нет рабочего bash, чтобы прогнать шаг воркфлоу")


GH_STUB = """#!/usr/bin/env bash
# Заглушка gh: тег берётся из $FAKE_TAG, релиз — из $FAKE_RELEASE_JSON,
# нет файла релиза → ошибка (релиз не читается).
args="$*"
if printf '%s' "$args" | grep -q -- "--jq .tagName"; then
  [ -f "$FAKE_TAG" ] && cat "$FAKE_TAG"
  exit 0
fi
if [ -f "$FAKE_RELEASE_JSON" ]; then
  cat "$FAKE_RELEASE_JSON"
  exit 0
fi
echo "release not found" >&2
exit 1
"""

# Тесты не должны ждать 15×10 секунд реального шага ожидания.
SLEEP_STUB = "#!/usr/bin/env bash\nexit 0\n"


def _run_step(tmp_path, name_part, *, env_extra=None, release=None,
              fake_tag=None):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("sleep", SLEEP_STUB)):
        stub = stub_dir / name
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    if release is not None:
        (tmp_path / "release.json").write_text(json.dumps(release), encoding="utf-8")
    if fake_tag is not None:
        (tmp_path / "tag.txt").write_text(fake_tag, encoding="utf-8")
    out = tmp_path / "gh_env.txt"
    out.write_text("", encoding="utf-8")
    # Ровно то, что GitHub Actions передаёт из блока env:
    # RELEASE_TAG ← github.event.release.tag_name, INPUT_TAG ← inputs.tag.
    script = _step(name_part)["run"]
    env = dict(os.environ)
    env.pop("TAG", None)
    env.pop("SKIP", None)
    env.pop("ANNOUNCED", None)
    env.update({
        "PATH": str(stub_dir) + os.pathsep + env.get("PATH", ""),
        "GITHUB_ENV": str(out),
        "FAKE_TAG": str(tmp_path / "tag.txt"),
        "FAKE_RELEASE_JSON": str(tmp_path / "release.json"),
        "GH_TOKEN": "x",
        "RELEASE_TAG": "",
        "INPUT_TAG": "",
    })
    env.update(env_extra or {})
    res = subprocess.run([_bash(), "-c", script], capture_output=True, env=env,
                         timeout=180)
    return (subprocess.CompletedProcess(res.args, res.returncode,
                                        res.stdout.decode("utf-8", "replace"),
                                        res.stderr.decode("utf-8", "replace")),
            out.read_text(encoding="utf-8"))


class TestTagResolution:
    """«2.3.4» и «v2.3.4» должны означать один и тот же релиз."""

    def _resolve(self, tmp_path, *, input_tag="", release_tag="", fake_tag=None):
        return _run_step(tmp_path, "Resolve the tag", fake_tag=fake_tag,
                         env_extra={"RELEASE_TAG": release_tag,
                                    "INPUT_TAG": input_tag})

    @pytest.mark.parametrize("given,expected", [
        ("2.3.4", "v2.3.4"),        # ручной запуск без «v» — тот самый случай
        ("v2.3.4", "v2.3.4"),
        ("V2.3.4", "v2.3.4"),
        (" 2.3.4 ", "v2.3.4"),      # случайный пробел при копировании
        ("2.2.1.1", "v2.2.1.1"),    # тег из четырёх чисел тоже существует
    ])
    def test_manual_input_is_normalized(self, tmp_path, given, expected):
        res, out = self._resolve(tmp_path, input_tag=given)
        assert res.returncode == 0, res.stdout + res.stderr
        assert f"TAG={expected}" in out

    def test_release_event_tag_is_kept(self, tmp_path):
        res, out = self._resolve(tmp_path, release_tag="v2.3.4")
        assert res.returncode == 0
        assert "TAG=v2.3.4" in out

    def test_scheduled_run_uses_the_latest_published_release(self, tmp_path):
        res, out = self._resolve(tmp_path, fake_tag="v2.3.4\n")
        assert res.returncode == 0
        assert "TAG=v2.3.4" in out

    @pytest.mark.parametrize("given", ["main", "v2.3", "release-2.3.4", "", "v", "latest"])
    def test_garbage_is_refused_loudly(self, tmp_path, given):
        res, out = self._resolve(tmp_path, input_tag=given)
        assert res.returncode == 1
        assert "::error::" in res.stdout
        assert "TAG=" not in out


class TestWaitStep:
    """Четыре состояния релиза — четыре разных сообщения."""

    def _wait(self, tmp_path, release, announced="2.3.3", tag="v2.3.4"):
        return _run_step(tmp_path, "Wait for the published", release=release,
                         env_extra={"TAG": tag, "ANNOUNCED": announced})

    def test_published_release_with_the_windows_zip_passes(self, tmp_path):
        res, _ = self._wait(tmp_path, {"isDraft": False, "assets": [
            {"name": WINDOWS_ZIP}, {"name": "CHANGELOG.md"}]})
        assert res.returncode == 0, res.stdout
        assert "опубликован" in res.stdout

    def test_draft_is_reported_as_a_draft(self, tmp_path):
        res, _ = self._wait(tmp_path, {"isDraft": True,
                                       "assets": [{"name": WINDOWS_ZIP}]})
        assert res.returncode == 1
        assert "draft" in res.stdout
        assert "::error::" in res.stdout

    def test_published_without_the_windows_zip_is_reported(self, tmp_path):
        res, _ = self._wait(tmp_path, {"isDraft": False,
                                       "assets": [{"name": "macos.zip"}]})
        assert res.returncode == 1
        assert "no-asset:macos.zip" in res.stdout
        assert WINDOWS_ZIP in res.stdout          # в ошибке видно, чего не хватает

    def test_unreadable_release_shows_the_real_reason(self, tmp_path):
        res, _ = self._wait(tmp_path, None)       # файла релиза нет → gh падает
        assert res.returncode == 1
        assert "release not found" in res.stdout
        assert "::error::" in res.stdout

    def test_already_announced_version_is_skipped(self, tmp_path):
        res, out = self._wait(tmp_path, None, announced="2.3.4")
        assert res.returncode == 0
        assert "SKIP=1" in out
