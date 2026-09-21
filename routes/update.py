"""In-app self-update for the frozen Windows build.

The swap step is Windows-only: it waits for the process to exit and replaces
files with a generated updater.bat. On macOS the app is a .app bundle that a
signed/quarantined copy of the running process cannot safely overwrite, so
there the app only REPORTS that a newer version exists and the UI points at
the release page (auto_apply=false). Everything else (frozen? dev? which
version is newer) works the same on both platforms.

Flow (all triggered from the web UI):
  GET  /update/status   — frozen? current vs latest version? update available?
  GET  /update/download — stream the release zip to a temp file
  POST /update/apply    — extract, verify, swap via updater.bat, restart the app

Failure modes this module specifically guards against — all three were
reported as «скачал обновление, консоль закрылась, версия та же»:

1. STALE RELEASE LINK. version.json on main used to be stamped with a
   `releases/latest/download/...` alias, but while the new release is still
   a DRAFT (or after it was deleted) that alias silently resolves to the
   PREVIOUS published release: the updater downloads the build the user is
   already running and "installs" it — a no-op that looks like a failed
   update. So only an URL pinned to the advertised version
   (`releases/download/v<latest>/...`) is accepted, otherwise the asset is
   resolved through the API by EXACT tag (`releases/tags/v<latest>`, which
   answers 404 for drafts), and the version inside the downloaded zip is
   verified before anything on disk is touched.

2. SCRIPT THAT NEVER RUNS. v2.3.0 wrote updater.bat with
   `write_text("\r\n".join(lines))` in TEXT mode: every line ended with
   CR CR LF, cmd.exe aborted the script before the first swap command, the
   app had already exited — nothing was copied and the old version stayed.
   The script is now written with newline="" (exact CR LF) and validated
   byte-for-byte before it is launched.

3. HALF-DONE SWAP / LOST DATA. The old bat waited for the process with
   `tasklist | find` + `timeout` (a non-Windows `find` on PATH breaks the
   wait; `timeout` cannot run without a console), moved EVERY entry of the
   app folder — including .env, logs/ and output/ — into _backup and then
   deleted _update with the backup inside it, i.e. it destroyed the user's
   keys and results. The new bat waits for an explicit exit marker written
   by the app, retries locked moves, verifies the result, ROLLS BACK to the
   backup on any failure and moves only app-owned files (exe, _internal,
   ...) — user data stays where it is. Every step is appended to
   _update/update.log for diagnosability.

Swap strategy (a running .exe cannot overwrite itself on Windows):
  1. Extract the downloaded zip to <user_dir>/_update/
  2. Verify the new exe/_internal and that its version >= advertised
  3. Write _update/updater.bat which:
       waits for the app.exit marker (the app writes it right before exit),
       backs up ONLY the app files to _update/_backup/,
       moves the new files into place (retrying while files are locked),
       starts the new exe; on any failure restores the backup;
       keeps _backup (rollback) and update.log, cleans the rest
  4. Respond ok, write the app.exit marker, stop the app

From source (not frozen) the endpoints report frozen=False and the UI
hides the self-update button — update via git pull instead.
"""
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    import paths
except Exception:
    paths = None

bp = Blueprint("update", __name__)

APP_DIR_NAME = "YandexBusinessParser"     # top-level folder inside the release zip
EXE_NAME = "YandexBusinessParser.exe"
ZIP_ASSET_NAME = "YandexBusinessParser-windows-x64.zip"
STATE_FILE = "_update_state.json"         # progress for /update/status polling
ASSET_CACHE_TTL = 10 * 60                 # секунд: кэш проверки релиза по API
EXIT_MARKER = "app.exit"                  # the app writes this right before exiting
LOG_FILE = "update.log"                   # updater.bat trace, for diagnostics

# popen kwargs that work the same on all supported Python versions
_DETACHED = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0), "close_fds": True}


def _is_frozen() -> bool:
    return bool(paths and paths.is_frozen())


def _self_update_supported() -> bool:
    """Менять файлы на диске умеет только Windows-сборка (updater.bat + exe).

    macOS-версия — .app-бандл: подмена файлов запущенного бандла ломает
    подпись, а сам он может лежать в /Applications без права на запись.
    Поэтому там авто-обновление не предлагается — показываем «Доступна новая
    версия» и ссылку на страницу релизов.
    """
    import sys
    return sys.platform.startswith("win")


