"""Tests for the audit scheduling rehearsal library.

The reference implementation below is intentionally written independently
from the library (own month arithmetic, own rotation loop) so the two can
be cross-checked on full-history schedules.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import random
import tempfile
import unittest
from pathlib import Path

from audit_preview import Frequency, PlanError, load_plan, preview


# --------------------------------------------------------------------------
# Independent reference implementation
# --------------------------------------------------------------------------

_STEP = {"monthly": 1, "quarterly": 3, "annual": 12}


def _ref_add_months(year: int, month: int, anchor_day: int, offset: int) -> dt.date:
    total = (year * 12 + (month - 1)) + offset
    new_year, rem = divmod(total, 12)
    new_month = rem + 1
    if new_month == 12:
        next_first = dt.date(new_year + 1, 1, 1)
    else:
        next_first = dt.date(new_year, new_month + 1, 1)
    last_day = (next_first - dt.timedelta(days=1)).day
    return dt.date(new_year, new_month, min(anchor_day, last_day))


def _ref_occurrences(control: dict, horizon: dt.date) -> list[dt.date]:
    first = dt.date.fromisoformat(control["first_due"])
    step = _STEP[control["frequency"]]
    dates = []
    for n in itertools.count():
        due = _ref_add_months(first.year, first.month, first.day, step * n)
        if due >= horizon:
            break
        dates.append(due)
    return dates


def reference_schedule(doc: dict, horizon: dt.date) -> list[tuple[dt.date, int, str, int]]:
    """Full-history schedule: (due_date, control_id, department, auditor_id)."""
    rows: list[tuple[dt.date, int, str, int]] = []
    for department, roster in doc["departments"].items():
        auditors = sorted(roster)
        sequence = []
        for control in doc["controls"]:
            if control["department"] != department:
                continue
            for due in _ref_occurrences(control, horizon):
                sequence.append((due, control["id"]))
        sequence.sort(key=lambda item: (item[0], item[1]))
        for index, (due, control_id) in enumerate(sequence):
            rows.append((due, control_id, department, auditors[index % len(auditors)]))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def write_plan(doc: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    with handle:
        json.dump(doc, handle, ensure_ascii=False)
    return Path(handle.name)


class PlanFileMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self._paths:
            path.unlink(missing_ok=True)

    def make_plan(self, doc: dict):
        path = write_plan(doc)
        self._paths.append(path)
        return load_plan(path)


# --------------------------------------------------------------------------
# Date arithmetic and rotation vs. independent reference
# --------------------------------------------------------------------------


class TestAgainstReference(PlanFileMixin):
    DOC = {
        "departments": {"财务部": [101, 102, 103], "内审部": [201, 202]},
        "controls": [
            # month-end clamping: Jan 31 -> Feb 28 -> Mar 31 (non-leap)
            {"id": 1, "department": "财务部", "first_due": "2025-01-31", "frequency": "monthly"},
            # quarterly across year boundary
            {"id": 2, "department": "财务部", "first_due": "2025-10-15", "frequency": "quarterly"},
            # leap-day annual: must restore Feb 29 on leap years
            {"id": 3, "department": "财务部", "first_due": "2024-02-29", "frequency": "annual"},
            # quarterly starting on month-end day
            {"id": 4, "department": "内审部", "first_due": "2025-11-30", "frequency": "quarterly"},
            # annual on plain date
            {"id": 5, "department": "内审部", "first_due": "2025-06-10", "frequency": "annual"},
        ],
    }
    HORIZON = dt.date(2030, 1, 1)

    def test_full_history_matches_reference(self) -> None:
        plan = self.make_plan(self.DOC)
        expected = reference_schedule(self.DOC, self.HORIZON)
        # Replay the full history through 90-day windows and stitch it back.
        actual: list[tuple[dt.date, int, str, int]] = []
        start = min(dt.date.fromisoformat(c["first_due"]) for c in self.DOC["controls"])
        while start < self.HORIZON:
            for task in preview(plan, start):
                if task.due_date < self.HORIZON:
                    actual.append(
                        (task.due_date, task.control_id, task.department, task.auditor_id)
                    )
            start += dt.timedelta(days=90)
        self.assertEqual(expected, actual)

    def test_month_end_clamping_dates(self) -> None:
        plan = self.make_plan(self.DOC)
        tasks = preview(plan, dt.date(2026, 1, 1), control_ids=[1])
        due = [t.due_date for t in tasks]
        self.assertEqual(
            due,
            [dt.date(2026, 1, 31), dt.date(2026, 2, 28), dt.date(2026, 3, 31)],
        )

    def test_leap_day_annual_restores_feb29(self) -> None:
        plan = self.make_plan(self.DOC)
        tasks = preview(plan, dt.date(2028, 1, 1), control_ids=[3])
        self.assertEqual([t.due_date for t in tasks], [dt.date(2028, 2, 29)])

    def test_quarterly_crosses_year(self) -> None:
        plan = self.make_plan(self.DOC)
        tasks = preview(plan, dt.date(2026, 1, 1), control_ids=[2])
        self.assertEqual(
            [t.due_date for t in tasks],
            [dt.date(2026, 1, 15)],
        )
        # A window starting 2025-10-20 ends 2026-01-18, so it must contain
        # the next quarterly occurrence across the year boundary.
        tasks = preview(plan, dt.date(2025, 10, 20), control_ids=[2])
        self.assertEqual(
            [t.due_date for t in tasks],
            [dt.date(2026, 1, 15)],
        )


# --------------------------------------------------------------------------
# Query-independence: windows, order, and subsets never change assignments
# --------------------------------------------------------------------------


class TestQueryIndependence(PlanFileMixin):
    DOC = {
        "departments": {"财务部": [105, 101, 103]},
        "controls": [
            {"id": 1, "department": "财务部", "first_due": "2026-01-05", "frequency": "monthly"},
            {"id": 2, "department": "财务部", "first_due": "2026-01-05", "frequency": "quarterly"},
            {"id": 3, "department": "财务部", "first_due": "2026-02-20", "frequency": "monthly"},
            {"id": 4, "department": "财务部", "first_due": "2026-03-01", "frequency": "annual"},
        ],
    }

    def test_overlapping_windows_agree(self) -> None:
        plan = self.make_plan(self.DOC)
        first = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, dt.date(2026, 1, 1))}
        second = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, dt.date(2026, 2, 15))}
        for key in first.keys() & second.keys():
            self.assertEqual(first[key], second[key], f"mismatch at {key}")

    def test_reverse_order_queries_agree(self) -> None:
        plan = self.make_plan(self.DOC)
        late = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, dt.date(2026, 6, 1))}
        early = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, dt.date(2026, 1, 1))}
        again = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, dt.date(2026, 6, 1))}
        self.assertEqual(late, again)
        for key in early.keys() & late.keys():
            self.assertEqual(early[key], late[key], f"mismatch at {key}")

    def test_subset_queries_match_full_run(self) -> None:
        plan = self.make_plan(self.DOC)
        start = dt.date(2026, 1, 1)
        full = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, start)}
        rng = random.Random(20261004)
        for _ in range(20):
            subset = [cid for cid in (1, 2, 3, 4) if rng.random() < 0.5]
            if not subset:
                continue
            for task in preview(plan, start, control_ids=subset):
                key = (task.due_date, task.control_id)
                self.assertIn(key, full)
                self.assertEqual(full[key], task.auditor_id, f"mismatch at {key}")

    def test_same_day_controls_follow_id_order(self) -> None:
        plan = self.make_plan(self.DOC)
        tasks = preview(plan, dt.date(2026, 1, 1))
        jan5 = [t for t in tasks if t.due_date == dt.date(2026, 1, 5)]
        self.assertEqual([t.control_id for t in jan5], [1, 2])
        # Roster sorted ascending: [101, 103, 105]; first two tasks of the
        # department sequence are exactly these two same-day tasks.
        self.assertEqual([t.auditor_id for t in jan5], [101, 103])

    def test_unselected_tasks_still_occupy_rotation_slots(self) -> None:
        plan = self.make_plan(self.DOC)
        start = dt.date(2026, 1, 1)
        full = {(t.due_date, t.control_id): t.auditor_id for t in preview(plan, start)}
        only_three = preview(plan, start, control_ids=[3])
        self.assertTrue(only_three)
        for task in only_three:
            self.assertEqual(full[(task.due_date, task.control_id)], task.auditor_id)

    def test_window_before_first_due_yields_nothing(self) -> None:
        plan = self.make_plan(self.DOC)
        self.assertEqual(preview(plan, dt.date(2025, 1, 1)), [])
        self.assertEqual(preview(plan, dt.date(2025, 1, 1), control_ids=[1, 2]), [])

    def test_window_start_inclusive_end_exclusive(self) -> None:
        plan = self.make_plan(self.DOC)
        start = dt.date(2026, 1, 5)
        tasks = preview(plan, start)
        self.assertTrue(all(t.due_date >= start for t in tasks))
        self.assertTrue(all(t.due_date < start + dt.timedelta(days=90) for t in tasks))
        self.assertTrue(any(t.due_date == start for t in tasks))


# --------------------------------------------------------------------------
# Loader validation
# --------------------------------------------------------------------------


class TestLoader(PlanFileMixin):
    def test_roundtrip_and_read_only(self) -> None:
        doc = {
            "departments": {"财务部": [102, 101]},
            "controls": [
                {"id": 7, "department": "财务部", "first_due": "2026-01-31", "frequency": "monthly"}
            ],
        }
        plan = self.make_plan(doc)
        self.assertEqual(plan.controls[0].control_id, 7)
        self.assertEqual(plan.controls[0].frequency, Frequency.MONTHLY)
        self.assertEqual(dict(plan.departments), {"财务部": (102, 101)})
        with self.assertRaises(AttributeError):
            plan.controls = ()  # type: ignore[misc]
        with self.assertRaises(TypeError):
            plan.departments["财务部"] = (1,)  # type: ignore[index]

    def test_rejects_duplicate_control_ids(self) -> None:
        doc = {
            "departments": {"财务部": [1]},
            "controls": [
                {"id": 1, "department": "财务部", "first_due": "2026-01-01", "frequency": "monthly"},
                {"id": 1, "department": "财务部", "first_due": "2026-02-01", "frequency": "annual"},
            ],
        }
        with self.assertRaises(PlanError):
            self.make_plan(doc)

    def test_rejects_empty_roster(self) -> None:
        doc = {
            "departments": {"财务部": []},
            "controls": [],
        }
        with self.assertRaises(PlanError):
            self.make_plan(doc)

    def test_rejects_unknown_department(self) -> None:
        doc = {
            "departments": {"财务部": [1]},
            "controls": [
                {"id": 1, "department": "不存在", "first_due": "2026-01-01", "frequency": "monthly"}
            ],
        }
        with self.assertRaises(PlanError):
            self.make_plan(doc)

    def test_rejects_bad_frequency_and_date(self) -> None:
        base = {"departments": {"财务部": [1]}}
        for field, value in (("frequency", "weekly"), ("first_due", "2026-13-01")):
            control = {"id": 1, "department": "财务部", "first_due": "2026-01-01", "frequency": "monthly"}
            control[field] = value
            with self.assertRaises(PlanError, msg=field):
                self.make_plan({**base, "controls": [control]})


if __name__ == "__main__":
    unittest.main()
