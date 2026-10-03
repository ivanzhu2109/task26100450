"""公历日期工具：按月偏移并处理月末回退。"""
from __future__ import annotations

import calendar
import datetime


def add_months_clamped(base: datetime.date, months: int) -> datetime.date:
    """将 base 偏移 months 个月。

    始终沿用 base 的日号；目标月份没有该日号时取该月月末。
    例如 1月31日 偏移 1 个月到非闰年 2 月得到 2月28日，
    再相对首个到期日偏移 2 个月仍回到 3月31日。
    """
    total = base.year * 12 + (base.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)
