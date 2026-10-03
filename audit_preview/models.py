"""Data types for the audit scheduling rehearsal library."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum


class Frequency(Enum):
    """How often a control item is tested."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


@dataclass(frozen=True)
class ControlItem:
    """A single control item from the planning workpaper."""

    control_id: int
    department: str
    first_due: dt.date
    frequency: Frequency


@dataclass(frozen=True)
class ScheduledTask:
    """One rehearsal result entry: a task occurrence and its auditor."""

    control_id: int
    department: str
    due_date: dt.date
    auditor_id: int
