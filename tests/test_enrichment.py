"""
Tests for enrichment.py: government institution detection, collect_candidates.
Run with: python -m pytest tests/test_enrichment.py -v
"""
import sys
import os

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