def _platform_refusal() -> dict:
    return {"ok": False,
            "error": "Авто-обновление доступно только в сборке для Windows. "
                     "Скачайте новую версию со страницы релизов."}


def _is_dev() -> bool:
    """Сборка разработчика: авто-обновление отключено целиком.

    Публичный релиз не должен затирать dev-сборку (и наоборот), поэтому в
    dev-режиме мы даже не ходим на GitHub за версией: ни баннера, ни кнопки
    «Обновить сейчас», ни замены файлов.
    """
    try:
        from config import is_dev_build
        return bool(is_dev_build())
    except Exception:
        return False


def _dev_refusal() -> dict:
    return {"ok": False,
            "error": "Это DEV-сборка: авто-обновление отключено. "
                     "Публичный релиз ставится из обычной сборки."}


def _user_dir() -> Path:
    return Path(paths.user_dir()) if paths else Path.cwd()


def _app_root() -> Path:
    """Folder that contains the exe and _internal/ (works for onefile too)."""
    if paths and paths.is_frozen():
        return Path(sys_executable()).resolve().parent
    return Path(__file__).resolve().parent.parent


def sys_executable() -> str:
    import sys
    return sys.executable


def _work_dir() -> Path:
    d = _user_dir() / "_update"
    d.mkdir(exist_ok=True)
    return d


def _state() -> dict:
    f = _work_dir() / STATE_FILE
    if f.exists():
        try:
            return _json_load(f)
        except Exception:
            pass
    return {}


def _json_load(f: Path) -> dict:
    import json
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


def _save_state(**kw) -> None:
    import json
    data = _state()
    data.update(kw)
    with open(_work_dir() / STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _remote_meta() -> dict:
    """Latest release metadata from static/version.json on GitHub main."""
    import requests
    from routes.api import GITHUB_RAW_URL
    r = requests.get(GITHUB_RAW_URL, timeout=10,
                     headers={"User-Agent": "YandexParser-Updater/1.0"})
    r.raise_for_status()
    return r.json()


def _releases_page() -> str:
    """Human-facing release page (banner link when self-update is unavailable)."""
    try:
        from routes.api import GITHUB_REPO
    except Exception:
        return ""
    return f"https://github.com/{GITHUB_REPO}/releases/latest"


def _versioned_asset_url(version: str, url: str) -> str:
    """`url` if it is pinned to v<version>, else "".

    Only `.../releases/download/v<version>/<asset>` is safe to hand to the
    updater: the `releases/latest/download/...` alias serves the previous
    published release while the new one is a draft (GitHub hides drafts),
    which is how a user could end up re-installing the version already on
    disk.
    """
    version = str(version or "").strip()
    url = str(url or "").strip()
    if not version or not url:
        return ""
    return url if f"/releases/download/v{version}/" in url else ""


def _release_asset_url(version: str, use_cache: bool = True) -> str:
    """browser_download_url of the zip asset of EXACTLY the v<version> release.

    `/releases/tags/v<version>` is used instead of `/releases/latest`: it
    answers 404 while the release is a draft or was deleted, and that is
    precisely the case we must not treat as an available update. Returns ""
    when the release is not published or has no zip asset.
    """
    version = str(version or "").strip()
    if not version:
        return ""
    cache = _state().get("asset") or {}
    if use_cache and cache.get("version") == version:
        if time.time() - float(cache.get("at") or 0) < ASSET_CACHE_TTL:
            return str(cache.get("url") or "")
    url = ""
    try:
        import requests
        from routes.api import GITHUB_REPO
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/v{version}",
            timeout=10,
            headers={"User-Agent": "YandexParser-Updater/1.0",
                     "Accept": "application/vnd.github+json"},
        )
        if r.status_code == 200:
            data = r.json() or {}
            if not data.get("draft"):
                for asset in data.get("assets", []):
                    if asset.get("name") == ZIP_ASSET_NAME:
                        url = asset.get("browser_download_url", "")
                        break
    except Exception:
        pass
    _save_state(asset={"version": version, "url": url, "at": time.time()})
    return url


