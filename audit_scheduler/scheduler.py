"""预演核心：部门轮转序列与 90 天窗口查询。"""
from __future__ import annotations

import datetime
from collections.abc import Iterable

from .calendar import add_months_clamped
from .models import AuditPlan, ControlItem, ScheduledTask

WINDOW_DAYS = 90


def _control_occurrences(
    control: ControlItem, window_end: datetime.date
) -> list[datetime.date]:
    """列出控制项从首个到期日起、早于 window_end 的全部到期日。

    第 n 次任务相对首个到期月份偏移 n * month_step 个月（n 从 0 开始），
    日号始终相对首个到期日计算，不沿用被缩短后的日号。
    """
    step = control.frequency.month_step
    dates = []
    n = 0
    while True:
        due = add_months_clamped(control.first_due_date, n * step)
        if due >= window_end:
            break
        dates.append(due)
        n += 1
    return dates


class Rehearsal:
    """基于只读底稿的预演器。

    部门轮转序位由底稿唯一决定，不因查询次数、顺序或子集筛选改变。
    """

    def __init__(self, plan: AuditPlan) -> None:
        self._plan = plan
        self._controls_by_id = {c.control_id: c for c in plan.controls}
        self._auditors_by_department = {
            d.name: tuple(sorted(d.auditor_ids)) for d in plan.departments
        }
        self._controls_by_department: dict[str, list[ControlItem]] = {
            d.name: [] for d in plan.departments
        }
        for control in plan.controls:
            self._controls_by_department[control.department].append(control)

    def _department_sequence(
        self, department: str, window_end: datetime.date
    ) -> list[ScheduledTask]:
        """部门逻辑序列：按 (到期日, 控制项编号) 升序，审计员按编号循环。

        包含窗口之前从未被查看过的任务，它们同样占用轮次。
        """
        auditors = self._auditors_by_department[department]
        dated: list[tuple[datetime.date, int]] = []
        for control in self._controls_by_department[department]:
            for due in _control_occurrences(control, window_end):
                dated.append((due, control.control_id))
        dated.sort()
        return [
            ScheduledTask(
                control_id=control_id,
                department=department,
                due_date=due,
                auditor_id=auditors[index % len(auditors)],
            )
            for index, (due, control_id) in enumerate(dated)
        ]

    def preview(
        self,
        start: datetime.date,
        control_ids: Iterable[int] | None = None,
    ) -> list[ScheduledTask]:
        """返回窗口 [start, start+90天) 内、属于指定控制项集合的任务。

        control_ids 为 None 时预演全部控制项。筛选只改变返回哪些任务，
        不改变全部门轮转序位。结果按 (到期日, 控制项编号) 升序。
        """
        window_end = start + datetime.timedelta(days=WINDOW_DAYS)
        if control_ids is None:
            selected = None
        else:
            selected = set(control_ids)
            unknown = selected - self._controls_by_id.keys()
            if unknown:
                raise KeyError(f"未知的控制项编号: {sorted(unknown)}")

        tasks: list[ScheduledTask] = []
        for department in self._auditors_by_department:
            for task in self._department_sequence(department, window_end):
                if task.due_date < start:
                    continue
                if selected is not None and task.control_id not in selected:
                    continue
                tasks.append(task)
        tasks.sort(key=lambda t: (t.due_date, t.control_id))
        return tasks


def preview(
    plan: AuditPlan,
    start: datetime.date,
    control_ids: Iterable[int] | None = None,
) -> list[ScheduledTask]:
    """便捷函数：整批预演 90 天窗口。"""
    return Rehearsal(plan).preview(start, control_ids)
