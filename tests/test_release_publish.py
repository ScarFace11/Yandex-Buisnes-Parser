# -*- coding: utf-8 -*-
"""Автопубликация релиза: черновик публикуется сам, когда оба билда зелёные.

Почему это отдельный воркфлоу и почему именно так:

* публикация — это момент, когда у ВСЕХ установленных приложений включается
  авто-обновление, поэтому она не должна быть шагом внутри сборки: сборка
  Windows не знает, чем закончилась сборка macOS;
* воркфлоу .github/workflows/publish-release.yml запускается завершением
  обоих билдов (workflow_run) и публикует черновик, только если:
  у тега зелёные обе сборки, на черновике лежат все файлы, а сам он ещё
  черновик (иначе повторный запуск ничего не делает);
* dev- и rc-теги автоматика не публикует — это внутренние сборки;
* version.json здесь не пишется: его обновляет announce-release.yml уже
  ПОСЛЕ публикации, иначе приложения обещали бы недоступное обновление.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH = WORKFLOWS / "publish-release.yml"
WINDOWS_BUILD = WORKFLOWS / "build-exe.yml"
MACOS_BUILD = WORKFLOWS / "build-macos.yml"


def text(path=PUBLISH):
    return path.read_text(encoding="utf-8")


def code(path=PUBLISH):
    """Строки без комментариев: проверяем только то, что реально выполнится."""
    return "\n".join(ln for ln in text(path).splitlines()
                     if not ln.lstrip().startswith("#"))


def wf(path=PUBLISH):
    # PyYAML читает ключ `on:` как булево True.
    return yaml.safe_load(text(path))


def trigger():
    data = wf()
    return data.get("on", data.get(True))


# ── Триггеры ──────────────────────────────────────────────────

class TestTriggers:
    def test_runs_when_either_build_finishes(self):
        wr = trigger()["workflow_run"]
        assert wr["types"] == ["completed"]
        assert set(wr["workflows"]) == {"Build Windows EXE", "Build macOS .app"}

    def test_workflow_names_match_the_real_builds(self):
        for name, path in (("Build Windows EXE", WINDOWS_BUILD),
                           ("Build macOS .app", MACOS_BUILD)):
            assert wf(path)["name"] == name, f"{path.name}: имя workflow изменилось"

    def test_manual_run_can_publish_an_already_built_tag(self):
        """Аварийный выход: черновик собрали до появления автоматики."""
        assert trigger()["workflow_dispatch"]["inputs"]["tag"]["required"] is True


# ── Права и место в конвейере ─────────────────────────────────

class TestPermissionsAndScope:
    def test_can_publish_a_release_and_read_run_statuses(self):
        perms = wf()["permissions"]
        assert perms["contents"] == "write"
        assert perms["actions"] == "read"

    def test_publishing_is_not_scattered_across_the_builds(self):
        """Черновик публикует ровно один workflow — иначе гонка за релиз."""
        owners = [p.name for p in WORKFLOWS.glob("*.yml") if "--draft=false" in text(p)]
        assert owners == [PUBLISH.name], owners

    def test_nothing_is_rebuilt_here(self):
        body = code()
        for forbidden in ("pyinstaller", "pip install", "stamp_version",
                          "version.json", "actions/checkout"):
            assert forbidden not in body, f"публикация не должна: {forbidden}"


# ── Гейты: обе сборки, файлы, статус черновика ────────────────

class TestGates:
    def test_both_builds_must_be_green(self):
        body = code()
        for workflow_file in ("build-exe.yml", "build-macos.yml"):
            assert workflow_file in body, f"не проверяется статус {workflow_file}"
        # Успехом считается только success; всё остальное либо ждёт, либо стоп.
        assert re.search(r"^\s*success\)", body, re.M), "success — не единственный пропуск"
        for bad in ("failure", "cancelled", "timed_out"):
            assert bad in body

    def test_a_failed_build_stops_the_publication(self):
        body = code()
        assert "exit 1" in body and "::error::" in body
        assert body.index("exit 1") < body.index("gh release edit"), \
            "падение сборки обязано остановить работУ до публикации"

    def test_the_wait_is_bounded(self):
        """Ожидание конечно: иначе job висел бы в очереди сутками."""
        body = code()
        attempts = int(re.search(r"PWAIT_ATTEMPTS:-\s*(\d+)", body).group(1))
        pause = int(re.search(r"PWAIT_SLEEP:-\s*(\d+)", body).group(1))
        assert 1 <= attempts <= 60
        assert 5 <= pause <= 120
        assert attempts * pause <= 30 * 60, "суммарное ожидание больше получаса"

    def test_required_assets_match_what_the_builds_produce(self):
        required = wf()["jobs"]["publish"]["env"]["REQUIRED_ASSETS"].split()
        assert required == [
            "YandexBusinessParser-windows-x64.zip",
            "YandexBusinessParser-macos-arm64.zip",
            "YandexBusinessParser-macos-x64.zip",
            "CHANGELOG.md",
        ]
        # Каждый файл обязан реально появляться в сборке — иначе публикация
        # зависнет навсегда, а релиз будет без архива.
        assert "YandexBusinessParser-windows-x64.zip" in text(WINDOWS_BUILD)
        assert "CHANGELOG.md" in text(WINDOWS_BUILD)
        macos = text(MACOS_BUILD)
        assert "YandexBusinessParser-macos-$ARCH.zip" in macos
        assert 'asset_arch: arm64' in macos and 'asset_arch: x64' in macos

    def test_missing_assets_block_the_publication(self):
        body = code()
        assert "REQUIRED_ASSETS" in body
        assert "missing" in body
        assert 'grep -qx "$need"' in body

    def test_already_published_release_is_a_noop(self):
        body = code()
        assert ".isDraft" in body
        assert '"$draft" != "true"' in body

    def test_publishes_by_flipping_the_draft_flag(self):
        body = code()
        assert 'gh release edit "$TAG"' in body
        assert "--draft=false" in body


# ── Логика ожидания: гоняем сам скрипт на заглушке gh ────────

def _bash():
    """Рабочий bash: на Windows в PATH раньше Git Bash может стоять WSL-шим."""
    import os
    import shutil
    candidates = [shutil.which("bash"), os.environ.get("BASH"),
                  r"D:\Git\usr\bin\bash.exe",
                  r"C:\Program Files\Git\bin\bash.exe", "/bin/bash"]
    for cand in candidates:
        if not cand or not Path(cand).exists():
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
# Заглушка gh: отдаёт заранее заданные статусы запусков.
# Файл $FAKE_DIR/<workflow> — очередь строк «status conclusion»;
# последняя строка повторяется бесконечно.
wf=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--workflow" ]; then wf="$2"; shift 2; continue; fi
  shift
done
file="$FAKE_DIR/$wf"
[ -f "$file" ] || { echo 'missing '; exit 0; }
line="$(head -1 "$file")"
if [ "$(wc -l < "$file")" -gt 1 ]; then
  tail -n +2 "$file" > "$file.next" && mv "$file.next" "$file"
fi
printf '%s\n' "$line"
"""


