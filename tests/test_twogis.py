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

    def test_unknown_social_ignored(self):
        groups = [{"contacts": [{"type": "social_network", "url": "https://example.org/profile"}]}]
        s = _socials_from_contacts(groups)
        assert s == {}  # only VK/TG/IG/WA are tracked; other networks are dropped

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
        twogis._contacts_available = True  # key returns contacts by default in tests

    def teardown_method(self):
        twogis._contacts_available = None

    def test_basic_record(self):
        rec = parse_item(_item(), "Бар")
        assert rec is not None
        assert rec["name"] == "Бар «Пивная миля»"
        assert rec["address"] == "улица Свободы, 32"
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

    def test_no_name_rejected(self):
        assert parse_item(_item(name=""), "Бар") is None

    # ── rating / reviews (Lead Score inputs) ──

    def test_rating_and_reviews_come_from_the_api_payload(self):
        rec = parse_item(_item(), "Бар")
        assert rec["rating"] == 4.5
        assert rec["reviews_count"] == 87

    def test_missing_rating_stays_empty(self):
        # No value must never become a fake 0.0 — the score treats empty
        # as «unknown», a zero would read as «rated terribly».
        item = _item()
        item.pop("rating")
        item.pop("reviews")   # the fixture's reviews key
        rec = parse_item(item, "Бар")
        assert rec["rating"] == ""
        assert rec["reviews_count"] == ""

    def test_zero_reviews_is_kept_as_zero(self):
        item = _item(reviews={"count": 0}, rating={"value": 5.0})
        rec = parse_item(item, "Бар")
        assert rec["reviews_count"] == 0
        assert rec["rating"] == 5.0

    def test_malformed_rating_objects_do_not_crash(self):
        item = _item(rating="4.5", reviews=[{"count": 1}])
        rec = parse_item(item, "Бар")
        assert rec is not None
        assert rec["rating"] == ""
        assert rec["reviews_count"] == ""

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

    def test_name_and_category_from_name_ex(self):
        # Regression: the export used to show the brand twice
        # (name="Шашлыкоff, гриль-бар", category="Шашлыкоff") — the category
        # must be the business TYPE, never the brand.
        item = _item(
            name="Шашлыкоff, гриль-бар",
            name_ex={"primary": "Шашлыкоff", "extension": "гриль-бар"},
        )
        rec = parse_item(item, "кафе")
        assert rec["name"] == "Шашлыкоff"
        assert rec["category"] == "гриль-бар"

    def test_name_strips_trailing_extension_without_name_ex(self):
        rec = parse_item(_item(name="Zavarka coffee, кофейня"), "кафе")
        assert rec["name"] == "Zavarka coffee"
        assert rec["category"] == "кофейня"

    def test_category_falls_back_to_primary_rubric(self):
        item = _item(
            name="Пивная миля",
            rubrics=[
                {"kind": "additional", "name": "Кафе"},
                {"kind": "primary", "name": "Бары"},
            ],
        )
        rec = parse_item(item, "бар")
        assert rec["name"] == "Пивная миля"
        assert rec["category"] == "Бары"

    def test_display_name_tail_wins_over_rubric(self):
        item = _item(name="Бар, бар", rubrics=[{"kind": "primary", "name": "Бары"}])
        rec = parse_item(item, "бар")
        assert rec["name"] == "Бар"
        assert rec["category"] == "бар"

    def test_socials_from_outbound_wrapper_unwrapped(self):
        # 2GIS hands out link.2gis.ru redirects — the column must contain the
        # real profile, not a dead 2GIS link.
        groups = [{"contacts": [
            {"type": "social_network",
             "url": "http://link.2gis.ru/1.2/44C9D33B/online/project4/1/null/tok?https://vk.com/lakomkacafe"},
            {"type": "social_network",
             "url": "http://link.2gis.ru/1.2/C642693E/online/project4/1/null/tok?https://t.me/mo_na_co22"},
        ]}]
        s = _socials_from_contacts(groups)
        assert s["vk"] == "https://vk.com/lakomkacafe"
        assert s["telegram"] == "https://t.me/mo_na_co22"
        assert "link.2gis.ru" not in s["vk"]

    def test_wrapper_without_target_is_dropped(self):
        groups = [{"contacts": [
            {"type": "social_network",
             "url": "http://link.2gis.ru/1.2/44C9D33B/online/project4/1/null/tok"},
        ]}]
        assert _socials_from_contacts(groups) == {}

    def test_website_contact_unwrapped(self):
        groups = [{"contacts": [
            {"type": "website",
             "url": "http://link.2gis.ru/1.2/A/online/project4/1/null/tok?https://cafe.ru/menu"},
        ]}]
        assert _website_from_contacts(groups) == "https://cafe.ru/menu"
