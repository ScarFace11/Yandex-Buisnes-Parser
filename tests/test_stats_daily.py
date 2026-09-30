"""«Динамика по дням» — дашборд вкладки «Статистика».

Дашборд отвечает на вопрос «сколько найдено и просмотрено за каждый день»,
поэтому проверяем ровно источники и агрегацию:

* «найдено» — строки файлов результатов, разложенные по дате из имени;
* raw и processed нельзя складывать (в processed те же записи после фильтров);
* processed/json и processed/excel — два экспорта одних записей;
* «просмотрено» — по дате отметки в `_reviewed.json`, легаси-`true` без даты
  в график не попадает;
* окно из N дней заполнено нулями и не тянет файлы со стороны.
"""
from datetime import date, datetime, time, timedelta

import pytest
from flask import Flask

from yandex_maps_parser.exporters import save_excel


# ── Fixtures ──────────────────────────────────────────────────

def _rec(name):
    return {"name": name, "city": "Уфа", "query": "кафе",
            "yandex_maps_url": "https://ya.ru/" + name, "address": "ул. 1"}


def _day(offset: int) -> str:
    """Дата окна: 0 — сегодня, 1 — вчера."""
    return (date.today() - timedelta(days=offset)).isoformat()


def _ts(offset: int, hour: int = 12) -> float:
    """Момент отметки внутри дня, отстоящего на offset дней от сегодня."""
    d = datetime.combine(date.today() - timedelta(days=offset), time(hour, 0))
    return d.timestamp()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask client, направленный в временное дерево output/."""
    from routes import api as api_mod

    root = tmp_path / "output"
    raw = root / "raw"
    proc = root / "processed"
    arch = root / "_archive"
    for d in (raw, proc / "excel", proc / "json", arch):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(api_mod, "OUTPUT_DIR", str(root))
    monkeypatch.setattr(api_mod, "RESULTS_DIR", str(root))
    monkeypatch.setattr(api_mod, "REVIEWED_FILE", str(root / "_reviewed.json"))
    monkeypatch.setattr(api_mod, "_raw_dir", lambda: str(raw))
    monkeypatch.setattr(api_mod, "_processed_dir", lambda: str(proc))
    monkeypatch.setattr(api_mod, "_archive_root", lambda: str(arch))
    api_mod._REC_CACHE.clear()

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    c = app.test_client()
    c.dirs = {"root": root, "raw": raw, "proc": proc, "arch": arch}
    return c


def _raw_file(client, day: str, n: int, name: str = "кафе") -> str:
    """raw-файл за день: имя несёт дату, тело — n записей."""
    path = client.dirs["raw"] / f"raw_{day}_10-00_{name}_{n}.xlsx"
    save_excel([_rec(f"r{i}") for i in range(n)], str(path))
    return str(path)


def _proc_file(client, sub: str, name: str, n: int, day: str | None = None) -> str:
    """processed-файл: даты в имени нет, день берётся из mtime (или задаётся)."""
    import os
    path = client.dirs["proc"] / sub / f"{name}_filtered.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_excel([_rec(f"p{i}") for i in range(n)], str(path))
    if day:
        stamp = datetime.combine(date.fromisoformat(day), time(12, 0)).timestamp()
        os.utime(path, (stamp, stamp))
    return str(path)


def _write_marks(client, marks: dict):
    import json
    with open(client.dirs["root"] / "_reviewed.json", "w", encoding="utf-8") as fh:
        json.dump(marks, fh, ensure_ascii=False)


def _series(client, days=7):
    res = client.get(f"/stats/daily?days={days}").get_json()
    return res, {d["date"]: d for d in res["series"]}


# ── Форма ответа ──────────────────────────────────────────────

class TestShape:
    def test_window_is_ascending_and_ends_today(self, client):
        res, _ = _series(client, 7)
        assert res["days"] == 7
        assert res["end"] == date.today().isoformat()
        assert res["start"] == _day(6)
        assert [d["date"] for d in res["series"]] == [_day(6 - i) for i in range(7)]
        assert all(d["found"] == 0 and d["reviewed"] == 0 for d in res["series"])

    def test_empty_days_are_present_with_zeroes(self, client):
        _raw_file(client, _day(3), 5)
        res, by_day = _series(client, 7)
        assert by_day[_day(3)]["found"] == 5
        assert by_day[_day(2)] == {"date": _day(2), "found": 0, "files": 0, "reviewed": 0}

    @pytest.mark.parametrize("days,expected", [
        (7, 7), (14, 14), (30, 30),
        (1000, 90),          # верхняя граница
        (0, 7), (-5, 7),     # мусор — дефолт, а не один день
    ])
    def test_days_are_clamped(self, client, days, expected):
        assert _series(client, days)[0]["days"] == expected

    def test_series_reports_totals(self, client):
        _raw_file(client, _day(1), 4)
        res, _ = _series(client, 7)
        assert res["totals"]["found"] == 4


# ── «Найдено»: файлы ──────────────────────────────────────────

class TestFound:
    def test_counts_rows_by_file_name_date(self, client):
        _raw_file(client, _day(2), 3)
        _raw_file(client, _day(2), 4, name="бар")
        _raw_file(client, _day(0), 2, name="кафе")
        _, by_day = _series(client, 7)
        assert by_day[_day(2)]["found"] == 7
        assert by_day[_day(2)]["files"] == 2
        assert by_day[_day(0)]["found"] == 2
        assert by_day[_day(0)]["files"] == 1

    def test_raw_and_processed_are_not_summed(self, client):
        """processed — это те же записи после фильтров: сумма дала бы 2×."""
        _raw_file(client, _day(1), 10)
        _proc_file(client, "excel", "кафе", 6, day=_day(1))
        _proc_file(client, "json", "кафе", 6, day=_day(1))
        _, by_day = _series(client, 7)
        assert by_day[_day(1)]["found"] == 10, "за день отвечают raw-файлы"

    def test_processed_is_used_when_raw_is_gone(self, client):
        """raw за день убран (архив/ручная чистка) — считаем по processed."""
        _proc_file(client, "excel", "кафе", 8, day=_day(2))
        _, by_day = _series(client, 7)
        assert by_day[_day(2)]["found"] == 8
        assert by_day[_day(2)]["files"] == 1

    def test_processed_subfolders_are_not_summed(self, client):
        """json и excel — два экспорта одних записей: берётся больший."""
        _proc_file(client, "excel", "кафе", 9, day=_day(2))
        _proc_file(client, "json", "кафе", 4, day=_day(2))
        _, by_day = _series(client, 7)
        assert by_day[_day(2)]["found"] == 9

    def test_file_without_date_in_name_uses_mtime(self, client):
        """Имя без даты (например обработанная выгрузка) датируется mtime."""
        _proc_file(client, "excel", "без_даты", 3, day=_day(4))
        _, by_day = _series(client, 7)
        assert by_day[_day(4)]["found"] == 3

    def test_files_outside_the_window_are_ignored(self, client):
        _raw_file(client, _day(30), 100)
        _, by_day = _series(client, 7)
        assert sum(d["found"] for d in by_day.values()) == 0

    def test_archived_files_still_count(self, client):
        """Файл уехал в _archive/<дата> — день не должен обнулиться."""
        import shutil
        src = _raw_file(client, _day(2), 5)
        dest_dir = client.dirs["arch"] / "2026-01-01"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(src, str(dest_dir))
        _, by_day = _series(client, 7)
        assert by_day[_day(2)]["found"] == 5

    def test_internal_and_lock_files_are_not_counted(self, client):
        import json as _json
        (client.dirs["raw"] / f"_{_day(1)}.json").write_text(
            _json.dumps([_rec("x")] * 50), encoding="utf-8")
        (client.dirs["raw"] / f"~$raw_{_day(1)}_10-00.xlsx").write_text("junk", encoding="utf-8")
        _, by_day = _series(client, 7)
        assert by_day[_day(1)]["found"] == 0

    def test_unreadable_file_does_not_break_the_series(self, client):
        (client.dirs["raw"] / f"raw_{_day(1)}_10-00_битый.xlsx").write_text("не xlsx", encoding="utf-8")
        _raw_file(client, _day(1), 2, name="целый")
        _, by_day = _series(client, 7)
        assert by_day[_day(1)]["found"] == 2


# ── «Просмотрено»: отметки ────────────────────────────────────

class TestReviewed:
    def test_counts_marks_by_their_own_day(self, client):
        _write_marks(client, {
            "url1": {"reviewed_at": _ts(1)},
            "url2": {"reviewed_at": _ts(1, hour=20)},
            "url3": {"reviewed_at": _ts(3)},
        })
        _, by_day = _series(client, 7)
        assert by_day[_day(1)]["reviewed"] == 2
        assert by_day[_day(3)]["reviewed"] == 1
        assert by_day[_day(2)]["reviewed"] == 0

    def test_legacy_true_mark_has_no_day(self, client):
        """Даты отметки у старых записей нет — выдумывать её нельзя."""
        _write_marks(client, {"old": True, "new": {"reviewed_at": _ts(2)}})
        res, by_day = _series(client, 7)
        assert by_day[_day(2)]["reviewed"] == 1
        assert res["totals"]["reviewed"] == 1

    def test_updated_at_is_accepted_as_a_fallback(self, client):
        _write_marks(client, {"a": {"updated_at": _ts(2)}, "b": {"at": _ts(3)}})
        _, by_day = _series(client, 7)
        assert by_day[_day(2)]["reviewed"] == 1
        assert by_day[_day(3)]["reviewed"] == 1

    def test_marks_outside_the_window_are_ignored(self, client):
        _write_marks(client, {"a": {"reviewed_at": _ts(40)}})
        res, _ = _series(client, 7)
        assert res["totals"]["reviewed"] == 0

    def test_broken_timestamps_do_not_break_the_series(self, client):
        _write_marks(client, {"a": {"reviewed_at": "не число"},
                              "b": {"reviewed_at": 0},
                              "c": {"reviewed_at": _ts(1)}})
        _, by_day = _series(client, 7)
        assert by_day[_day(1)]["reviewed"] == 1

    def test_single_mark_route_records_the_date(self, client):
        client.post("/reviewed", json={"url": "https://ya.ru/1", "reviewed": True})
        saved = client.get("/reviewed").get_json()["https://ya.ru/1"]
        assert saved["reviewed_at"] > 0

    def test_unmark_removes_entry(self, client):
        client.post("/reviewed", json={"url": "https://ya.ru/1", "reviewed": True})
        client.post("/reviewed", json={"url": "https://ya.ru/1", "reviewed": False})
        assert client.get("/reviewed").get_json() == {}

    def test_undated_marks_are_counted_but_not_plotted(self, client):
        """Отметки старого формата (`true`) даты не несут: в график они не
        попадают, но их число уходит в ответ — иначе интерфейсу нечем
        объяснить «просмотрено 0» при куче отмеченных строк."""
        _write_marks(client, {"a": True, "b": True, "c": {"reviewed_at": _ts(1)}})
        res, _ = _series(client, 7)
        assert res["totals"]["reviewed"] == 1
        assert res["totals"]["undated"] == 2

    def test_marked_rows_without_a_date_are_reported(self, client):
        _write_marks(client, {"a": {"reviewed_at": "не число"}, "b": {"reviewed_at": 0}})
        res, _ = _series(client, 7)
        assert res["totals"]["undated"] == 2


# ── Свой период: месяц и диапазон ───────────────────────────────

class TestPeriod:
    def _get(self, client, query):
        return client.get("/stats/daily?" + query).get_json()

    def test_month_is_the_whole_calendar_month(self, client):
        first = date.today().replace(day=1)
        res = self._get(client, "month=" + first.strftime("%Y-%m"))
        assert res["mode"] == "month"
        assert res["start"] == first.isoformat()
        assert res["end"] == date.today().isoformat(), "будущих дней в окне нет"
        assert len(res["series"]) == (date.today() - first).days + 1

    def test_month_widens_the_window_beyond_the_quick_segments(self, client):
        first = date.today().replace(day=1)
        if date.today().day <= 7:
            pytest.skip("первый день месяца ещё попадает в окно 7 дней")
        _raw_file(client, first.isoformat(), 3)
        assert self._get(client, "month=" + first.strftime("%Y-%m"))["totals"]["found"] == 3
        assert self._get(client, "days=7")["totals"]["found"] == 0

    @pytest.mark.parametrize("month", ["мусор", "2026-99", "2026", ""])
    def test_broken_month_falls_back_to_the_quick_period(self, client, month):
        res = self._get(client, "month=" + month)
        assert res["mode"] == "days" and res["days"] == 7

    def test_explicit_range_is_taken_as_is(self, client):
        res = self._get(client, f"from={_day(9)}&to={_day(2)}")
        assert res["mode"] == "range"
        assert res["start"] == _day(9) and res["end"] == _day(2)
        assert res["days"] == 8
        assert [d["date"] for d in res["series"]] == [_day(9 - i) for i in range(8)]

    def test_range_reaches_days_the_quick_segments_cannot(self, client):
        _raw_file(client, _day(40), 5)
        assert self._get(client, f"from={_day(60)}&to={_day(30)}")["totals"]["found"] == 5
        assert self._get(client, "days=30")["totals"]["found"] == 0

    def test_reversed_or_half_filled_range_is_ordered(self, client):
        res = self._get(client, f"from={_day(2)}&to={_day(9)}")      # поля наоборот
        assert res["start"] == _day(9) and res["end"] == _day(2)
        res = self._get(client, f"from={_day(3)}")                   # задано только начало
        assert res["start"] == _day(3) and res["end"] == date.today().isoformat()

    def test_future_end_is_cut_to_today(self, client):
        res = self._get(client, f"from={_day(2)}&to=2099-01-01")
        assert res["end"] == date.today().isoformat()
        assert res["days"] == 3

    def test_range_longer_than_a_year_is_truncated_and_flagged(self, client):
        res = self._get(client, "from=2000-01-01&to=2099-01-01")
        assert res["truncated"] is True
        assert res["days"] == 366
        assert res["start"] == (date.today() - timedelta(days=365)).isoformat()
        assert res["end"] == date.today().isoformat()

    def test_quick_periods_are_never_flagged_as_truncated(self, client):
        assert self._get(client, "days=7")["truncated"] is False
        assert self._get(client, "days=1000")["truncated"] is False

    def test_explicit_range_wins_over_days(self, client):
        res = self._get(client, f"days=7&from={_day(3)}&to={_day(1)}")
        assert res["mode"] == "range" and res["days"] == 3


# ── Почасовой ряд «Сегодня» ───────────────────────────────

class TestHours:
    def _get(self, client, query):
        return client.get("/stats/daily?" + query).get_json()

    def test_single_day_with_hours_returns_24_buckets(self, client):
        _raw_file(client, _day(0), 5)
        res = self._get(client, "days=1&hours=1")
        assert "hours" in res
        assert [h["hour"] for h in res["hours"]] == list(range(24))

    def test_hour_is_taken_from_the_file_name(self, client):
        # raw_…_14-01_… и raw_…_14-50_… — обе записи в колонку «14».
        path = client.dirs["raw"] / f"raw_{_day(0)}_14-01_кафе.xlsx"
        save_excel([_rec(f"a{i}") for i in range(3)], str(path))
        path2 = client.dirs["raw"] / f"raw_{_day(0)}_14-50_бар.xlsx"
        save_excel([_rec(f"b{i}") for i in range(2)], str(path2))
        res = self._get(client, "days=1&hours=1")
        hour14 = res["hours"][14]
        assert hour14["found"] == 5 and hour14["files"] == 2
        assert sum(h["found"] for h in res["hours"]) == 5

    def test_hours_sum_matches_the_daily_total(self, client):
        _raw_file(client, _day(0), 7)          # имя несёт 10-00 → час 10
        res = self._get(client, "days=1&hours=1")
        assert res["totals"]["found"] == 7
        assert sum(h["found"] for h in res["hours"]) == 7

    def test_processed_files_do_not_invent_hours(self, client):
        _proc_file(client, "excel", "кафе", 4, day=_day(0))
        res = self._get(client, "days=1&hours=1")
        assert res["hours"] is None, "у processed времени поиска в имени нет"

    def test_hours_absent_for_multi_day_windows(self, client):
        _raw_file(client, _day(0), 5)
        assert "hours" not in self._get(client, "days=7&hours=1")
        assert "hours" not in self._get(client, "days=7")

    def test_hours_flag_without_single_day_window_is_ignored(self, client):
        if date.today().day == 1:
            pytest.skip("1-го числа окно месяца — один день: hours там уместен")
        res = self._get(client, "month=" + date.today().strftime("%Y-%m") + "&hours=1")
        assert "hours" not in res
