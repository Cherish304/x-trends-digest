"""内置调度：标准 5 段 cron 表达式（分 时 日 月 周），仅用标准库。

支持 *、数字、a-b、a,b、*/n、a-b/n。周的 0 和 7 都表示周日。
日与周同时限定时，按标准 cron 语义取"或"。
"""

import time
from datetime import datetime, timedelta
from typing import Callable, Set

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def _parse_field(spec: str, lo: int, hi: int) -> Set[int]:
    values = set()  # type: Set[int]
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError("步长必须为正: %s" % spec)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(part)
            end = hi if step != 1 else start
        if start < lo or end > hi or start > end:
            raise ValueError("cron 字段超出范围: %s" % spec)
        values.update(range(start, end + 1, step))
    return values


class CronSchedule:
    def __init__(self, expr: str) -> None:
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError("cron 表达式需要 5 段，收到: %r" % expr)
        sets = [_parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES)]
        self.minutes, self.hours, self.days, self.months, dows = sets
        self.dows = {d % 7 for d in dows}
        self._dom_star = fields[2].startswith("*")
        self._dow_star = fields[4].startswith("*")

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minutes or dt.hour not in self.hours:
            return False
        if dt.month not in self.months:
            return False
        dom_ok = dt.day in self.days
        dow_ok = ((dt.weekday() + 1) % 7) in self.dows  # Python 周一=0，cron 周日=0
        if self._dom_star or self._dow_star:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def next_after(self, dt: datetime) -> datetime:
        cur = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = cur + timedelta(days=366 * 5)
        while cur < limit:
            if self.matches(cur):
                return cur
            cur += timedelta(minutes=1)
        raise ValueError("五年内没有匹配的触发时间")


def run_forever(
    schedule: CronSchedule,
    job: Callable[[], object],
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
    max_runs: int = 0,
    on_error: Callable[[Exception], None] = lambda e: print("任务失败: %r" % e, flush=True),
) -> int:
    """阻塞运行；max_runs>0 时执行到次数后返回（便于测试）。返回已执行次数。"""
    runs = 0
    while True:
        target = schedule.next_after(now())
        delay = (target - now()).total_seconds()
        if delay > 0:
            sleep(delay)
        try:
            job()
        except Exception as exc:  # 单次失败不应让常驻进程退出
            on_error(exc)
        runs += 1
        if max_runs and runs >= max_runs:
            return runs
