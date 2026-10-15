"""邮件渲染层：把 Digest 和 Snapshot 渲染成 HTML 邮件加纯文本备用版本。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..models import Digest, Snapshot
from ._common import FALLBACK_NOTICE, Meta, date_cn, format_dt, resolve_date, weekday_cn
from .email_html import render_html
from .email_text import render_text

EMAIL_TITLE = "X 热点日报"


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def render_email(
    digest: Digest,
    snapshot: Optional[Snapshot] = None,
    now: Optional[datetime] = None,
) -> RenderedEmail:
    """now 只用于"邮件生成时间"和没有 fetched_at 时的日期，测试里可注入以保证输出稳定。"""
    shown = resolve_date(snapshot, now)
    meta = Meta(
        title=EMAIL_TITLE,
        date_label=date_cn(shown),
        weekday=weekday_cn(shown),
        generated=(now or datetime.now()).strftime("%Y-%m-%d %H:%M"),
        fetched=format_dt(snapshot.fetched_at) if snapshot and snapshot.fetched_at else "",
    )
    subject = "%s · %s" % (EMAIL_TITLE, meta.date_label)
    if digest.fallback:
        subject += "（%s）" % FALLBACK_NOTICE
    return RenderedEmail(
        subject=subject,
        html=render_html(digest, snapshot, meta),
        text=render_text(digest, snapshot, meta),
    )


__all__ = ["EMAIL_TITLE", "RenderedEmail", "render_email"]
