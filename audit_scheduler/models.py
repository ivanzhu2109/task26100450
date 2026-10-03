"""数据类型定义：规划底稿与预演结果。"""
from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass


class Frequency(enum.Enum):
    """控制项测试频率。"""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"

    @property
    def month_step(self) -> int:
        """每次任务相对上一次偏移的月数。"""
        return _MONTH_STEPS[self]


_MONTH_STEPS = {
    Frequency.MONTHLY: 1,
    Frequency.QUARTERLY: 3,
    Frequency.ANNUALLY: 12,
}


@dataclass(frozen=True)
class ControlItem:
    """控制项：全局唯一编号、所属部门、首个到期日与频率。"""

    control_id: int
    department: str
    first_due_date: datetime.date
    frequency: Frequency


@dataclass(frozen=True)
class Department:
    """部门：非空且固定的审计员名册（唯一整数编号）。"""

    name: str
    auditor_ids: tuple[int, ...]


@dataclass(frozen=True)
class AuditPlan:
    """规划底稿：载入后只读。"""

    controls: tuple[ControlItem, ...]
    departments: tuple[Department, ...]


@dataclass(frozen=True)
class ScheduledTask:
    """预演结果中的一项任务。"""

    control_id: int
    department: str
    due_date: datetime.date
    auditor_id: int
