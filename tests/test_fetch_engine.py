"""
Tests for the user-selectable detail-fetch engine («Способ парсинга»).

fetch_engine: auto | cdp | playwright | httpx.
- auto keeps the historical ladder: CDP → Playwright, HTTP only on anti-bot.
- cdp / playwright must use ONLY the chosen engine (no cross-substitution);
  when it is unavailable the record degrades to the throttled HTTP fetch.
- httpx never touches a browser.
Runner side: _apply_params validates the value and disables browser pools
for httpx.

Run with: python -m pytest tests/test_fetch_engine.py -v
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# >800 bytes so a healthy page passes _looks_like_antiblock.
_GOOD_PAGE = "<html>" + "x" * 1000 + "</html>"
_STUB_PAGE = "<html>ok</html>"  # <800 bytes → anti-bot stub


class _FakeClient:
    """Stand-in for cdp_client / browser_client with call recording."""

    def __init__(self, available=True, page=_GOOD_PAGE):
        self._available = available
        self.calls = []
        self.page = page

    def is_available(self):
        return self._available

    def fetch_page(self, url, biz_id="", timeout_ms=30000):
        self.calls.append(url)
        return self.page


def _prepare_state(monkeypatch, engine):
    from yandex_maps_parser import state
    monkeypatch.setattr(state, "FETCH_DETAIL", True, raising=False)
    monkeypatch.setattr(state, "PARSE_MODE", "all", raising=False)
    monkeypatch.setattr(state, "MAX_WORKERS", 2, raising=False)
    monkeypatch.setattr(state, "SOCIAL_MODE", "all", raising=False)
    monkeypatch.setattr(state, "REQUIRED_SOCIALS", set(), raising=False)
    monkeypatch.setattr(state, "USE_BROWSER", True, raising=False)
    monkeypatch.setattr(state, "SOURCE", "yandex", raising=False)
    monkeypatch.setattr(state, "FETCH_ENGINE", engine, raising=False)
    return state


def _run_enrich(monkeypatch, engine, *, cdp=None, playwright=None, html_fetch=None):
    """Run enrich() with one candidate and fake fetch modules.

    Returns (results, cdp_client, playwright_client, http_client) where the
    last three are the fakes with their .calls lists.
    """
    from yandex_maps_parser import enrichment
    _prepare_state(monkeypatch, engine)
    cdp = cdp if cdp is not None else _FakeClient(available=False)
    pw = playwright if playwright is not None else _FakeClient(available=False)
    http = html_fetch if html_fetch is not None else _FakeClient(available=True)
    monkeypatch.setattr(enrichment, "cdp_client", cdp, raising=False)
    monkeypatch.setattr(enrichment, "browser_client", pw, raising=False)
    monkeypatch.setattr(enrichment, "fetch_html",
                        lambda url, biz_id="", session=None: http.fetch_page(url, biz_id=biz_id),
                        raising=False)
    pbar = types.SimpleNamespace(update=lambda *a, **k: None)
    out = enrichment.enrich(
        [{"name": "Кафе Тест", "city": "Уфа", "query": "кафе", "_biz_id": "biz1"}],
        pbar)
    return out, cdp, pw, http


class TestFetchEngineSelection:
    """enrichment.fetch_detail must honour the user-chosen engine."""

    def test_auto_prefers_cdp(self, monkeypatch):
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "auto", cdp=_FakeClient(available=True))
        assert len(cdp.calls) == 1
        assert pw.calls == []
        assert http.calls == []

    def test_auto_falls_back_to_playwright(self, monkeypatch):
        # auto + CDP unavailable → Playwright answers (historical ladder).
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "auto", playwright=_FakeClient(available=True))
        assert cdp.calls == []
        assert len(pw.calls) == 1
        assert http.calls == []

    def test_cdp_choice_never_uses_playwright(self, monkeypatch):
        # Explicit cdp: even with Playwright up, CDP is the only browser used.
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "cdp", cdp=_FakeClient(available=True),
            playwright=_FakeClient(available=True))
        assert len(cdp.calls) == 1
        assert pw.calls == []
        assert http.calls == []

    def test_playwright_choice_never_uses_cdp(self, monkeypatch):
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "playwright", cdp=_FakeClient(available=True),
            playwright=_FakeClient(available=True))
        assert cdp.calls == []
        assert len(pw.calls) == 1
        assert http.calls == []

    def test_cdp_unavailable_degrades_to_http(self, monkeypatch):
        # Chosen engine missing → the card is still fetched via throttled
        # HTTP instead of being lost.
        out, cdp, pw, http = _run_enrich(monkeypatch, "cdp")
        assert cdp.calls == []
        assert pw.calls == []
        assert len(http.calls) == 1
        assert [r["name"] for r in out] == ["Кафе Тест"]

    def test_playwright_unavailable_degrades_to_http(self, monkeypatch):
        out, cdp, pw, http = _run_enrich(monkeypatch, "playwright")
        assert pw.calls == []
        assert len(http.calls) == 1
        assert [r["name"] for r in out] == ["Кафе Тест"]

    def test_httpx_never_touches_browser(self, monkeypatch):
        # _apply_params sets USE_BROWSER=False for httpx; mirror that here.
        from yandex_maps_parser import state
        state = _prepare_state(monkeypatch, "httpx")
        monkeypatch.setattr(state, "USE_BROWSER", False, raising=False)
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "httpx", cdp=_FakeClient(available=True),
            playwright=_FakeClient(available=True))
        assert cdp.calls == []
        assert pw.calls == []
        assert len(http.calls) == 1

    def test_antibot_stub_retries_via_cdp_then_http(self, monkeypatch):
        # auto + CDP serves a stub → one fresh-tab CDP retry → throttled HTTP.
        stub = _FakeClient(available=True, page=_STUB_PAGE)
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "auto", cdp=stub, html_fetch=_FakeClient(available=True))
        assert len(stub.calls) == 2
        assert len(http.calls) == 1
        assert [r["name"] for r in out] == ["Кафе Тест"]

    def test_antibot_stub_with_playwright_goes_straight_to_http(self, monkeypatch):
        # playwright choice: no CDP cross-retry on a stub — HTTP immediately.
        stub = _FakeClient(available=True, page=_STUB_PAGE)
        out, cdp, pw, http = _run_enrich(
            monkeypatch, "playwright", playwright=stub,
            cdp=_FakeClient(available=True))
        assert len(stub.calls) == 1
        assert cdp.calls == []
        assert len(http.calls) == 1


class TestApplyParamsValidation:
    """runner._apply_params validates fetch_engine and gates browser pools."""

    @staticmethod
    def _apply(monkeypatch, params):
        from yandex_maps_parser import runner, state
        monkeypatch.setattr(state, "YANDEX_API_KEY", "", raising=False)
        runner._apply_params(params)
        return state

    def test_valid_engines_pass_through(self, monkeypatch):
        for engine in ("auto", "cdp", "playwright", "httpx"):
            st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"],
                                           "fetch_engine": engine})
            assert st.FETCH_ENGINE == engine

    def test_invalid_engine_falls_back_to_auto(self, monkeypatch):
        for junk in ("selenium", "", None, ["cdp"]):
            st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"],
                                           "fetch_engine": junk})
            assert st.FETCH_ENGINE == "auto"

    def test_missing_engine_defaults_to_auto(self, monkeypatch):
        st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"]})
        assert st.FETCH_ENGINE == "auto"

    def test_httpx_disables_browser(self, monkeypatch):
        st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"],
                                       "fetch_engine": "httpx"})
        assert st.USE_BROWSER is False

    def test_browser_engines_keep_use_browser(self, monkeypatch):
        for engine in ("auto", "cdp", "playwright"):
            st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"],
                                           "fetch_engine": engine})
            assert st.USE_BROWSER is True

    def test_use_browser_false_wins_over_engine(self, monkeypatch):
        st = self._apply(monkeypatch, {"queries": ["кафе"], "cities": ["Уфа"],
                                       "fetch_engine": "cdp", "use_browser": False})
        assert st.USE_BROWSER is False
