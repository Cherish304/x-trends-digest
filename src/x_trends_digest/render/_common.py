"""HTML 与纯文本渲染共用的小工具和展示上限。"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

from ..models import Snapshot

MAX_TRENDS = 10  # 趋势排行最多展示条数
MAX_POSTS = 10  # 热帖卡片最多展示条数
MAX_POST_CHARS = 300  # 单条帖子正文最多展示字数
FALLBACK_NOTICE = "AI 摘要暂不可用"


def trend_link(name: str) -> str:
    """趋势一律链接到 X 搜索页，不使用数据源给的 url（来源不可信）。"""
    return "https://x.com/search?q=" + quote(name, safe="")


def safe_url(url: str) -> str:
    """只放行 http/https 链接；其他协议（javascript: 等）和含空白/控制字符的一律丢弃。"""
    url = (url or "").strip()
    if not url or any(c.isspace() or ord(c) < 32 for c in url):
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def truncate(text: str, limit: int = MAX_POST_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def resolve_date(snapshot: Optional[Snapshot], now: Optional[datetime]) -> datetime:
    """优先用快照的 fetched_at（原样取其日期，不做时区换算），否则用 now / 当前时间。"""
    raw = snapshot.fetched_at if snapshot else ""
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return now or datetime.now()


def date_cn(dt: datetime) -> str:
    return "%d年%d月%d日" % (dt.year, dt.month, dt.day)


def one_line(text: str) -> str:
    return " ".join(text.split())
