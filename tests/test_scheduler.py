"""审计排程预演库的自动化测试。

包含一个独立编写的参考实现，用于对小数据的全历史完整排程逐项对照。
"""
from __future__ import annotations

import datetime
import json

import pytest

from audit_scheduler import (
    AuditPlan,
    ControlItem,
    Department,
    Frequency,
    Rehearsal,
    load_plan,
    preview,
)
from audit_scheduler.loader import PlanFormatError

ONE_DAY = datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# 独立参考实现：与库内部实现不共享任何代码
# ---------------------------------------------------------------------------

def ref_add_months(base: datetime.date, months: int) -> datetime.date:
    """参考月份偏移：用「次月1日减一天」求月末，独立实现日号回退。"""
    total = (base.year * 12 + base.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        month_end = datetime.date(year, 12, 31)
    else:
        month_end = datetime.date(year, month + 1, 1) - ONE_DAY
    return datetime.date(year, month, min(base.day, month_end.day))


def ref_full_schedule(plan: AuditPlan, horizon: datetime.date):
    """参考全历史排程：逐控制项生成全部到期日，再逐部门排序轮转。"""
    auditors = {d.name: sorted(d.auditor_ids) for d in plan.departments}
    by_department: dict[str, list[tuple[datetime.date, int]]] = {
        d.name: [] for d in plan.departments
    }
    for control in plan.controls:
        step = {Frequency.MONTHLY: 1, Frequency.QUARTERLY: 3,
                Frequency.ANNUALLY: 12}[control.frequency]
        n = 0
        while True:
            due = ref_add_months(control.first_due_date, n * step)
            if due >= horizon:
                break
            by_department[control.department].append((due, control.control_id))
            n += 1
    result = {}
    for department, entries in by_department.items():
        entries.sort(key=lambda e: (e[0], e[1]))
        roster = auditors[department]
        for index, (due, control_id) in enumerate(entries):
            result[(control_id, due)] = roster[index % len(roster)]
    return result


def make_plan(controls, departments) -> AuditPlan:
    return AuditPlan(controls=tuple(controls), departments=tuple(departments))


# ---------------------------------------------------------------------------
# 月末、季度跨年、闰日年度
# ---------------------------------------------------------------------------

def test_monthly_month_end_clamping_and_recovery():
    plan = make_plan(
        [ControlItem(1, "财务部", datetime.date(2025, 1, 31), Frequency.MONTHLY)],
        [Department("财务部", (11,))],
    )
    tasks = preview(plan, datetime.date(2025, 1, 1))
    dates = [t.due_date for t in tasks]
    assert dates == [
        datetime.date(2025, 1, 31),
        datetime.date(2025, 2, 28),  # 非闰年 2 月月末
        datetime.date(2025, 3, 31),  # 恢复 31 日，不沿用 28 日
    ]
    assert all(t.auditor_id == 11 for t in tasks)


def test_quarterly_cross_year():
    plan = make_plan(
        [ControlItem(1, "内审部", datetime.date(2025, 10, 31), Frequency.QUARTERLY)],
        [Department("内审部", (7,))],
    )
    tasks = preview(plan, datetime.date(2025, 10, 1))
    assert [t.due_date for t in tasks] == [
        datetime.date(2025, 10, 31),
    ]
    # 2026-01-31 超出 90 天窗口（窗口止于 2025-12-30），需从更晚的起点查看
    tasks = preview(plan, datetime.date(2026, 1, 1))
    assert [t.due_date for t in tasks] == [
        datetime.date(2026, 1, 31),  # 跨年
    ]
    tasks = preview(plan, datetime.date(2026, 1, 1))
    assert [t.due_date for t in tasks] == [
        datetime.date(2026, 1, 31),
    ]


def test_leap_day_annually_restores_feb29():
    plan = make_plan(
        [ControlItem(1, "合规部", datetime.date(2024, 2, 29), Frequency.ANNUALLY)],
        [Department("合规部", (5,))],
    )
    rehearsal = Rehearsal(plan)
    years = {}
    for year in range(2024, 2029):
        for t in rehearsal.preview(datetime.date(year, 1, 1)):
            years.setdefault(t.due_date.year, []).append(t.due_date)
    assert years[2024] == [datetime.date(2024, 2, 29)]
    assert years[2025] == [datetime.date(2025, 2, 28)]
    assert years[2026] == [datetime.date(2026, 2, 28)]
    assert years[2027] == [datetime.date(2027, 2, 28)]
    assert years[2028] == [datetime.date(2028, 2, 29)]  # 闰年恢复 29 日


# ---------------------------------------------------------------------------
# 与独立参考实现逐项对照（小数据全历史完整排程）
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_plan() -> AuditPlan:
    return make_plan(
        [
            ControlItem(1, "财务部", datetime.date(2024, 1, 31), Frequency.MONTHLY),
            ControlItem(2, "财务部", datetime.date(2024, 2, 29), Frequency.ANNUALLY),
            ControlItem(3, "财务部", datetime.date(2024, 3, 15), Frequency.QUARTERLY),
            ControlItem(4, "内审部", datetime.date(2024, 1, 31), Frequency.QUARTERLY),
            ControlItem(5, "内审部", datetime.date(2024, 6, 30), Frequency.MONTHLY),
            ControlItem(6, "内审部", datetime.date(2024, 2, 29), Frequency.ANNUALLY),
        ],
        [
            Department("财务部", (101, 102, 103)),
            Department("内审部", (201, 202)),
        ],
    )


def test_matches_reference_full_history(small_plan):
    horizon = datetime.date(2030, 1, 1)
    reference = ref_full_schedule(small_plan, horizon)
    rehearsal = Rehearsal(small_plan)
    # 用连续 90 天窗口覆盖整个历史区间，汇总后与参考逐项对照
    seen = {}
    start = datetime.date(2024, 1, 1)
    while start < horizon:
        for t in rehearsal.preview(start):
            if t.due_date >= horizon:
                continue  # 末个窗口可能越过 horizon，参考实现不含这些任务
            key = (t.control_id, t.due_date)
            assert key not in seen or seen[key] == t.auditor_id
            seen[key] = t.auditor_id
        start += datetime.timedelta(days=90)
    assert seen == reference


def test_window_excludes_start_minus_one_and_end_day(small_plan):
    start = datetime.date(2026, 3, 1)
    tasks = preview(small_plan, start)
    assert all(start <= t.due_date < start + datetime.timedelta(days=90) for t in tasks)


def test_window_before_first_due_yields_nothing():
    plan = make_plan(
        [ControlItem(1, "财务部", datetime.date(2030, 5, 1), Frequency.MONTHLY)],
        [Department("财务部", (1, 2))],
    )
    assert preview(plan, datetime.date(2029, 1, 1)) == []


# ---------------------------------------------------------------------------
# 查询方式不影响轮转序位
# ---------------------------------------------------------------------------

def test_overlapping_windows_consistent(small_plan):
    rehearsal = Rehearsal(small_plan)
    first = {(t.control_id, t.due_date): t.auditor_id
             for t in rehearsal.preview(datetime.date(2026, 1, 1))}
    second = {(t.control_id, t.due_date): t.auditor_id
              for t in rehearsal.preview(datetime.date(2026, 2, 15))}
    overlap = set(first) & set(second)
    assert overlap  # 确保确实存在重叠任务
    for key in overlap:
        assert first[key] == second[key]


def test_reverse_order_viewing_consistent(small_plan):
    rehearsal = Rehearsal(small_plan)
    later = rehearsal.preview(datetime.date(2027, 1, 1))
    earlier = rehearsal.preview(datetime.date(2026, 1, 1))
    fresh = Rehearsal(small_plan)
    earlier_fresh = fresh.preview(datetime.date(2026, 1, 1))
    later_fresh = fresh.preview(datetime.date(2027, 1, 1))
    assert earlier == earlier_fresh
    assert later == later_fresh


def test_subset_view_matches_full_view_and_keeps_rotation(small_plan):
    rehearsal = Rehearsal(small_plan)
    start = datetime.date(2026, 1, 1)
    full = {(t.control_id, t.due_date): t.auditor_id
            for t in rehearsal.preview(start)}
    subset_ids = [2, 4]
    subset = rehearsal.preview(start, control_ids=subset_ids)
    assert {t.control_id for t in subset} <= set(subset_ids)
    for t in subset:
        # 未被选中的任务仍占轮次：子集结果与全量结果中的人选完全一致
        assert full[(t.control_id, t.due_date)] == t.auditor_id


def test_unselected_tasks_still_consume_rotation_slots():
    plan = make_plan(
        [
            ControlItem(1, "财务部", datetime.date(2026, 1, 1), Frequency.MONTHLY),
            ControlItem(2, "财务部", datetime.date(2026, 1, 1), Frequency.MONTHLY),
        ],
        [Department("财务部", (101, 102))],
    )
    start = datetime.date(2026, 1, 1)
    only_two = preview(plan, start, control_ids=[2])
    # 控制项 2 的每次任务在部门序列中恒为偶数位，固定轮到 102
    assert [t.auditor_id for t in only_two] == [102, 102, 102]
    only_one = preview(plan, start, control_ids=[1])
    assert [t.auditor_id for t in only_one] == [101, 101, 101]


def test_same_day_controls_ordered_by_id():
    plan = make_plan(
        [
            ControlItem(9, "财务部", datetime.date(2026, 3, 10), Frequency.ANNUALLY),
            ControlItem(3, "财务部", datetime.date(2026, 3, 10), Frequency.ANNUALLY),
            ControlItem(7, "财务部", datetime.date(2026, 3, 10), Frequency.ANNUALLY),
        ],
        [Department("财务部", (101, 102, 103))],
    )
    tasks = preview(plan, datetime.date(2026, 3, 1))
    assert [t.control_id for t in tasks] == [3, 7, 9]
    # 序列第一项交给编号最小的审计员，依编号升序循环
    assert [t.auditor_id for t in tasks] == [101, 102, 103]


def test_auditors_assigned_in_id_order_not_roster_order():
    plan = make_plan(
        [ControlItem(1, "财务部", datetime.date(2026, 1, 1), Frequency.MONTHLY)],
        [Department("财务部", (300, 100, 200))],  # 名册顺序打乱
    )
    tasks = preview(plan, datetime.date(2026, 1, 1))
    assert [t.auditor_id for t in tasks] == [100, 200, 300]


def test_unknown_control_id_rejected(small_plan):
    with pytest.raises(KeyError):
        preview(small_plan, datetime.date(2026, 1, 1), control_ids=[999])


# ---------------------------------------------------------------------------
# 底稿载入
# ---------------------------------------------------------------------------

def write_plan(tmp_path, data) -> str:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_plan_roundtrip(tmp_path, small_plan):
    data = {
        "departments": [
            {"name": "财务部", "auditor_ids": [101, 102, 103]},
            {"name": "内审部", "auditor_ids": [201, 202]},
        ],
        "controls": [
            {"control_id": c.control_id, "department": c.department,
             "first_due_date": c.first_due_date.isoformat(),
             "frequency": c.frequency.value}
            for c in small_plan.controls
        ],
    }
    plan = load_plan(write_plan(tmp_path, data))
    assert plan == small_plan
    # 载入结果只读
    with pytest.raises(AttributeError):
        plan.controls[0].control_id = 99  # type: ignore[misc]


@pytest.mark.parametrize("data,fragment", [
    ({"departments": [], "controls": []}, "departments"),
    ({"departments": [{"name": "A", "auditor_ids": []}], "controls": []}, "auditor_ids"),
    ({"departments": [{"name": "A", "auditor_ids": [1, 1]}], "controls": []}, "重复"),
    ({"departments": [{"name": "A", "auditor_ids": [1]}],
      "controls": [{"control_id": 1, "department": "B",
                    "first_due_date": "2026-01-01", "frequency": "monthly"}]}, "不存在的部门"),
    ({"departments": [{"name": "A", "auditor_ids": [1]}],
      "controls": [{"control_id": 1, "department": "A",
                    "first_due_date": "2026-01-01", "frequency": "weekly"}]}, "frequency"),
    ({"departments": [{"name": "A", "auditor_ids": [1]}],
      "controls": [{"control_id": 1, "department": "A",
                    "first_due_date": "2026-13-01", "frequency": "monthly"}]}, "日期"),
    ({"departments": [{"name": "A", "auditor_ids": [1]}],
      "controls": [
          {"control_id": 1, "department": "A",
           "first_due_date": "2026-01-01", "frequency": "monthly"},
          {"control_id": 1, "department": "A",
           "first_due_date": "2026-02-01", "frequency": "monthly"},
      ]}, "唯一"),
])
def test_load_plan_validation(tmp_path, data, fragment):
    with pytest.raises(PlanFormatError, match=fragment):
        load_plan(write_plan(tmp_path, data))
