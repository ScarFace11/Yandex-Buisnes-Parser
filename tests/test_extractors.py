"""
Smoke tests for the parser's extraction pipeline.
Run with: python -m pytest tests/ -v
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser.extractors import (
    extract_socials,
    _extract_from_json_blob,
    _clean_social_url,
    _normalize_social_url,
    _is_aggregator,
)
from yandex_maps_parser.search import parse_feature


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

    def test_skip_with_website(self):
        """Businesses with real websites should be skipped."""
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        feat = self._make_feature(url="https://salon-example.ru")
        rec = parse_feature(feat, "тест")
        assert rec is None

    def test_aggregator_kept(self):
        """Businesses with aggregator links (taplink) should be kept."""
        import yandex_maps_parser.state as state
        state.SOCIAL_MODE = "all"
        feat = self._make_feature(url="https://taplink.cc/salon")
        rec = parse_feature(feat, "тест")
        assert rec is not None
        assert rec["aggregator_url"] == "https://taplink.cc/salon"

    def test_empty_name_skipped(self):
        feat = self._make_feature(name="")
        rec = parse_feature(feat, "тест")
        assert rec is None

    def test_min_rating_filter(self):
        import yandex_maps_parser.state as state
        state.MIN_RATING = 4.0
        feat = self._make_feature(rating_score=3.5)
        rec = parse_feature(feat, "тест")
        assert rec is None
        state.MIN_RATING = 0.0  # reset

    def test_min_reviews_filter(self):
        import yandex_maps_parser.state as state
        state.MIN_REVIEWS = 50
        feat = self._make_feature(rating_count=10)
        rec = parse_feature(feat, "тест")
        assert rec is None
        state.MIN_REVIEWS = 0  # reset