def _download_target(latest: str, stamped_url: str = "") -> tuple:
    """(url, reason) — where the advertised version can really be downloaded.

    1. the URL stamped into version.json, when it is pinned to v<latest>
       (no network call needed — the normal case);
    2. otherwise the asset of the exact v<latest> release through the API;
    3. otherwise an empty url and a message explaining that the release is
       not published yet, so the caller can tell the truth instead of
       offering an update that would silently no-op.
    """
    version = str(latest or "").strip()
    if not version:
        return "", "Неизвестна версия обновления — повторите проверку позже."
    pinned = _versioned_asset_url(version, stamped_url)
    if pinned:
        return pinned, ""
    resolved = _release_asset_url(version)
    if resolved:
        return resolved, ""
    return "", (f"Релиз v{version} ещё не опубликован на GitHub. Обновление "
                 "появится здесь сразу после публикации релиза.")


@staticmethod
def _ver_tuple(v: str):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


@bp.route("/update/status")
def update_status():
    from config import APP_VERSION
    import sys
    out = {
        "frozen": _is_frozen(),
        "dev": _is_dev(),
        "current": APP_VERSION,
        "latest": None,
        "newer": False,
        "changelog": "",
        "download_url": "",
        # false → в баннере нет кнопки «Обновить сейчас» (macOS/исходники).
        "auto_apply": _is_frozen() and _self_update_supported(),
        "platform": sys.platform,
        "state": _state(),
    }
    # DEV-сборка: за версией не ходим — обновление ей не предлагается.
    if out["dev"] or not _is_frozen():
        return jsonify(out)
    try:
        meta = _remote_meta()
        out["latest"] = meta.get("version", "")
        out["changelog"] = meta.get("changelog", "")
        stamped = meta.get("download_url", "")
        out["download_url"] = _releases_page()
        out["newer"] = _ver_tuple(out["latest"] or "0") > _ver_tuple(APP_VERSION)
        if out["newer"]:
            url, why = _download_target(out["latest"], stamped)
            if url:
                out["download_url"] = url
            else:
                # Advertised but not installable (release still a draft, was
                # deleted, ...). Better to say "nothing to install" than to
                # walk the user through an update that silently no-ops.
                out["newer"] = False
                out["notice"] = why
        # Remember the advertised version for /update/apply: the bat is built
        # later, and the zip must be verified against the SAME advertised
        # version even if GitHub is unreachable by then.
        _save_state(latest=out["latest"], download_url=out["download_url"],
                    stamped_url=stamped)
    except Exception as exc:
        out["error"] = str(exc)
    return jsonify(out)


@bp.route("/update/changelog")
def update_changelog():
    """version.json from GitHub (version, changelog, history) for the
    «Что нового» modal. Falls back to the bundled copy when offline."""
    from config import APP_VERSION
    try:
        meta = _remote_meta()
    except Exception:
        # Offline: serve the bundled static/version.json so the modal
        # still opens and shows at least the current version's notes.
        try:
            import json as _json
            bundled = (paths.resource_dir() if paths else Path(__file__).resolve().parent.parent) / "static" / "version.json"
            meta = _json.loads(bundled.read_text(encoding="utf-8-sig"))
            meta["offline"] = True
        except Exception:
            meta = {"version": APP_VERSION, "changelog": ""}
    meta.setdefault("version", APP_VERSION)
    meta["current"] = APP_VERSION
    return jsonify(meta)


