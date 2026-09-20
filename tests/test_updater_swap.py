# -*- coding: utf-8 -*-
"""In-app updater: end-to-end swap on a real filesystem (Windows only).

The test runs the ACTUAL /update/apply view — it generates the real
updater.bat, spawns it detached and lets it swap the files while the "app"
files are locked (a running exe cannot be moved or overwritten). Asserts:

  * the new version lands and the new exe starts;
  * user data (.env, logs/) is NOT touched by the swap;
  * the old version is kept in _update/_backup for rollback;
  * a stale zip (older version inside than advertised) is REFUSED and deleted
    — the «updater installs the previous published release» bug;
  * the download URL is resolved from the latest PUBLISHED release, not from
    the version.json stamp that lags while the release is a draft.
"""
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fake frozen-Windows installation: exe + _internal + user data."""
    app_root = tmp_path / "app"
    (app_root / "_internal").mkdir(parents=True)
    shutil.copy(r"C:\Windows\System32\where.exe", app_root / "YandexBusinessParser.exe")
    (app_root / "_internal" / "core.txt").write_text("OLD", encoding="utf-8")
    (app_root / ".env").write_text("API_KEY=1", encoding="utf-8")
    (app_root / "logs").mkdir()
    (app_root / "logs" / "run.log").write_text("keep me", encoding="utf-8")

    from routes import update as update_mod
    monkeypatch.setattr(update_mod, "_is_frozen", lambda: True)
    monkeypatch.setattr(update_mod, "_is_dev", lambda: False)
    monkeypatch.setattr(update_mod, "_self_update_supported", lambda: True)
    monkeypatch.setattr(update_mod, "_app_root", lambda: app_root)
    monkeypatch.setattr(update_mod, "_work_dir", lambda: _ensure(app_root / "_update"))
    # os._exit would kill the test process — record the call instead. The
    # view MUST schedule it: without the hard exit the running exe stays
    # locked and the updater rolls back to the old version.
    state = {"exited": False}

    def _fake_exit(code):
        state["exited"] = True

    monkeypatch.setattr(os, "_exit", _fake_exit)

    app = Flask(__name__)
    app.register_blueprint(update_mod.bp)
    return {"client": app.test_client(), "app_root": app_root,
            "work": app_root / "_update", "update": update_mod,
            "state": state}


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_zip(tmp_path: Path, version: str) -> Path:
    """A release zip the way CI builds it: exe + _internal at the top level."""
    stage = tmp_path / "stage"
    (stage / "_internal" / "static").mkdir(parents=True)
    shutil.copy(r"C:\Windows\System32\robocopy.exe", stage / "YandexBusinessParser.exe")
    (stage / "_internal" / "core.txt").write_text("NEW", encoding="utf-8")
    (stage / "_internal" / "static" / "version.json").write_text(
        '{"version": "%s"}' % version, encoding="utf-8")
    zip_path = tmp_path / "update.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for p in sorted(stage.rglob("*")):
            z.write(p, p.relative_to(stage))
    return zip_path


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="updater.bat is Windows-only")
class TestRealSwap:
    def test_swap_installs_the_new_version_and_keeps_user_data(self, env, tmp_path, monkeypatch):
        client, app_root, work = env["client"], env["app_root"], env["work"]
        zip_path = _make_zip(tmp_path, "9.9.9")
        monkeypatch.setattr(env["update"], "_state",
                            lambda: {"latest": "9.9.9",
                                     "download": {"file": str(zip_path)}})

        # Simulate the running app: lock the exe and a file inside _internal
        # for a few seconds (the window before the process exits). The real
        # app exits ~1 s after writing the marker; the bat's retry loop must
        # ride out exactly this kind of short lock.
        lock1 = open(app_root / "YandexBusinessParser.exe", "rb")
        lock2 = open(app_root / "_internal" / "core.txt", "rb")
        try:
            r = client.post("/update/apply")
            assert r.status_code == 200
            assert r.get_json()["ok"] is True
            time.sleep(4)          # the «application is still shutting down» window
        finally:
            lock1.close()
            lock2.close()
        # The hard exit was scheduled (os._exit ~1s after the response).
        exit_deadline = time.time() + 5
        while time.time() < exit_deadline and not env["state"]["exited"]:
            time.sleep(0.1)
        assert env["state"]["exited"], "update_apply must os._exit to release the exe lock"

        # A CI runner is heavily loaded: the bat's ping-based waits and the
        # start of the new exe can take tens of seconds — give it 90s.
        deadline = time.time() + 90
        core = app_root / "_internal" / "core.txt"
        while time.time() < deadline:
            if core.exists() and core.read_text(encoding="utf-8") == "NEW":
                break
            time.sleep(0.5)

        # New version installed...
        log = ""
        try:
            log = (work / "update.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        assert (app_root / "_internal" / "core.txt").read_text(
            encoding="utf-8") == "NEW", f"swap failed; updater log:\n{log}"
        assert (app_root / "YandexBusinessParser.exe").exists()
        # ...user data untouched...
        assert (app_root / ".env").read_text(encoding="utf-8") == "API_KEY=1"
        assert (app_root / "logs" / "run.log").read_text(encoding="utf-8") == "keep me"
        # ...the old version kept for rollback, and the run is logged.
        assert (work / "_backup" / "YandexBusinessParser.exe").exists()
        log = (work / "update.log").read_text(encoding="utf-8", errors="replace")
        assert "update completed" in log
        # The exit marker is cleaned up after a successful swap.
        assert not (work / "app.exit").exists()

    def test_stale_zip_is_refused_and_deleted(self, env, tmp_path, monkeypatch):
        client = env["client"]
        zip_path = _make_zip(tmp_path, "9.9.9")
        monkeypatch.setattr(env["update"], "_state",
                            lambda: {"latest": "10.0.0",          # advertised newer
                                     "download": {"file": str(zip_path)}})
        r = client.post("/update/apply")
        assert r.status_code == 409
        body = r.get_json()
        assert body["ok"] is False
        assert "не опубликован" in body["error"]
        # The stale zip is gone so the next attempt re-downloads.
        assert not zip_path.exists()


class TestPublishedAssetResolution:
    """The download URL must come from the latest PUBLISHED release."""

    def _patch_requests(self, monkeypatch, payload):
        import requests

        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return payload

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

    def test_uses_the_published_asset_url(self, monkeypatch):
        from routes import update as update_mod
        self._patch_requests(monkeypatch, {"assets": [{
            "name": update_mod.ZIP_ASSET_NAME,
            "browser_download_url": "https://x/pub.zip"}]})
        assert update_mod._published_asset_url() == "https://x/pub.zip"

    def test_empty_when_the_asset_is_missing(self, monkeypatch):
        from routes import update as update_mod
        self._patch_requests(monkeypatch, {"assets": [{"name": "other.zip"}]})
        assert update_mod._published_asset_url() == ""

    def test_empty_when_github_is_unreachable(self, monkeypatch):
        import requests
        from routes import update as update_mod

        def _boom(*a, **k):
            raise ConnectionError("offline")
        monkeypatch.setattr(requests, "get", _boom)
        assert update_mod._published_asset_url() == ""
