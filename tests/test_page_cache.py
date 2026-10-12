# -*- coding: utf-8 -*-
"""Дисковый кэш карточек Яндекс.Карт: `yandex_maps_parser/cache.py`.

Кэш вернули в работу, потому что детальные карточки перекачивались при
каждом прогоне (секунды браузера на организацию). Здесь проверяем, что он
безопасен, а не только включён:

* попадание отдаёт ту же страницу и экономит вызов браузера;
* антибот-заглушка / пустой ответ / битый файл на диск не попадают —
  иначе заглушка пережила бы повторный прогон;
* TTL и лимит объёма реально действуют (папка не растёт бесконечно);
* запись атомарная (читатель не увидит половину страницы);
* `YP_PAGE_CACHE=0` выключает кэш целиком.
"""
import os
import time
from pathlib import Path

import pytest

from yandex_maps_parser import cache, extractors

ROOT = Path(__file__).resolve().parent.parent


PAGE = "<html><body>" + "организация " * 300 + "</body></html>"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Изолированный каталог кэша — тесты не трогают output/.cache."""
    d = tmp_path / "pages"
    monkeypatch.setattr(cache, "_CACHE_DIR", str(d))
    monkeypatch.delenv("YP_PAGE_CACHE", raising=False)
    cache.reset_stats()          # счётчики — модульный синглтон
    return d


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


# ── Базовое поведение ─────────────────────────────────────────

class TestStoreAndGet:
    def test_roundtrip(self, cache_dir):
        cache.set_cached("123", PAGE)
        assert cache.get_cached("123") == PAGE

    def test_miss_without_file(self, cache_dir):
        assert cache.get_cached("nope") is None

    def test_no_biz_id_is_a_noop(self, cache_dir):
        cache.set_cached("", PAGE)
        assert cache.get_cached("") is None
        assert not cache_dir.exists() or not list(cache_dir.glob("*.html"))

    def test_reset_stats_zeroes_the_counters(self, cache_dir):
        cache.set_cached("123", PAGE)
        cache.get_cached("123")
        cache.reset_stats()
        assert cache.cache_stats()["hits"] == 0

    def test_disabled_by_env(self, cache_dir, monkeypatch):
        cache.set_cached("123", PAGE)
        monkeypatch.setenv("YP_PAGE_CACHE", "0")
        assert cache.is_enabled() is False
        assert cache.get_cached("123") is None
        cache.set_cached("456", PAGE)          # выключено — на диск не пишем
        assert not (cache_dir / "456.html").exists()

    def test_short_page_is_not_stored(self, cache_dir):
        cache.set_cached("123", "<html>робот</html>")
        assert not (cache_dir / "123.html").exists()

    def test_truncated_file_counts_as_a_miss_and_is_removed(self, cache_dir):
        cache.set_cached("123", PAGE)
        (cache_dir / "123.html").write_text("огрызок", encoding="utf-8")
        assert cache.get_cached("123") is None
        assert not (cache_dir / "123.html").exists()

    def test_write_is_atomic_and_leaves_no_temp_files(self, cache_dir):
        cache.set_cached("123", PAGE)
        assert [p.name for p in cache_dir.glob("*.tmp")] == []
        assert (cache_dir / "123.html").read_text(encoding="utf-8") == PAGE

    def test_biz_id_is_sanitised_into_a_filename(self, cache_dir):
        cache.set_cached("../../etc/passwd", PAGE)
        assert cache.get_cached("../../etc/passwd") == PAGE
        # Ничего не вылезло за папку кэша.
        assert all(p.parent == cache_dir for p in cache_dir.glob("*.html"))


# ── TTL и лимит объёма ────────────────────────────────────────

class TestExpiryAndLimits:
    def test_expired_page_is_a_miss(self, cache_dir):
        cache.set_cached("123", PAGE)
        _age(cache_dir / "123.html", cache._TTL_SECONDS + 60)
        assert cache.get_cached("123") is None
        assert not (cache_dir / "123.html").exists()

    def test_cleanup_expired_removes_only_old_pages(self, cache_dir):
        cache.set_cached("old", PAGE)
        cache.set_cached("new", PAGE)
        _age(cache_dir / "old.html", cache._TTL_SECONDS + 60)
        assert cache.cleanup_expired() == 1
        assert (cache_dir / "new.html").exists()
        assert not (cache_dir / "old.html").exists()

    def test_size_limit_evicts_the_oldest_page(self, cache_dir, monkeypatch):
        # Лимит считается в байтах файла — влезает ровно одна страница.
        monkeypatch.setattr(cache, "_MAX_BYTES", len(PAGE.encode("utf-8")) + 10)
        cache.set_cached("first", PAGE)
        _age(cache_dir / "first.html", 3600)
        cache.set_cached("second", PAGE)
        # Влезает ровно одна страница — самая старая уходит.
        assert cache.get_cached("second") == PAGE
        assert not (cache_dir / "first.html").exists()

    def test_stats_report_size_and_counters(self, cache_dir):
        cache.set_cached("123", PAGE)
        cache.get_cached("123")
        cache.get_cached("missing")
        stats = cache.cache_stats()
        assert stats["enabled"] is True
        assert stats["total"] == 1 and stats["valid"] == 1
        assert stats["bytes"] == len(PAGE.encode("utf-8"))
        assert stats["max_bytes"] == cache._MAX_BYTES
        assert stats["hits"] == 1 and stats["misses"] >= 1


# ── Связка с загрузкой карточки ───────────────────────────────

class TestFetchHtmlUsesTheCache:
    @pytest.fixture
    def fake_cdp(self, monkeypatch):
        """Браузер-заглушка: считает вызовы и отдаёт заданную страницу."""
        calls = []
        page = {"html": PAGE}

        def fetch_page(url, timeout_ms=40000, biz_id=""):
            calls.append((url, biz_id))
            return page["html"]

        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "fetch_page", fetch_page)
        return calls, page

    def test_second_fetch_is_served_from_cache(self, cache_dir, fake_cdp):
        calls, _ = fake_cdp
        url = "https://yandex.ru/maps/org/123"
        assert extractors.fetch_html(url, biz_id="123") == PAGE
        assert extractors.fetch_html(url, biz_id="123") == PAGE
        assert len(calls) == 1, "повторная загрузка ждала бы браузер зря"

    def test_antiblock_stub_is_not_cached(self, cache_dir, fake_cdp):
        calls, page = fake_cdp
        page["html"] = "<html>Ой! Похоже, вы робот. showcaptcha</html>" + "x" * 1000
        url = "https://yandex.ru/maps/org/123"
        assert extractors.fetch_html(url, biz_id="123") == ""
        assert extractors.fetch_html(url, biz_id="123") == ""
        assert len(calls) == 2, "заглушка не должна жить в кэше сутки"
        assert not (cache_dir / "123.html").exists()

    def test_without_biz_id_nothing_is_cached(self, cache_dir, fake_cdp):
        calls, _ = fake_cdp
        url = "https://taplink.cc/salon"
        assert extractors.fetch_html(url) == PAGE
        assert extractors.fetch_html(url) == PAGE
        assert len(calls) == 2


class TestEnrichmentReusesTheCardPage:
    """Сквозная проверка через настоящий enrichment.enrich().

    Это тот путь, из-за которого кэш и отключали: детальная карточка грузится
    для каждой организации, и до подключения fetch_html повторный прогон
    открывал её в браузере заново.
    """

    PAGE_WITH_VK = (
        '<html><body><script type="application/json">'
        '{"url": "https://vk.com/testcafe", "rating": "4,7"}'
        '</script>' + '<div>' + ('страница карточки ' * 80) + '</div></body></html>'
    )

    @pytest.fixture
    def cdp(self, monkeypatch):
        """Браузер-заглушка: считает карточки, которые пришлось открывать."""
        import types
        from yandex_maps_parser import cdp_client, enrichment, state

        opened: list[str] = []
        monkeypatch.setattr(cdp_client, "is_available", lambda: True)
        monkeypatch.setattr(cdp_client, "fetch_page",
                            lambda url, timeout_ms=40000, biz_id="":
                            (opened.append(url), self.PAGE_WITH_VK)[1])
        monkeypatch.setattr(state, "FETCH_DETAIL", True, raising=False)
        monkeypatch.setattr(state, "USE_BROWSER", True, raising=False)
        monkeypatch.setattr(state, "PARSE_MODE", "all", raising=False)
        monkeypatch.setattr(state, "SOCIAL_MODE", "all", raising=False)
        monkeypatch.setattr(state, "REQUIRED_SOCIALS", set(), raising=False)
        monkeypatch.setattr(state, "MAX_WORKERS", 1, raising=False)
        import types as _t
        pbar = _t.SimpleNamespace(update=lambda *a, **k: None)
        return types.SimpleNamespace(enrich=enrichment.enrich, opened=opened, pbar=pbar)

    def _candidate(self):
        return {"name": "Тестовое кафе", "city": "Уфа", "query": "кафе",
                "_biz_id": "15064875244", "_raw_feature": {}}

    def test_second_run_takes_the_card_from_the_cache(self, cache_dir, cdp):
        first = cdp.enrich([self._candidate()], cdp.pbar)
        assert len(cdp.opened) == 1, "первый прогон открывает карточку"
        assert first[0]["vk"] == "https://vk.com/testcafe", "ссылка досталась со страницы"
        assert (cache_dir / "15064875244.html").exists(), "страница легла в кэш"

        second = cdp.enrich([self._candidate()], cdp.pbar)
        assert len(cdp.opened) == 1, "второй прогон не должен открывать браузер"
        assert second[0]["vk"] == first[0]["vk"]
        assert cache.cache_stats()["hits"] == 1

    def test_antiblock_page_is_not_reused_between_runs(self, cache_dir, cdp, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp_mod
        monkeypatch.setattr(cdp_mod, "fetch_page",
                            lambda url, timeout_ms=40000, biz_id="":
                            (cdp.opened.append(url),
                             "<html>Похоже, вы робот. showcaptcha</html>" + "x" * 1000)[1])
        cdp.enrich([self._candidate()], cdp.pbar)
        cdp.enrich([self._candidate()], cdp.pbar)
        assert len(cdp.opened) == 4, "две попытки на прогон, заглушка не кэшируется"
        assert not (cache_dir / "15064875244.html").exists()


class TestEnrichmentUsesTheCachedFetch:
    def test_detail_pages_go_through_fetch_html(self):
        text = (ROOT / "yandex_maps_parser" / "enrichment.py").read_text(
            encoding="utf-8")
        assert "fetch_html(detail_url, biz_id=biz_id)" in text
        assert "cdp_client.fetch_page(detail_url, biz_id=biz_id)" not in text, (
            "прямой вызов браузера в обход fetch_html отключает кэш страниц")