@bp.route("/update/download", methods=["POST"])
def update_download():
    """Stream the release zip to _update/update.zip."""
    if _is_dev():
        return jsonify(_dev_refusal()), 400
    if not _is_frozen():
        return jsonify({"ok": False, "error": "Доступно только в сборке .exe"}), 400
    if not _self_update_supported():
        return jsonify(_platform_refusal()), 400

    state = _state()
    explicit = (request.get_json(silent=True) or {}).get("url")
    url = explicit or ""
    if not url:
        # NEVER fall back to the stamped `releases/latest/download/...` alias:
        # while the release is a draft (or was deleted) it serves the PREVIOUS
        # release and the update becomes a silent no-op — the reported bug.
        # Only an URL pinned to v<advertised> is used, otherwise the exact tag
        # is resolved through the API.
        latest = str(state.get("latest") or "")
        stamped = str(state.get("stamped_url") or "")
        if not latest:
            try:
                meta = _remote_meta()
                latest = meta.get("version", "")
                stamped = meta.get("download_url", "")
            except Exception:
                pass
        url, why = _download_target(latest, stamped)
        if not url:
            return jsonify({"ok": False, "error": why or "Не найден адрес обновления"}), 400
    _save_state(download_url=url)

    import requests
    try:
        r = requests.get(url, stream=True, timeout=(10, 300),
                         headers={"User-Agent": "YandexParser-Updater/1.0"})
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        target = _work_dir() / "update.zip"
        done = 0
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
        if total and done != total:
            return jsonify({"ok": False,
                            "error": f"Архив скачан неполностью ({done} из {total} байт)"}), 502
        _save_state(download={"done": done, "total": total,
                              "file": str(target), "url": url})
        return jsonify({"ok": True, "bytes": done, "total": total, "file": str(target)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@bp.route("/update/apply", methods=["POST"])
def update_apply():
    """Extract the downloaded zip, verify it, schedule the swap, restart."""
    if _is_dev():
        return jsonify(_dev_refusal()), 400
    if not _is_frozen():
        return jsonify({"ok": False, "error": "Доступно только в сборке .exe"}), 400
    if not _self_update_supported():
        return jsonify(_platform_refusal()), 400

    st = _state()
    zip_path = Path(st.get("download", {}).get("file") or (_work_dir() / "update.zip"))
    if not zip_path.exists():
        return jsonify({"ok": False, "error": "Обновление ещё не скачано"}), 400

    work = _work_dir()
    extract = work / "extracted"
    if extract.exists():
        shutil.rmtree(extract, ignore_errors=True)
    extract.mkdir(parents=True)

    # 1. Extract
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Архив повреждён: {exc}"}), 400

    # 2. Locate the new app folder (zip may or may not have a top-level dir)
    src = extract
    if not (src / EXE_NAME).exists():
        inner = src / APP_DIR_NAME
        if (inner / EXE_NAME).exists():
            src = inner
        else:
            return jsonify({"ok": False, "error": "В архиве нет " + EXE_NAME}), 400
    if not (src / "_internal").exists():
        return jsonify({"ok": False, "error": "В архиве нет _internal — повреждённая сборка"}), 400

    # 3. Verify the version INSIDE the zip against the advertised one.
    #    While a release is still a draft, a `releases/latest/...` link
    #    downloaded the PREVIOUS release: without this check the updater
    #    would "successfully" install an old version (report: «остаётся
    #    прежняя версия»). A stale zip is deleted so the retry re-downloads.
    advertised = str(st.get("latest") or "").strip()
    zip_version = ""
    for cand in (src / "_internal" / "static" / "version.json",
                 src / "static" / "version.json"):
        if cand.exists():
            try:
                zip_version = str(_json_load(cand).get("version", "")).strip()
            except Exception:
                zip_version = ""
            break
    if advertised and zip_version and _ver_tuple(zip_version) < _ver_tuple(advertised):
        try:
            zip_path.unlink()
        except OSError:
            pass
        _save_state(error=f"В архиве v{zip_version}, ожидалась v{advertised}")
        return jsonify({
            "ok": False,
            "error": f"В архиве версия v{zip_version}, а ожидалась v{advertised}: "
                     "релиз ещё не опубликован. Скачайте новую версию вручную "
                     "со страницы релизов (кнопка GitHub ↗)."}), 409
    new_version = zip_version or advertised

    app_root = _app_root()

    # 4. Build the updater script: it runs AFTER this process exits.
    #    The old bat waited for the app PID via `tasklist | find` and slept
    #    with `timeout` — both break easily (a non-Windows find.exe on PATH,
    #    no console for timeout), so the swap could start while the exe was
    #    still locked: the move failed silently, the new _internal landed
    #    next to the OLD exe, and the old version relaunched. This bat waits
    #    for an explicit marker file instead, retries locked moves, verifies
    #    the result and rolls back if anything failed. Only app-owned files
    #    are moved — .env, logs/ and output/ stay where they are.
    backup = work / "_backup"
    bat = work / "updater.bat"
    marker = work / EXIT_MARKER

    def _mov_block(idx: int, name: str, is_dir: bool) -> list[str]:
        """Retry-loop that moves one app entry into the backup folder."""
        pre = [f'if exist "%BAK%\\{name}" rmdir /s /q "%BAK%\\{name}"'] if is_dir else []
        return [
            f'rem -- swap entry: {name} ({"dir" if is_dir else "file"})',
            "set /a TRY=0",
            f":mov_{idx}",
            f'if not exist "%APP%\\{name}" goto done_{idx}',
            *pre,
            f'move /y "%APP%\\{name}" "%BAK%\\{name}" >nul 2>>"%LOG%"',
            f'if not exist "%APP%\\{name}" goto done_{idx}',
            "set /a TRY+=1",
            "if %TRY% GEQ 10 goto rollback",
            "ping -n 2 127.0.0.1 >nul",
            f"goto mov_{idx}",
            f":done_{idx}",
            "",
        ]

    lines = [
        "@echo off",
        "setlocal EnableExtensions",
        "rem Auto-generated by YandexBusinessParser updater - do not edit",
        f'set "LOG={work / LOG_FILE}"',
        f'set "APP={app_root}"',
        f'set "SRC={src}"',
        f'set "BAK={backup}"',
        f'set "MARK={marker}"',
        f'set "WORK={work}"',
        'echo [%date% %time%] updater started >> "%LOG%"',
        "",
        "rem -- 1. Wait for the app.exit marker (the app writes it on exit)",
        "set /a N=0",
        ":waitmark",
        'if exist "%MARK%" goto waited',
        "ping -n 2 127.0.0.1 >nul",
        "set /a N+=1",
        "if %N% LSS 40 goto waitmark",
        'echo [%time%] no exit marker after ~40s, proceeding anyway >> "%LOG%"',
        ":waited",
        "ping -n 3 127.0.0.1 >nul",
        "",
        "rem -- 2. Back up ONLY the app files (user data is not touched)",
        'if not exist "%BAK%" mkdir "%BAK%"',
    ]
    for i, entry in enumerate(sorted(src.iterdir())):
        lines += _mov_block(i, entry.name, entry.is_dir())
    lines += [
        "rem -- 3. Copy the new files in",
        'xcopy "%SRC%\\*" "%APP%\\" /e /i /y >>"%LOG%" 2>&1',
        "if errorlevel 1 goto rollback",
        f'if not exist "%APP%\\{EXE_NAME}" goto rollback',
        'echo [%time%] swap done, starting the new version >> "%LOG%"',
        'cd /d "%APP%"',
        f'start "" "%APP%\\{EXE_NAME}"',
        'echo [%date% %time%] update completed >> "%LOG%"',
        'if exist "%SRC%" rmdir /s /q "%SRC%"',
        'if exist "%MARK%" del /q "%MARK%" >nul 2>&1',
        'if exist "%WORK%\\update.zip" del /q "%WORK%\\update.zip" >nul 2>&1',
        "exit /b 0",
        "",
        ":rollback",
        'echo [%time%] FAILED - restoring the previous version >> "%LOG%"',
    ]
    for i, entry in enumerate(sorted(src.iterdir())):
        name = entry.name
        lines += [
            f'if not exist "%APP%\\{name}" if exist "%BAK%\\{name}" '
            f'move /y "%BAK%\\{name}" "%APP%\\{name}" >nul 2>>"%LOG%"',
        ]
    lines += [
        'echo [%date% %time%] rollback finished, old version kept >> "%LOG%"',
        "exit /b 1",
    ]
    # newline="" keeps the explicit CR-LF line endings exactly as written.
    # v2.3.0 wrote the same script in text mode, so every line ended with
    # CR CR LF and cmd.exe aborted it before the first swap command: the app
    # restarted, nothing was replaced and the version stayed the same.
    with open(bat, "w", encoding="cp866", errors="replace", newline="") as fh:
        fh.write("\r\n".join(lines))
    raw = bat.read_bytes()
    if b"\r\r" in raw or not raw.startswith(b"@echo off\r\n"):
        return jsonify({"ok": False,
                        "error": "Скрипт установки записался с ошибкой — "
                                 "обновление отменено, приложение не тронуто."}), 500

    _save_state(applied=True, new_version=new_version,
                previous_version=st.get("current", ""), error="",
                bat=str(bat))

    # 5. Launch detached, signal exit, then stop the app so the .bat can
    #    take over. The marker makes the bat start its swap as soon as this
    #    process is gone; the retry loops cover the shutdown window.
    if marker.exists():
        try:
            marker.unlink()
        except OSError:
            pass
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(work), **_DETACHED)
    try:
        marker.write_text("exit", encoding="ascii")
    except OSError:
        pass

    # 6. Give the response a moment to flush, then hard-exit: the running
    #    exe locks itself, and the .bat can only swap files once this
    #    process is gone (the marker + the bat's retry loops cover the gap).
    def _bye():
        import time as _t
        _t.sleep(1.0)
        os._exit(0)

    import threading
    threading.Thread(target=_bye, daemon=True).start()
    return jsonify({"ok": True, "message": "Обновление установлено — приложение перезапускается…",
                    "new_version": new_version})
