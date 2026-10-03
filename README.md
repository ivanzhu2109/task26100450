# 审计排程预演库

由上层直接调用的 Python 库：规划底稿保存在本地 JSON 文件，载入后只读，
预演结果在内存中返回，无任何外部服务依赖。

## 底稿格式

```json
{
  "departments": [{"name": "财务部", "auditor_ids": [101, 102]}],
  "controls": [
    {"control_id": 1, "department": "财务部",
     "first_due_date": "2026-01-31", "frequency": "monthly"}
  ]
}
```

- `control_id`：全局唯一整数；`frequency`：`monthly` / `quarterly` / `annually`。
- 每个部门的 `auditor_ids` 非空且编号唯一。

## 用法

```python
import datetime
from audit_scheduler import load_plan, Rehearsal, preview

plan = load_plan("plan.json")                 # 整批载入，只读
tasks = preview(plan, datetime.date(2026, 1, 1))          # 全部控制项
tasks = preview(plan, datetime.date(2026, 1, 1), [1, 3])  # 指定控制项子集

rehearsal = Rehearsal(plan)                   # 复用同一底稿多次预演
tasks = rehearsal.preview(datetime.date(2026, 1, 1))
```

每次调用返回窗口 `[start, start+90天)` 内的任务（`ScheduledTask`：
控制项编号、部门、到期日、负责审计员），按到期日升序、同日按控制项编号升序。

## 规则摘要

- 第 n 次任务相对首个到期月份偏移 n、3n 或 12n 个月；日号始终沿用首个
  到期日，目标月份没有该日号时取月末（如 1月31日 → 2月28日 → 3月31日，
  闰日年度任务到下一闰年恢复 2月29日）。
- 每个部门内全部任务按 (到期日, 控制项编号) 排序，审计员按编号升序循环；
  序列第一项交给最小编号审计员。
- 轮转序位由底稿唯一决定：窗口之前及筛选之外的任务仍占轮次，查询次数、
  顺序与子集筛选均不改变任何任务的负责审计员。

## 测试

```bash
python3 -m pytest tests/ -q
```
