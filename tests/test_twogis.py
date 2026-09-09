"""
Unit tests for the 2GIS provider (offline — no network calls).

Run with: python -m pytest tests/test_twogis.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import state
from yandex_maps_parser import twogis
from yandex_maps_parser.twogis import (
    _socials_from_contacts,
    _phones_from_contacts,
    _website_from_contacts,
    parse_item,
)


# ── contact_groups parsing ────────────────────────────────────

class TestSocialsFromContacts:
    def test_vk_and_telegram(self):
        groups = [{"contacts": [
            {"type": "social_network", "url": "https://vk.com/club1"},
            {"type": "social_network", "url": "https://t.me/somebar"},
        ]}]
        s = _socials_from_contacts(groups)
        assert "vk" in s and "vk.com/club1" in s["vk"]
        assert "telegram" in s and "t.me/somebar" in s["telegram"]

    def test_messenger_type_whatsapp(self):
        groups = [{"contacts": [{"type": "messenger", "url": "https://wa.me/79001234567"}]}]
        s = _socials_from_contacts(groups)
        assert "whatsapp" in s

    def test_unknown_social_goes_to_other(self):
        groups = [{"contacts": [{"type": "social_network", "url": "https://example.org/profile"}]}]
        s = _socials_from_contacts(groups)
        assert "other_socials_list" in s

    def test_website_type_is_not_social(self):
        groups = [{"contacts": [{"type": "website", "url": "https://cafe.ru"}]}]
        s = _socials_from_contacts(groups)
        assert s == {}

    def test_empty_and_malformed(self):
        assert _socials_from_contacts([]) == {}
        assert _socials_from_contacts(None) == {}
        assert _socials_from_contacts([{"contacts": [{"type": "phone"}]}]) == {}


class TestPhonesAndWebsite:
    def test_phones_deduped(self):
        groups = [{"contacts": [
            {"type": "phone", "text": "+7 900 111-22-33"},
            {"type": "phone", "text": "+7 900 111-22-33"},
            {"type": "phone", "text": "+7 900 444-55-66"},
        ]}]
        assert _phones_from_contacts(groups) == ["+7 900 111-22-33", "+7 900 444-55-66"]

    def test_website_found(self):
        groups = [{"contacts": [
            {"type": "phone", "text": "+7 900 000-00-00"},
            {"type": "website", "url": "https://cafe.ru"},
        ]}]
        assert _website_from_contacts(groups) == "https://cafe.ru"


# ── parse_item ────────────────────────────────────────────────

def _item(**over):
    base = {
        "id": "70000001029535674",
        "name": "Бар «Пивная миля»",
        "address_name": "улица Свободы, 32",
        "point": {"lat": 56.32, "lon": 41.01},
        "rating": {"value": 4.5},
        "reviews": {"count": 87},
        "hours": {"display_text": "Ежедневно 12:00-02:00"},
        "contact_groups": [{"contacts": [
            {"type": "phone", "text": "+7 4852 30-00-00"},
            {"type": "social_network", "url": "https://vk.com/pivmilya"},
        ]}],
    }
    base.update(over)
    return base


class TestParseItem:
    def setup_method(self):
        state.PARSE_MODE = "all"
        state.MIN_RATING = 0.0
        state.MIN_REVIEWS = 0
        twogis._contacts_available = True  # key returns contacts by default in tests

    def teardown_method(self):
        twogis._contacts_available = None

    def test_basic_record(self):
        rec = parse_item(_item(), "Бар")
        assert rec is not None
        assert rec["name"] == "Бар «Пивная миля»"
        assert rec["address"] == "улица Свободы, 32"
        assert rec["rating"] == "4.5"
        assert rec["reviews"] == 87
        assert rec["hours"] == "Ежедневно 12:00-02:00"
        assert "+7 4852 30-00-00" in rec["phone"]
        assert rec["twogis_url"] == "https://2gis.ru/firm/70000001029535674"
        assert rec["yandex_maps_url"] == ""
        assert rec["_skip_detail"] is True  # contacts came with the API
        assert rec["_detail_url"] == "https://2gis.ru/firm/70000001029535674"

    def test_key_without_contacts_needs_fallback(self):
        # Demo keys strip contact_groups — the firm page must be fetched
        # during enrichment to find socials.
        twogis._contacts_available = False
        rec = parse_item(_item(), "Бар")
        assert rec is not None
        assert rec["_skip_detail"] is False
        assert rec["_detail_url"] == "https://2gis.ru/firm/70000001029535674"

    def test_reviews_shape_org_review_count(self):
        # Real API shape: {"org_review_count_with_stars": N, ...}
        item = _item(reviews={"org_review_count_with_stars": 12, "is_reviewable": True})
        rec = parse_item(item, "Бар")
        assert rec["reviews"] == 12

    def test_reviews_plain_number(self):
        rec = parse_item(_item(reviews=5), "Бар")
        assert rec["reviews"] == 5

    def test_no_name_rejected(self):
        assert parse_item(_item(name=""), "Бар") is None

    def test_parse_mode_without_website_keeps_no_site(self):
        state.PARSE_MODE = "without_website"
        rec = parse_item(_item(), "Бар")
        assert rec is not None  # no website in contact_groups

    def test_parse_mode_without_website_skips_website(self):
        state.PARSE_MODE = "without_website"
        item = _item(contact_groups=[{"contacts": [{"type": "website", "url": "https://cafe.ru"}]}])
        assert parse_item(item, "Бар") is None

    def test_parse_mode_all_keeps_website(self):
        state.PARSE_MODE = "all"
        item = _item(contact_groups=[{"contacts": [{"type": "website", "url": "https://cafe.ru"}]}])
        rec = parse_item(item, "Бар")
        assert rec is not None
        assert rec["website"] == "https://cafe.ru"

    def test_aggregator_counts_as_no_website(self):
        state.PARSE_MODE = "without_website"
        item = _item(contact_groups=[{"contacts": [{"type": "website", "url": "https://taplink.cc/bar"}]}])
        rec = parse_item(item, "Бар")
        assert rec is not None
        assert rec["aggregator_url"] == "https://taplink.cc/bar"
        assert rec["website"] == ""

    def test_rating_filter(self):
        state.MIN_RATING = 4.0
        item = _item(rating={"value": 3.5})
        assert parse_item(item, "Бар") is None

    def test_reviews_filter(self):
        state.MIN_REVIEWS = 100
        item = _item(reviews={"count": 87})
        assert parse_item(item, "Бар") is None

    def test_category_from_name_ex(self):
        item = _item(name_ex={"primary": "Бар"})
        rec = parse_item(item, "Бар")
        assert rec["category"] == "Бар"
