"""Deterministic 90-day rehearsal scheduling over a loaded plan."""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Iterable

from .loader import Plan
from .models import ControlItem, Frequency, ScheduledTask

WINDOW_DAYS = 90

_MONTH_STEPS = {
    Frequency.MONTHLY: 1,
    Frequency.QUARTERLY: 3,
    Frequency.ANNUAL: 12,
}


def preview(
    plan: Plan,
    window_start: dt.date,
    control_ids: Iterable[int] | None = None,
) -> list[ScheduledTask]:
    """Rehearse tasks due in [window_start, window_start + 90 days).

    Filtering by control ids or window never changes the underlying
    per-department rotation; it only changes which tasks are returned.
    Tasks before the window and tasks of unselected controls still occupy
    their rotation slots.
    """
    if not isinstance(window_start, dt.date) or isinstance(window_start, dt.datetime):
        raise TypeError("window_start must be a datetime.date")
    window_end = window_start + dt.timedelta(days=WINDOW_DAYS)
    selected = None if control_ids is None else set(control_ids)

    by_department: dict[str, list[ControlItem]] = {}
    for control in plan.controls:
        by_department.setdefault(control.department, []).append(control)

    results: list[ScheduledTask] = []
    for department, controls in by_department.items():
        roster = sorted(plan.departments[department])
        # The rotation always spans every control of the department, so
        # unselected tasks and pre-window tasks still occupy their slots.
        sequence = _department_sequence(controls, window_end)
        for index, (due_date, control) in enumerate(sequence):
            if due_date < window_start:
                continue
            if selected is not None and control.control_id not in selected:
                continue
            results.append(
                ScheduledTask(
                    control_id=control.control_id,
                    department=department,
                    due_date=due_date,
                    auditor_id=roster[index % len(roster)],
                )
            )
    results.sort(key=lambda task: (task.due_date, task.control_id))
    return results


def _department_sequence(
    controls: list[ControlItem], horizon: dt.date
) -> list[tuple[dt.date, ControlItem]]:
    """Full logical task sequence of one department up to horizon (exclusive).

    Occurrences always start at each control's first due date, regardless of
    any queried window, so the rotation never depends on query history.
    """
    occurrences: list[tuple[dt.date, ControlItem]] = []
    for control in controls:
        step = _MONTH_STEPS[control.frequency]
        due_date = control.first_due
        while due_date < horizon:
            occurrences.append((due_date, control))
            due_date = _add_months(control.first_due, step, due_date)
    occurrences.sort(key=lambda item: (item[0], item[1].control_id))
    return occurrences


def _add_months(first_due: dt.date, step: int, current: dt.date) -> dt.date:
    """Advance current by step months, anchored on first_due's day.

    The day-of-month always comes from the first due date; if the target
    month lacks that day, the month end is used without shortening later
    occurrences (e.g. Jan 31 -> Feb 28 -> Mar 31).
    """
    month_index = (current.year * 12 + current.month - 1) + step
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(first_due.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)
