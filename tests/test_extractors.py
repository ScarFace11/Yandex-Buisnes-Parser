"""
Smoke tests for the parser's extraction pipeline.
Run with: python -m pytest tests/ -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser.extractors import (
    extract_socials,
    extract_phone,
    extract_rating_reviews,
    extract_website,
    extract_aggregator,
    extract_page,
    PageView,
    _extract_from_json_blob,
    _clean_social_url,
    _normalize_social_url,
    _is_aggregator,
    own_contacts_html,
)
from yandex_maps_parser.search import parse_feature


# ── extract_website (карточка организации) ────────────────────

class TestExtractWebsite:
    def test_contact_block_link_wins(self):
        html = '<a href="https://salon-example.ru/">Сайт</a>'
        assert extract_website(html) == "https://salon-example.ru"

    def test_social_link_is_not_a_website(self):
        html = '<a href="https://vk.com/salon">Сайт</a>'
        assert extract_website(html) == ""

    def test_aggregator_is_not_a_website(self):
        html = '<a href="https://taplink.cc/salon">Сайт</a>'
        assert extract_website(html) == ""

    def test_page_data_url_field(self):
        html = ('<script type="application/json">{"org":{"url":'
                '"https://salon-example.ru"}}</script>')
        assert extract_website(html) == "https://salon-example.ru"

    def test_empty_page_has_no_website(self):
        assert extract_website("<html><body>нет контактов</body></html>") == ""
        assert extract_website("") == ""


# ── Ссылка «Сайт» живёт глубже 200 КБ ────────────────────────────
# Реальная карточка ~900 КБ, секция «Контакты» начинается около 690 КБ
# (замер по 168 закэшированным страницам: ни на одной из них старый разбор
# по первым 200 КБ не нашёл сайт, хотя в HTML он был). Секцию contacts
# целиком читает и extract_phone — сайт теперь ищется так же.

def _deep_card(site_href: str, pad: int = 250_000) -> str:
    """Карточка, где кнопка «Сайт» глубже 200 КБ — как на реальных страницах.

    Реальный порядок: кнопка «Сайт» в шапке карточки идёт РАНЬШЕ секции
    «Контакты» (замер по закэшированным страницам: ссылка ~670 КБ, секция
    ~690 КБ).
    """
    return ("x" * pad
            + '<div class="action-button-view _type_action_button">'
            + f'<a href="{site_href}" role="button" rel="nofollow">Сайт</a></div>'
            + '<h3 class="card-section-header__title _wide">Контакты</h3>'
            + '<h3 class="card-section-header__title _wide">Время работы</h3>')


class TestSiteLinkBeyondPageHead:
    def test_own_site_is_found_deep_in_the_contacts_section(self):
        got = extract_website(_deep_card("https://salon-example.ru/"))
        assert got == "https://salon-example.ru"

    def test_aggregator_is_read_as_aggregator_not_as_website(self):
        html = _deep_card("https://taplink.cc/salon")
        assert extract_website(html) == "", "витрина сайтом не считается"
        assert extract_aggregator(html) == "https://taplink.cc/salon"

    def test_plain_site_leaves_the_aggregator_empty(self):
        assert extract_aggregator(_deep_card("https://salon-example.ru")) == ""

    def test_social_link_is_neither_site_nor_aggregator(self):
        html = _deep_card("https://vk.com/salon")
        assert extract_website(html) == ""
        assert extract_aggregator(html) == ""

    def test_aggregator_in_page_data(self):
        html = ('<script type="application/json">'
                '{"org":{"url":"https://taplink.cc/salon"}}</script>')
        assert extract_aggregator(html) == "https://taplink.cc/salon"

    def test_extract_page_carries_the_aggregator_field(self):
        page = extract_page(_deep_card("https://taplink.cc/salon"))
        assert page["aggregator"] == "https://taplink.cc/salon"
        assert page["website"] == ""

    def test_without_a_contacts_section_the_page_is_still_searched(self):
        # Прежнее поведение для фрагментов без секции — оно сохранено.
        html = '<a href="https://salon-example.ru/">Сайт</a>'
        assert extract_website(html) == "https://salon-example.ru"

    def test_yandex_erid_tag_is_stripped_from_the_site_url(self):
        # Метка партнёрской программы Яндекса на ссылке «Сайт» — мусор в отчёте.
        html = _deep_card("https://salon-example.ru/?erid=3MtFQRkqfB2huzBcH")
        assert extract_website(html) == "https://salon-example.ru"


# ── extract_socials ────────────────────────────────────────────

class TestExtractSocials:
    def test_vk_link(self):
        text = 'Мы в VK: https://vk.com/mybeauty'
        result = extract_socials(text)
        assert "vk" in result
        assert "vk.com/mybeauty" in result["vk"]

    def test_telegram_link(self):
        text = 'Telegram: https://t.me/beauty_salon'
        result = extract_socials(text)
        assert "telegram" in result
        assert "t.me/beauty_salon" in result["telegram"]

    def test_whatsapp_link(self):
        text = 'WhatsApp: https://wa.me/79001234567'
        result = extract_socials(text)
        assert "whatsapp" in result

    def test_instagram_link(self):
        text = 'Instagram: https://www.instagram.com/salon_beauty'
        result = extract_socials(text)
        assert "instagram" in result

    def test_no_socials(self):
        text = 'Обычный текст без ссылок'
        result = extract_socials(text)
        assert len(result) == 0

    def test_multiple_socials(self):
        text = '''
        VK: https://vk.com/salon
        Telegram: https://t.me/salon
        Instagram: https://instagram.com/salon
        '''
        result = extract_socials(text)
        assert len(result) >= 2

    def test_utm_params_stripped(self):
        text = 'https://vk.com/salon?utm_source=google&utm_medium=cpc'
        result = extract_socials(text)
        assert "utm_source" not in result.get("vk", "")

    def test_excludes_yandex_urls(self):
        text = 'https://yandex.ru/maps/org/123'
        result = extract_socials(text)
        assert len(result) == 0

    def test_non_profile_vk_ignored(self):
        text = 'https://vk.com/wall-123_456'
        result = extract_socials(text)
        # wall posts should be excluded
        assert "vk" not in result or "wall" not in result.get("vk", "")


# ── _extract_from_json_blob ───────────────────────────────────

class TestExtractFromJsonBlob:
    def test_extracts_from_nuxt_state(self):
        html = '''
        <script>window.__NUXT__={
            "socialLinks": {
                "vk": "https://vk.com/salon",
                "telegram": "https://t.me/salon"
            }
        }</script>
        '''
        result = _extract_from_json_blob(html)
        assert "vk" in result or "telegram" in result

    def test_empty_html(self):
        result = _extract_from_json_blob("<html><body>Nothing here</body></html>")
        assert len(result) == 0

    def test_extracts_from_application_json(self):
        html = '''
        <script type="application/json">
        {"links": {"instagram": "https://instagram.com/test"}}
        </script>
        '''
        result = _extract_from_json_blob(html)
        assert "instagram" in result


# ── extract_rating_reviews (Lead Score inputs) ────────────────

class TestExtractRatingReviews:
    def test_reads_the_business_card_blob(self):
        # Real pages embed the card in window.__INITIAL_STATE__ (the same blob
        # socials come from).
        html = ('<script>window.__INITIAL_STATE__={"business": '
                '{"rating": 4.7, "reviewsCount": 213}}</script>')
        assert extract_rating_reviews(html) == (4.7, 213)

    def test_handles_nested_value_count_shape(self):
        html = ('<script type="application/json">{"ratingData": '
                '{"ratingValue": 4.25, "reviewsCount": 18}}</script>')
        assert extract_rating_reviews(html) == (4.2, 18)

    def test_empty_page_returns_empty_strings(self):
        # Missing data must stay empty — a fake 0.0 would poison the score.
        assert extract_rating_reviews("<html><body>нет данных</body></html>") == ("", "")
        assert extract_rating_reviews("") == ("", "")

    def test_out_of_range_rating_is_rejected(self):
        html = ('<script type="application/json">'
                '{"rating": 250, "reviewsCount": 3}</script>')
        rating, reviews = extract_rating_reviews(html)
        assert rating == ""
        assert reviews == 3

    def test_times_ten_scale_is_normalised(self):
        # Some builds embed 4.7 as 47 — normalise it, don't throw the rating
        # away (the lead score needs «рейтинг ≥ 4.5»).
        html = ('<script type="application/json">'
                '{"ratingValue": 47, "reviewCount": 900}</script>')
        assert extract_rating_reviews(html) == (4.7, 900)

    def test_ld_json_block_is_read(self):
        html = ('<script type="application/ld+json">{"aggregateRating": '
                '{"ratingValue": 4.6, "reviewCount": 128}}</script>')
        assert extract_rating_reviews(html) == (4.6, 128)

    def test_unninified_state_with_spaces(self):
        # `window.__INITIAL_STATE__ = {` (space after «=») must match too.
        html = 'window.__INITIAL_STATE__ = {"org":{"rating":4.9,"reviewsCount":77}};'
        assert extract_rating_reviews(html) == (4.9, 77)


# ── extract_phone (карточка организации) ──────────────────────

class TestExtractPhone:
    def test_tel_link_wins(self):
        html = ('<div>8 800 555 35 35</div>'
                '<a href="tel:+7 (495) 123-45-67">позвонить</a>')
        assert extract_phone(html) == "+7 495 123-45-67"

    def test_eight_prefix_is_normalised(self):
        assert extract_phone('<a href="tel:84951234567">x</a>') == "+7 495 123-45-67"

    def test_text_fallback(self):
        assert extract_phone("Телефон: +7 495 123 45 67") == "+7 495 123-45-67"

    def test_junk_and_short_numbers_are_rejected(self):
        assert extract_phone('<a href="tel:12345">x</a>') == ""
        assert extract_phone("<html>нет телефона</html>") == ""
        assert extract_phone("") == ""

    def test_hotline_8800_is_rejected(self):
        # 8-800 lines are platform/franchise support — you cannot call the
        # owner on them.
        assert extract_phone('<a href="tel:88005553535">x</a>') == ""
        assert extract_phone(
            '<script type="application/json">{"phone":"8 800 555 35 35"}</script>'
        ) == ""

    def test_phone_from_embedded_page_data(self):
        # Карточка прячет номер за кнопкой «Показать телефон», но отдаёт его
        # в данных страницы — читаем оттуда, без лишнего клика.
        html = ('<script type="application/json">{"org":{"contacts":'
                '[{"type":"phone","phone":"+7 812 555-11-22"}]}}</script>')
        assert extract_phone(html) == "+7 812 555-11-22"

    def test_phone_from_nested_value_object(self):
        html = 'window.__INITIAL_STATE__={"a":{"phoneNumber":{"value":"89161112233"}}};'
        assert extract_phone(html) == "+7 916 111-22-33"

    def test_unrelated_numbers_in_state_are_not_phones(self):
        # Only phone-named keys count: a random number in the state is not one.
        html = ('<script type="application/json">'
                '{"views":89161112233,"rating":4.7}</script>')
        assert extract_phone(html) == ""


# ── _clean_social_url ─────────────────────────────────────────

class TestCleanSocialUrl:
    def test_removes_utm(self):
        url = "https://vk.com/salon?utm_source=google&utm_medium=cpc"
        cleaned = _clean_social_url(url)
        assert "utm_source" not in cleaned
        assert "utm_medium" not in cleaned

    def test_removes_trailing_slash(self):
        url = "https://t.me/salon/"
        cleaned = _clean_social_url(url)
        assert not cleaned.endswith("/")

    def test_preserves_valid_url(self):
        url = "https://vk.com/salon"
        cleaned = _clean_social_url(url)
        assert cleaned == url

    def test_ref_before_trackcode_leaves_no_dangling_query(self):
        """Живой случай 17.10.2026: в колонке ВК было `…/heroeskaluga&amp;trackcode=…`.

        Ссылка из карточки приходит HTML-экранированной; после снятия `?ref=…`
        оставался хвост `&amp;trackcode=…`, и адрес профиля превращался в мусор.
        """
        assert (_clean_social_url("https://vk.ru/club?ref=x&amp;trackcode=4433")
                == "https://vk.ru/club")

    def test_trackcode_removed(self):
        assert _clean_social_url("https://vk.ru/club?trackcode=4433") == "https://vk.ru/club"

    def test_real_query_is_kept(self):
        """Параметры, без которых ссылка не работает, остаются на месте."""
        url = "https://youtube.com/watch?v=abc&t=10"
        assert _clean_social_url(url) == url
        assert _clean_social_url("https://wa.me/79001234567?text=hi") == \
            "https://wa.me/79001234567?text=hi"


# ── _normalize_social_url ─────────────────────────────────────

class TestNormalizeSocialUrl:
    def test_vk_profile(self):
        url = "https://vk.com/salon"
        result = _normalize_social_url("vk", url)
        assert result is not None
        assert "vk.com/salon" in result

    def test_vk_wall_excluded(self):
        url = "https://vk.com/wall-123_456"
        result = _normalize_social_url("vk", url)
        assert result is None

    def test_instagram_post_excluded(self):
        url = "https://instagram.com/p/ABC123"
        result = _normalize_social_url("instagram", url)
        assert result is None

    def test_instagram_profile(self):
        url = "https://instagram.com/salon"
        result = _normalize_social_url("instagram", url)
        assert result is not None


# ── _is_aggregator ────────────────────────────────────────────

class TestIsAggregator:
    def test_taplink(self):
        assert _is_aggregator("https://taplink.cc/salon")

    def test_linktree(self):
        assert _is_aggregator("https://linktr.ee/salon")

    def test_vk_is_not_aggregator(self):
        assert not _is_aggregator("https://vk.com/salon")

    def test_normal_website(self):
        assert not _is_aggregator("https://salon-example.ru")


# ── parse_feature ─────────────────────────────────────────────

class TestParseFeature:
    def _make_feature(self, name="Тест", url="", biz_id="12345",
                      rating_score=4.5, rating_count=10,
                      categories=None, address="ул. Тестовая, 1"):
        """Helper to build a minimal GeoJSON feature."""
        meta = {
            "name": name,
            "url": url,
            "id": biz_id,
            "address": address,
            "Categories": [{"name": c} for c in (categories or ["Салон красоты"])],
            "rating": {
                "score": str(rating_score) if rating_score else "",
                "count": str(rating_count) if rating_count else "",
            },
            "Phones": [{"formatted": "+7 900 123 45 67"}],
            "Hours": {"text": "ежедневно 10:00-20:00"},
        }
        return {
            "properties": {"CompanyMetaData": meta},
            "geometry": {"coordinates": [37.6, 55.7]},
        }

    def test_basic_record(self):
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        feat = self._make_feature()
        rec = parse_feature(feat, "тест")
        assert rec is not None
        assert rec["name"] == "Тест"
        assert rec["phone"] == "+7 900 123 45 67"
        assert rec["lat"] == 55.7
        assert rec["lon"] == 37.6

    def test_website_not_filtered(self):
        """Parse mode «all» keeps businesses with websites."""
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        state.PARSE_MODE = "all"
        feat = self._make_feature(url="https://salon-example.ru")
        rec = parse_feature(feat, "тест")
        assert rec is not None
        assert rec["name"] == "Тест"

    def test_website_filtered_in_without_website_mode(self):
        """Parse mode «without_website» (default) drops businesses with a website.

        Выдача сайт не показывает, поэтому фильтр добивает его на карточке
        (enrichment → extract_website) — здесь проверяется API-путь фильтра.
        """
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        state.PARSE_MODE = "without_website"
        feat = self._make_feature(url="https://salon-example.ru")
        assert parse_feature(feat, "тест") is None

    def test_aggregator_kept(self):
        """Businesses with aggregator links (taplink) should be kept in both modes."""
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        for mode in ("without_website", "all"):
            state.PARSE_MODE = mode
            feat = self._make_feature(url="https://taplink.cc/salon")
            rec = parse_feature(feat, "тест")
            assert rec is not None
        assert rec["aggregator_url"] == "https://taplink.cc/salon"

    def test_empty_name_skipped(self):
        feat = self._make_feature(name="")
        rec = parse_feature(feat, "тест")
        assert rec is None


# ── Блок контактов: чужие контакты не подмешиваются ────────────────
# На карточке организации есть секция «Контакты» — контакты ИМЕННО её.
# Всё остальное (блок «похожие организации» = ключ `competitor` в state-JSON,
# подборки) принадлежит другим фирмам и раньше подмешивалось в запись.


def _card_page(pad: int = 0) -> str:
    """Синтетическая карточка: свои контакты в секции, чужие — в state-JSON."""
    own = (
        '<h3 class="card-section-header__title _wide">Контакты</h3>'
        '<div class="card-phones-view__phone">'
        '<span dir="ltr" itemprop="telephone">+7 (913) 714-24-24</span></div>'
        '<a href="https://vk.com/own_biz" itemprop="sameAs">VK</a>'
        '<a href="https://t.me/own_biz" itemprop="sameAs">TG</a>'
        '<h3 class="card-section-header__title _wide">Время работы</h3>'
    )
    foreign = (
        '<script type="application/json" class="state-view">'
        '{"socialLinks":[{"type":"telegram","href":"https://t.me/own_biz"}],'
        '"phones":[{"number":"+7 913 714-24-24"}],'
        '"competitor":{'
        '"socialLinks":[{"type":"vk","href":"https://vk.com/competitor"},'
        '{"type":"whatsapp","href":"https://wa.me/79137995033"}],'
        '"phones":[{"number":"+7 913 799-50-33"}],'
        '"rating":4.8}}'
        '</script>'
    )
    return "x" * pad + own + foreign


class TestOwnContactsSection:
    def test_section_is_cut_out_of_the_page(self):
        sec = own_contacts_html(_card_page())
        assert sec.startswith('<h3 class="card-section-header__title')
        assert "itemprop=\"telephone\"" in sec and "own_biz" in sec
        assert "Время работы" not in sec        # секция кончается следующим разделом
        assert "competitor" not in sec          # state-JSON за пределами секции

    def test_plain_text_has_no_section(self):
        # Фрагмент/JSON выдачи/чужой сайт разбираются как раньше, без среза.
        assert own_contacts_html("обычный текст") == ""
        assert own_contacts_html("") == ""
        assert own_contacts_html("<h3>Контакты</h3>") == ""

    def test_socials_come_from_the_contacts_block_only(self):
        soc = extract_socials(_card_page())
        assert soc["vk"] == "https://vk.com/own_biz"
        assert soc["telegram"] == "https://t.me/own_biz"
        assert "whatsapp" not in soc, "wa.me из блока «похожие организации» — чужой"

    def test_phone_is_read_from_the_contacts_block(self):
        # Номер живёт глубже 200 КБ — прежнее усечение страницы его не
        # находило вовсе, теперь разбор идёт по секции «Контакты».
        assert extract_phone(_card_page(pad=250_000)) == "+7 913 714-24-24"

    def test_competitor_phone_is_never_taken(self):
        # Без секции (старая страница / другой формат) JSON всё равно
        # чистится от чужих веток.
        page = ('<script type="application/json">'
                '{"competitor":{"phones":[{"number":"+7 913 799-50-33"}]}}'
                '</script>')
        assert extract_phone(page) == ""

    def test_json_blob_ignores_the_similar_organisations_block(self):
        soc = _extract_from_json_blob(_card_page())
        # Внутри state-JSON свои ссылки есть (telegram), чужих нет.
        assert "telegram" in soc
        assert "vk" not in soc
        assert "whatsapp" not in soc

    def test_rating_is_not_taken_from_a_neighbour_card(self):
        page = ('<script type="application/json">'
                '{"relatedPlaces":[{"rating":4.9}],'
                '"competitor":{"rating":4.8}}'
                '</script>')
        assert extract_rating_reviews(page) == ("", "")


# ── extract_page: всё со страницы за один разбор ─────────────

def _by_parts(html: str) -> dict:
    """То же самое пятью отдельными вызовами — как было до extract_page."""
    socials = dict(_extract_from_json_blob(html))
    for k, v in extract_socials(html).items():
        socials.setdefault(k, v)
    rating, reviews = extract_rating_reviews(html)
    return {"socials": socials, "rating": rating, "reviews": reviews,
            "phone": extract_phone(html), "website": extract_website(html)}


class TestExtractPage:
    """Один разбор страницы вместо пяти — с тем же результатом.

    Повторный разбор встроенных данных был чистой тратой: на карточках из
    кэша сборщика пять проходов занимали 15.7 мс, один — 7 мс. Поэтому
    главное здесь — не скорость сама по себе, а то, что результат не
    поменялся, а страница действительно разбирается один раз.
    """

    @pytest.mark.parametrize("pad", (0, 250_000))
    def test_same_result_as_separate_calls(self, pad):
        html = _card_page(pad=pad)
        page = extract_page(html)
        parts = _by_parts(html)
        assert page["phone"] == parts["phone"]
        assert page["website"] == parts["website"]
        assert (page["rating"], page["reviews"]) == (parts["rating"], parts["reviews"])
        merged = dict(page["socials_json"])
        for k, v in page["socials_contacts"].items():
            merged.setdefault(k, v)
        assert merged == parts["socials"]

    def test_socials_come_back_in_two_blocks_with_priority_left_to_caller(self):
        """Соцсети из выдачи важнее встроенных, встроенные — важнее контактов."""
        page = extract_page(_card_page())
        assert page["socials_json"].get("telegram") == "https://t.me/own_biz"
        assert page["socials_contacts"].get("vk") == "https://vk.com/own_biz"
        assert "competitor" not in str(page["socials_json"])

    def test_page_is_parsed_once(self, monkeypatch):
        """Встроенные данные разбираются один раз на страницу, а не на шаг."""
        from yandex_maps_parser import extractors as ex

        calls = []
        real = ex._blobs_in

        def counting(text):
            calls.append(len(text))
            return real(text)

        monkeypatch.setattr(ex, "_blobs_in", counting)
        page = ex.extract_page(_card_page())
        assert page["phone"]
        assert len(calls) == 1, f"данные страницы разобраны {len(calls)} раз"

    def test_unneeded_steps_are_not_run_at_all(self, monkeypatch):
        """Шаг не нужен (значение есть из выдачи) — он и не считается."""
        from yandex_maps_parser import extractors as ex

        calls = {"phone": 0, "website": 0, "rating": 0}
        monkeypatch.setattr(ex, "extract_phone",
                            lambda html, view=None: calls.update(phone=calls["phone"] + 1))
        monkeypatch.setattr(ex, "extract_website",
                            lambda html, view=None: calls.update(website=calls["website"] + 1))
        monkeypatch.setattr(ex, "extract_rating_reviews",
                            lambda html, view=None: (calls.update(rating=calls["rating"] + 1),
                                                     ("", ""))[1])
        page = ex.extract_page(_card_page(), rating=False, phone=False, website=False)
        assert calls == {"phone": 0, "website": 0, "rating": 0}
        assert page["phone"] == "" and page["website"] == ""
        assert page["rating"] == "" and page["reviews"] == ""
        assert page["socials_contacts"], "соцсети отключены не были — они нужны всегда"

    def test_empty_page_gives_empty_values_not_errors(self):
        page = extract_page("")
        assert page == {"socials_json": {}, "socials_contacts": {},
                        "rating": "", "reviews": "", "phone": "", "website": "",
                        "aggregator": ""}

    def test_one_view_serves_every_step(self):
        """PageView помнит разбор: второй вызов отдаёт тот же результат без работы."""
        view = PageView(_card_page())
        first = view.blobs()
        assert view.blobs() is first, "данные страницы разбираются повторно"
        assert view.contacts() is view.contacts()
