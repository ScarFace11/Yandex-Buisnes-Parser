"""In-app self-update for the frozen Windows build.

Flow (all triggered from the web UI):
  GET  /update/status   — frozen? current vs latest version? update available?
  GET  /update/download — stream the release zip to a temp file
  POST /update/apply    — extract, verify, swap via updater.bat, restart the app

Swap strategy (a running .exe cannot overwrite itself on Windows):
  1. Extract the downloaded zip to <user_dir>/_update/
  2. Verify YandexBusinessParser.exe and _internal/ exist inside
  3. Write _update/updater.bat which:
       waits for the current process to exit,
       backs up the current files to _backup/,
       moves the new files into place,
       starts the new exe, deletes itself
  4. Respond ok, then spawn the .bat detached and stop Flask

From source (not frozen) the endpoints report frozen=False and the UI
hides the self-update button — update via git pull instead.
"""
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, Response

try:
    import paths
except Exception:
    paths = None

bp = Blueprint("update", __name__)

APP_DIR_NAME = "YandexBusinessParser"     # top-level folder inside the release zip
EXE_NAME = "YandexBusinessParser.exe"
STATE_FILE = "_update_state.json"         # progress for /update/status polling

# popen kwargs that work the same on all supported Python versions
_DETACHED = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0), "close_fds": True}


def _is_frozen() -> bool:
    return bool(paths and paths.is_frozen())


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


@staticmethod
def _ver_tuple(v: str):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


@bp.route("/update/status")
def update_status():
    from config import APP_VERSION
    out = {
        "frozen": _is_frozen(),
        "current": APP_VERSION,
        "latest": None,
        "newer": False,
        "changelog": "",
        "download_url": "",
        "state": _state(),
    }
    if not _is_frozen():
        return jsonify(out)
    try:
        meta = _remote_meta()
        out["latest"] = meta.get("version", "")
        out["changelog"] = meta.get("changelog", "")
        out["download_url"] = meta.get("download_url", "")
        out["newer"] = _ver_tuple(out["latest"] or "0") > _ver_tuple(APP_VERSION)
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
    if not _is_frozen():
        return jsonify({"ok": False, "error": "Доступно только в сборке .exe"}), 400

    meta = _state()
    url = (request.get_json(silent=True) or {}).get("url") or meta.get("download_url")
    if not url:
        try:
            url = _remote_meta().get("download_url", "")
        except Exception:
            url = ""
    if not url:
        return jsonify({"ok": False, "error": "Не найден адрес обновления"}), 400

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
        _save_state(download={"done": done, "total": total,
                              "file": str(target), "url": url})
        return jsonify({"ok": True, "bytes": done, "total": total, "file": str(target)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@bp.route("/update/apply", methods=["POST"])
def update_apply():
    """Extract the downloaded zip, verify it, schedule the swap, restart."""
    if not _is_frozen():
        return jsonify({"ok": False, "error": "Доступно только в сборке .exe"}), 400

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

    app_root = _app_root()
    new_version = _state().get("latest") or ""
    try:
        vf = src / "static" / "version.json"
        if vf.exists():
            import json as _json
            new_version = _json.loads(vf.read_text(encoding="utf-8")).get("version", new_version)
    except Exception:
        pass

    # 3. Build the updater script: it runs AFTER this process exits.
    #    a running exe cannot replace itself, so a .bat waits for PID,
    #    backs up, swaps, restarts, deletes itself.
    pid = os.getpid()
    backup = work / "_backup"
    bat = work / "updater.bat"
    bat.write_text("\r\n".join([
        "@echo off",
        "rem Auto-generated by YandexBusinessParser updater — do not edit",
        f":waitloop",
        f"tasklist /FI \"PID eq {pid}\" | find /I \"{pid}\" >nul && (timeout /t 1 /nobreak >nul & goto waitloop)",
        f"if exist \"{backup}\" rmdir /s /q \"{backup}\"",
        # everything currently in the app folder except the _update workdir
        f"mkdir \"{backup}\"",
        f"for /f %%i in ('dir /b \"{app_root}\" ^| findstr /v /i \"_update\"') do move \"{app_root}\\%%i\" \"{backup}\\\" >nul 2>&1",
        f"xcopy \"{src}\\*\" \"{app_root}\\\" /e /i /y >nul",
        f"start \"\" \"{app_root}\\{EXE_NAME}\"",
        f"rmdir /s /q \"{work}\"",
        "exit",
    ]), encoding="cp866", errors="replace")

    _save_state(applied=True, new_version=new_version,
                previous_version=st.get("current", ""))

    # 4. Launch detached, then stop the app so the .bat can take over.
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(work), **_DETACHED)

    def _bye():
        import time as _t
        _t.sleep(1.0)
        os._exit(0)

    import threading
    threading.Thread(target=_bye, daemon=True).start()
    return jsonify({"ok": True, "message": "Обновление установлено — приложение перезапускается…",
                    "new_version": new_version})