def _step_script(step_id: str) -> str:
    for job in wf()["jobs"].values():
        for step in job["steps"]:
            if step.get("id") == step_id:
                # Actions подставляет выражения ДО выполнения — повторяем это.
                return (step["run"]
                        .replace("${{ steps.tag.outputs.tag }}", "v2.3.4")
                        .replace("${{ github.repository }}", "owner/name"))
    raise AssertionError(f"в publish-release.yml нет шага id={step_id}")


def _run_wait_step(tmp_path, exe_states, macos_states, attempts="2", pause="1"):
    """Прогон шага «Wait for both builds to be green» с заглушкой gh."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    gh = stub_dir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    # Файла нет → заглушка отвечает «missing» (запуска сборки ещё не было).
    for name, states in (("build-exe.yml", exe_states),
                         ("build-macos.yml", macos_states)):
        if states:
            (tmp_path / name).write_text("\n".join(states) + "\n", encoding="utf-8")
    out = tmp_path / "gh_output.txt"
    out.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "PATH": str(stub_dir) + os.pathsep + env.get("PATH", ""),
        "FAKE_DIR": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "REPO": "owner/name",
        "RAW_TAG": "v2.3.4",
        "PWAIT_ATTEMPTS": attempts,
        "PWAIT_SLEEP": pause,
    })
    res = subprocess.run([_bash(), "-c", _step_script("builds")],
                         capture_output=True, env=env, timeout=180)
    # bash пишет UTF-8, а подпроцесс на Windows читается в системной кодировке —
    # поэтому декодируем явно.
    return (subprocess.CompletedProcess(
                res.args, res.returncode,
                res.stdout.decode("utf-8", "replace"),
                res.stderr.decode("utf-8", "replace")),
            out.read_text(encoding="utf-8"))


class TestWaitLogic:
    """Шаг ожидания прогоняется целиком — на заглушке вместо gh."""

    def test_both_green_lets_the_publication_pass(self, tmp_path):
        res, out = _run_wait_step(tmp_path, ["completed success"],
                                 ["completed success"])
        assert res.returncode == 0, res.stderr
        assert "ok=true" in out
        assert "Обе сборки зелёные" in res.stdout

    def test_failed_build_blocks_the_publication(self, tmp_path):
        res, out = _run_wait_step(tmp_path, ["completed success"],
                                 ["completed failure"])
        assert res.returncode == 1
        assert "::error::" in res.stdout
        assert "ok=true" not in out

    def test_second_build_finishing_later_still_publishes(self, tmp_path):
        """Первый билд завершился раньше — публикуем по завершению второго."""
        res, out = _run_wait_step(tmp_path, ["completed success"],
                                 ["in_progress", "completed success"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert "Ждём ещё:" in res.stdout
        assert "ok=true" in out

    def test_never_green_times_out_without_publishing(self, tmp_path):
        res, out = _run_wait_step(tmp_path, ["completed success"],
                                 ["in_progress"], attempts="2")
        assert res.returncode == 1
        assert "публикация отложена" in res.stdout
        assert "ok=true" not in out

    def test_missing_run_is_treated_as_pending(self, tmp_path):
        """Сборка ещё не запускалась — это не успех и не провал."""
        res, out = _run_wait_step(tmp_path, ["completed success"], [], attempts="1")
        assert res.returncode == 1
        assert "missing" in res.stdout


# ── Какие теги автоматика не трогает ──────────────────────────

class TestOnlyStableTags:
    def _pattern(self):
        found = re.search(r"grep -Eq '([^']+)'", code())
        assert found, "в workflow нет проверки формата тега"
        return re.compile(found.group(1))

    @pytest.mark.parametrize("tag", ["v2.3.4", "v2.2.1.1", "v10.0.0"])
    def test_stable_tags_are_published(self, tag):
        assert self._pattern().match(tag)

    @pytest.mark.parametrize("tag", ["v2.3.4-dev", "v2.3.4-rc1", "main",
                                     "2.3.4", "v2.3", "release-2.3.4"])
    def test_dev_and_other_tags_are_left_alone(self, tag):
        assert not self._pattern().match(tag)

    def test_dev_versions_cannot_be_auto_published(self, monkeypatch):
        """То же правило, что и у сборки: DEV-версия — не публичный релиз."""
        import config
        monkeypatch.setattr(config, "APP_VERSION", "2.3.4-dev")
        assert config.is_dev_build() is True
        assert not self._pattern().match("v2.3.4-dev")
        assert not self._pattern().match("v" + str(config.APP_VERSION))


# ── Ручной ввод тега: шаг прогоняется целиком ────────────────

def _run_tag_step(tmp_path, raw_tag, input_tag=""):
    """Прогон шага «Check the tag» с теми же env, что даёт GitHub Actions."""
    out = tmp_path / "gh_output.txt"
    out.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "GITHUB_OUTPUT": str(out),
        "REPO": "owner/name",
        "RAW_TAG": raw_tag,
        "INPUT_TAG": input_tag,
    })
    res = subprocess.run([_bash(), "-c", _step_script("tag")],
                         capture_output=True, env=env, timeout=120)
    return (subprocess.CompletedProcess(
                res.args, res.returncode,
                res.stdout.decode("utf-8", "replace"),
                res.stderr.decode("utf-8", "replace")),
            out.read_text(encoding="utf-8"))


class TestManualTagInput:
    """Человек называет версию без «v» — публикация всё равно должна найти тег."""

    @pytest.mark.parametrize("given,expected", [
        ("2.3.4", "v2.3.4"), ("v2.3.4", "v2.3.4"),
        ("V2.3.4", "v2.3.4"), (" 2.3.4 ", "v2.3.4"), ("2.2.1.1", "v2.2.1.1"),
    ])
    def test_manual_input_is_normalized_and_published(self, tmp_path, given, expected):
        res, out = _run_tag_step(tmp_path, given, input_tag=given)
        assert res.returncode == 0, res.stdout + res.stderr
        assert f"tag={expected}" in out
        assert "publish=true" in out

    def test_manual_input_with_a_bad_tag_fails_loudly(self, tmp_path):
        """Ручной запуск — осознанное действие: молчаливое «нечего делать» врёт."""
        res, out = _run_tag_step(tmp_path, "2.3.4-rc1", input_tag="2.3.4-rc1")
        assert res.returncode == 1
        assert "::error::" in res.stdout
        assert "publish=true" not in out

    @pytest.mark.parametrize("branch", ["main", "v2.3.4-dev", "feature/x"])
    def test_a_push_to_a_non_release_tag_stays_a_quiet_noop(self, tmp_path, branch):
        """Пуш ветки/dev-тега ничего не публикует — но и не краснит конвейер."""
        res, out = _run_tag_step(tmp_path, branch)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "publish=false" in out
        assert "::error::" not in res.stdout
