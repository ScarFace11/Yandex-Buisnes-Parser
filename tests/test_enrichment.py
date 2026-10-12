"""
Tests for enrichment.py: government institution detection, collect_candidates.
Run with: python -m pytest tests/test_enrichment.py -v
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser.enrichment import _is_government_institution, _GOV_NAME_KEYWORDS


class TestIsGovernmentInstitution:
    """Test that government institution detection works correctly."""

    def test_poliklinika_in_name(self):
        assert _is_government_institution({"name": "Городская поликлиника №5"})

    def test_bolnitsa_in_name(self):
        assert _is_government_institution({"name": "Центральная больница"})

    def test_gospital_in_name(self):
        assert _is_government_institution({"name": "Военный госпиталь"})

    def test_municipalnoe_in_name(self):
        assert _is_government_institution({"name": "Муниципальное учреждение здравоохранения"})

    def test_gosudarstvennoe_in_name(self):
        assert _is_government_institution({"name": "Государственная стоматология"})

    def test_federalnoe_in_name(self):
        assert _is_government_institution({"name": "Федеральная клиника"})

    def test_stomatologicheskoe_otdelenie(self):
        assert _is_government_institution({"name": "Стоматологическое отделение №2"})

    def test_case_insensitive(self):
        """Detection should work regardless of case."""
        assert _is_government_institution({"name": "ПОЛИКЛИНИКА №10"})
        assert _is_government_institution({"name": "Больница"})

    def test_private_clinic_not_flagged(self):
        """Private clinics should NOT be flagged as government."""
        assert not _is_government_institution({"name": "Стоматология Смайл"})
        assert not _is_government_institution({"name": "Дентал Плюс"})
        assert not _is_government_institution({"name": "Приватная клиника"})

    def test_private_with_poliklinika_in_category(self):
        """Private clinic with 'поликлиника' in CATEGORY (not name) should NOT be flagged."""
        assert not _is_government_institution({
            "name": "Смайл",
            "category": "Стоматологическая поликлиника"
        })

    def test_empty_name(self):
        """Empty name should not crash."""
        assert not _is_government_institution({"name": ""})
        assert not _is_government_institution({})

    def test_name_without_keyword(self):
        """Names without government keywords should not be flagged."""
        assert not _is_government_institution({"name": "Клиника Доктора Иванова"})
        assert not _is_government_institution({"name": "МедЦентр Здоровье"})
        assert not _is_government_institution({"name": "Стоматологическая клиника Альфа"})

    def test_keyword_in_middle_of_name(self):
        """Keywords should match even in the middle of the name."""
        assert _is_government_institution({"name": "Отделение челюстно-лицевой хирургии больницы №3"})

    def test_all_keywords_exist(self):
        """Verify all expected keywords are defined."""
        expected_keywords = {
            "поликлиник", "больниц", "госпитал",
            "муниципальн", "государств", "федеральн",
            "стоматологическое отделение",
        }
        assert set(_GOV_NAME_KEYWORDS) == expected_keywords


class TestCrawlPrefilter:
    """Предфильтр сбора: запись, которую всё равно снимут фильтры (чёрный
    список, «только без сайтов», соцсети), не попадает НИ в живой поток
    (им наполняется таблица результатов), НИ в output/raw/.

    Раньше сбор складывал всё, а этап 2 снимал лишнее: пользователь видел в
    таблице записи, которые сам же и отключил, и они исчезали после сборки.
    Решение принимает processing.crawl_skip_reason — то же правило, что у
    этапа 2, поэтому «Применить фильтры заново» не находит расхождений.
    """

    @staticmethod
    def _pbar():
        return types.SimpleNamespace(update=lambda *a, **k: None)

    @staticmethod
    def _prepare(monkeypatch, **overrides):
        from yandex_maps_parser import state
        monkeypatch.setattr(state, "FETCH_DETAIL", False, raising=False)
        monkeypatch.setattr(state, "PARSE_MODE", "all", raising=False)
        monkeypatch.setattr(state, "MAX_WORKERS", 2, raising=False)
        monkeypatch.setattr(state, "SOCIAL_MODE", "all", raising=False)
        monkeypatch.setattr(state, "REQUIRED_SOCIALS", set(), raising=False)
        monkeypatch.setattr(state, "BLACKLIST_WORDS", [], raising=False)
        state.reset_crawl_skips()
        for key, val in overrides.items():
            monkeypatch.setattr(state, key, val, raising=False)
        return state

    def test_record_without_socials_is_dropped_in_with_socials_mode(self, monkeypatch):
        """«С соцсетями»: запись без соцсетей не показываем и не сохраняем."""
        from yandex_maps_parser import enrichment
        state = self._prepare(monkeypatch, SOCIAL_MODE="with_socials", REQUIRED_SOCIALS={"vk"})
        out = enrichment.enrich(
            [{"name": "Без соцсетей", "city": "Уфа", "query": "кафе"}], self._pbar())
        assert out == []
        assert state.crawl_skip_summary()["no_socials"] == 1

    def test_record_with_social_is_emitted_with_its_link(self, monkeypatch):
        from yandex_maps_parser import enrichment
        self._prepare(monkeypatch, SOCIAL_MODE="with_socials")
        out = enrichment.enrich(
            [{"name": "С ВК", "city": "Уфа", "query": "кафе",
              "_raw_feature": {"url": "https://vk.com/somecafe"}}], self._pbar())
        assert [r["name"] for r in out] == ["С ВК"]
        assert out[0]["vk"].startswith("https://vk.com")

    def test_required_socials_drop_record_without_them(self, monkeypatch):
        """Плитки — фильтр И: нет хотя бы одной выбранной сети — записи нет."""
        from yandex_maps_parser import enrichment
        state = self._prepare(monkeypatch, REQUIRED_SOCIALS={"vk", "telegram"})
        out = enrichment.enrich(
            [{"name": "Только ВК", "city": "Уфа", "query": "кафе",
              "_raw_feature": {"url": "https://vk.com/onlyvk"}}], self._pbar())
        assert out == []
        assert state.crawl_skip_summary()["missing_socials"] == 1

    def test_without_socials_mode_drops_records_that_have_them(self, monkeypatch):
        from yandex_maps_parser import enrichment
        state = self._prepare(monkeypatch, SOCIAL_MODE="without_socials")
        out = enrichment.enrich(
            [{"name": "С ВК", "city": "Уфа", "query": "кафе",
              "_raw_feature": {"url": "https://vk.com/somecafe"}}], self._pbar())
        assert out == []
        assert state.crawl_skip_summary()["has_socials"] == 1

    def test_blacklisted_record_never_loads_its_detail_page(self, monkeypatch):
        """Слово из чёрного списка известно уже из выдачи — карточку не грузим."""
        from yandex_maps_parser import enrichment, cdp_client, state
        self._prepare(monkeypatch, BLACKLIST_WORDS=["франшиза"], FETCH_DETAIL=True)
        monkeypatch.setattr(cdp_client, "is_available", lambda: True)
        fetched = []
        monkeypatch.setattr(enrichment, "fetch_html", lambda *a, **k: fetched.append(a) or "<html/>")
        out = enrichment.enrich(
            [{"name": "Кофейня Франшиза", "category": "Кофейня", "city": "Уфа",
              "query": "кафе", "_biz_id": "123"}], self._pbar())
        assert out == []
        assert fetched == [], "карточка чёрного списка не должна загружаться"
        assert state.crawl_skip_summary()["blacklist"] == 1

    def test_website_found_on_the_card_is_dropped(self, monkeypatch):
        """«Только без сайтов»: сайт выяснился на карточке — записи нет."""
        from yandex_maps_parser import enrichment, state
        self._prepare(monkeypatch, PARSE_MODE="without_website")
        out = enrichment.enrich(
            [{"name": "С сайтом", "city": "Уфа", "query": "кафе",
              "website": "https://cafe.ru"}], self._pbar())
        assert out == []
        assert state.crawl_skip_summary()["website"] == 1

    def test_aggregator_link_is_not_a_website(self, monkeypatch):
        """Ссылка-витрина (taplink/vk.cc) сайтом не считается — запись остаётся."""
        from yandex_maps_parser import enrichment
        self._prepare(monkeypatch, PARSE_MODE="without_website")
        out = enrichment.enrich(
            [{"name": "Витрина", "city": "Уфа", "query": "кафе",
              "aggregator_url": "https://vk.cc/abc"}], self._pbar())
        assert [r["name"] for r in out] == ["Витрина"]

    def test_counters_reset_between_runs(self, monkeypatch):
        from yandex_maps_parser import enrichment, state
        self._prepare(monkeypatch, SOCIAL_MODE="with_socials")
        enrichment.enrich([{"name": "Без соцсетей", "city": "Уфа", "query": "кафе"}], self._pbar())
        assert state.crawl_skip_summary()["total"] == 1
        state.reset_crawl_skips()
        assert state.crawl_skip_summary()["total"] == 0
