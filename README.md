# 审计排程预演库（audit_preview）

由上层直接调用的纯 Python 库：规划底稿保存在本地 JSON 文件，载入后只读，
预演结果在内存中返回，不写回文件、不依赖任何外部服务。

## 底稿格式

```json
{
  "departments": {"财务部": [101, 102], "内审部": [201]},
  "controls": [
    {"id": 1, "department": "财务部", "first_due": "2026-01-31", "frequency": "monthly"},
    {"id": 2, "department": "内审部", "first_due": "2024-02-29", "frequency": "annual"}
  ]
}
```

- `id`：全局唯一整数控制项编号；`frequency` 为 `monthly` / `quarterly` / `annual`。
- `first_due`：无时区公历日期（ISO 格式），即第一次任务的到期日。
- 每个部门的名册非空且固定，审计员以唯一整数编号标识。

## 用法

```python
import datetime as dt
from audit_preview import load_plan, preview

plan = load_plan("workpaper.json")          # 只读底稿
tasks = preview(plan, dt.date(2026, 1, 1))   # 全部控制项的 90 天窗口
subset = preview(plan, dt.date(2026, 1, 1), control_ids=[1, 2])
for task in tasks:
    print(task.due_date, task.control_id, task.auditor_id)
```

`preview` 返回到期日在 `[window_start, window_start + 90 天)` 内的任务及负责审计员。

## 排程规则

- 第 n 次任务相对首个到期月份偏移 n、3n 或 12n 个月（n 从 0 开始）；日号始终沿用
  首个到期日，目标月份没有该日号时取月末，之后月份恢复原始日号
  （如 1 月 31 日 → 2 月 28 日 → 3 月 31 日；2 月 29 日起算的年度任务在闰年恢复 29 日）。
- 每个部门独立排程：全部控制项产生的任务按到期日升序、同日按控制项编号升序排列，
  审计员按编号升序循环认领，序列第一项交给编号最小的审计员。
- 该逻辑序列与查询无关：重叠窗口、逆序查看、控制项子集查看都不会改变任何任务的
  到期日或负责人；窗口之前及筛选之外的任务仍然占用轮次。

## 测试

```bash
python3 -m pytest tests/ -q
```
