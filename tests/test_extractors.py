"""
Smoke tests for the parser's extraction pipeline.
Run with: python -m pytest tests/ -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser.extractors import (
    extract_socials,
    extract_phone,
    extract_rating_reviews,
    _extract_from_json_blob,
    _clean_social_url,
    _normalize_social_url,
    _is_aggregator,
    unwrap_outbound,
)
from yandex_maps_parser.search import parse_feature


# ── unwrap_outbound (2GIS outbound link wrappers) ──────────────

class TestUnwrapOutbound:
    WRAPPER = ("http://link.2gis.ru/1.2/44C9D33B/online/20260901/project4/"
               "70000001038637938/null/tomig32986304dCI391881J3IH2H72lw54F004ded")

    def test_unwraps_target(self):
        assert unwrap_outbound(self.WRAPPER + "?https://vk.com/lakomkacafe") == \
            "https://vk.com/lakomkacafe"

    def test_unwraps_url_encoded_target(self):
        assert unwrap_outbound(self.WRAPPER + "?https%3A%2F%2Ft.me%2Fmybar") == \
            "https://t.me/mybar"

    def test_wrapper_without_target_dropped(self):
        assert unwrap_outbound(self.WRAPPER) == ""

    def test_ordinary_url_untouched(self):
        assert unwrap_outbound("https://vk.com/foo") == "https://vk.com/foo"
        assert unwrap_outbound("") == ""

    def test_extract_socials_unwraps_2gis_redirect(self):
        html = f'<a href="{self.WRAPPER}?http://vk.com/zavarka_cafe">VK</a>'
        result = extract_socials(html)
        # …and http:// profiles are upgraded to https:// for the export.
        assert result["vk"] == "https://vk.com/zavarka_cafe"
        assert "link.2gis.ru" not in result["vk"]

    def test_extract_socials_ignores_dead_wrapper(self):
        html = f'<a href="{self.WRAPPER}">соцсеть</a>'
        assert extract_socials(html) == {}


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


# ── extract_phone (2GIS/Yandex card fallback) ─────────────────

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
        # 2GIS hides the number behind «Показать телефон» but ships it in the
        # page data — read it from there.
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
        """Parse mode «without_website» (default) drops businesses with a website."""
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
