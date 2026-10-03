"""从本地 JSON 文件载入规划底稿，载入后只读。"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from .models import AuditPlan, ControlItem, Department, Frequency


class PlanFormatError(ValueError):
    """底稿内容不符合约定格式。"""


def _fail(message: str) -> None:
    raise PlanFormatError(message)


def _parse_date(value: object, where: str) -> datetime.date:
    if not isinstance(value, str):
        _fail(f"{where}: 日期必须是 ISO 字符串，得到 {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        _fail(f"{where}: 非法日期 {value!r}")


def _parse_department(raw: object, index: int) -> Department:
    where = f"departments[{index}]"
    if not isinstance(raw, dict):
        _fail(f"{where}: 必须是对象")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        _fail(f"{where}: name 必须是非空字符串")
    auditor_ids = raw.get("auditor_ids")
    if (
        not isinstance(auditor_ids, list)
        or not auditor_ids
        or any(not isinstance(a, int) or isinstance(a, bool) for a in auditor_ids)
    ):
        _fail(f"{where}: auditor_ids 必须是非空整数数组")
    if len(set(auditor_ids)) != len(auditor_ids):
        _fail(f"{where}: auditor_ids 存在重复编号")
    return Department(name=name, auditor_ids=tuple(auditor_ids))


def _parse_control(raw: object, index: int) -> ControlItem:
    where = f"controls[{index}]"
    if not isinstance(raw, dict):
        _fail(f"{where}: 必须是对象")
    control_id = raw.get("control_id")
    if not isinstance(control_id, int) or isinstance(control_id, bool):
        _fail(f"{where}: control_id 必须是整数")
    department = raw.get("department")
    if not isinstance(department, str) or not department:
        _fail(f"{where}: department 必须是非空字符串")
    first_due_date = _parse_date(raw.get("first_due_date"), where)
    frequency_raw = raw.get("frequency")
    try:
        frequency = Frequency(frequency_raw)
    except ValueError:
        _fail(f"{where}: frequency 必须是 monthly/quarterly/annually，得到 {frequency_raw!r}")
    return ControlItem(
        control_id=control_id,
        department=department,
        first_due_date=first_due_date,
        frequency=frequency,
    )


def load_plan(path: str | Path) -> AuditPlan:
    """读取 JSON 底稿并校验，返回只读的 AuditPlan。

    底稿格式::

        {
          "departments": [{"name": "财务部", "auditor_ids": [101, 102]}],
          "controls": [
            {"control_id": 1, "department": "财务部",
             "first_due_date": "2026-01-31", "frequency": "monthly"}
          ]
        }
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        _fail("底稿顶层必须是对象")

    raw_departments = data.get("departments")
    if not isinstance(raw_departments, list) or not raw_departments:
        _fail("departments 必须是非空数组")
    departments = tuple(
        _parse_department(raw, i) for i, raw in enumerate(raw_departments)
    )
    department_names = [d.name for d in departments]
    if len(set(department_names)) != len(department_names):
        _fail("部门名称重复")

    raw_controls = data.get("controls")
    if not isinstance(raw_controls, list):
        _fail("controls 必须是数组")
    controls = tuple(_parse_control(raw, i) for i, raw in enumerate(raw_controls))
    control_ids = [c.control_id for c in controls]
    if len(set(control_ids)) != len(control_ids):
        _fail("control_id 必须全局唯一")
    known = set(department_names)
    for control in controls:
        if control.department not in known:
            _fail(f"控制项 {control.control_id} 引用了不存在的部门 {control.department!r}")

    return AuditPlan(controls=controls, departments=departments)
