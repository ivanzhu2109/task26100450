"""Loading and validation of planning workpapers stored as local JSON files.

Workpaper format::

    {
      "departments": {"财务部": [101, 102], "内审部": [201]},
      "controls": [
        {"id": 1, "department": "财务部",
         "first_due": "2026-01-31", "frequency": "monthly"}
      ]
    }

The loaded plan is read-only: all mutation attempts raise, and the source
file is never written back.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .models import ControlItem, Frequency


class PlanError(ValueError):
    """Raised when a planning workpaper is malformed or inconsistent."""


def load_plan(path: str | Path) -> "Plan":
    """Load a planning workpaper from a JSON file into a read-only plan."""
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return Plan(_parse(raw))


def _parse(raw: Any) -> "_PlanData":
    if not isinstance(raw, dict):
        raise PlanError("workpaper root must be a JSON object")
    departments = _parse_departments(raw.get("departments"))
    controls = _parse_controls(raw.get("controls"), departments)
    return _PlanData(departments=departments, controls=controls)


def _parse_departments(raw: Any) -> dict[str, tuple[int, ...]]:
    if not isinstance(raw, dict) or not raw:
        raise PlanError("'departments' must be a non-empty JSON object")
    departments: dict[str, tuple[int, ...]] = {}
    for name, roster in raw.items():
        if not isinstance(name, str) or not name:
            raise PlanError("department names must be non-empty strings")
        if (
            not isinstance(roster, list)
            or not roster
            or any(not _is_int(auditor) for auditor in roster)
        ):
            raise PlanError(
                f"department {name!r} must have a non-empty roster of integer auditor ids"
            )
        if len(set(roster)) != len(roster):
            raise PlanError(f"department {name!r} has duplicate auditor ids")
        departments[name] = tuple(roster)
    return departments


def _parse_controls(raw: Any, departments: dict[str, tuple[int, ...]]) -> tuple[ControlItem, ...]:
    if not isinstance(raw, list):
        raise PlanError("'controls' must be a JSON array")
    seen_ids: set[int] = set()
    controls: list[ControlItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise PlanError("each control must be a JSON object")
        control_id = entry.get("id")
        if not _is_int(control_id):
            raise PlanError("control 'id' must be an integer")
        if control_id in seen_ids:
            raise PlanError(f"duplicate control id {control_id}")
        seen_ids.add(control_id)
        department = entry.get("department")
        if department not in departments:
            raise PlanError(f"control {control_id} references unknown department {department!r}")
        try:
            frequency = Frequency(entry.get("frequency"))
        except ValueError:
            allowed = ", ".join(member.value for member in Frequency)
            raise PlanError(
                f"control {control_id} has invalid frequency; expected one of: {allowed}"
            ) from None
        first_due_raw = entry.get("first_due")
        if not isinstance(first_due_raw, str):
            raise PlanError(f"control {control_id} 'first_due' must be an ISO date string")
        try:
            first_due = dt.date.fromisoformat(first_due_raw)
        except ValueError:
            raise PlanError(
                f"control {control_id} has invalid first_due {first_due_raw!r}"
            ) from None
        controls.append(
            ControlItem(
                control_id=control_id,
                department=department,
                first_due=first_due,
                frequency=frequency,
            )
        )
    return tuple(controls)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _PlanData:
    __slots__ = ("departments", "controls")

    def __init__(self, departments: dict[str, tuple[int, ...]], controls: tuple[ControlItem, ...]):
        self.departments = departments
        self.controls = controls


class Plan:
    """Read-only, in-memory view of a loaded planning workpaper."""

    __slots__ = ("_data",)

    def __init__(self, data: _PlanData):
        object.__setattr__(self, "_data", data)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Plan is read-only")

    @property
    def controls(self) -> tuple[ControlItem, ...]:
        return self._data.controls

    @property
    def departments(self) -> MappingProxyType[str, tuple[int, ...]]:
        return MappingProxyType(self._data.departments)
