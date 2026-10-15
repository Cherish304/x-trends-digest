"""HTML 与纯文本渲染共用的小工具、展示上限和配色之外的常量。"""

import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote, urlparse

from ..models import Digest, Snapshot

MAX_TRENDS = 10  # 趋势排行最多展示条数
MAX_POSTS = 10  # 热帖卡片最多展示条数
MAX_POST_LINES = 4  # 单条帖子正文最多行数（HTML 和纯文本都一样）
LINE_UNITS = 28.0  # 每行容纳的"全角字符"数，按 600px 容器里卡片正文宽度估算
LEAD_MAX_CHARS = 90  # 「今日一句话」最多字数
TOP_TRENDS = 3  # 突出显示的前几名

FALLBACK_NOTICE = "AI 摘要暂不可用"
SUBTITLE = "每日 X 热点速览 · 趋势与热帖一页读完"
UNSUBSCRIBE_PLACEHOLDER = "{{UNSUBSCRIBE_URL}}"  # 发送前由外部程序替换成真实退订链接

_WEEKDAYS = "一二三四五六日"
_SECTION_EMOJI = (
    ("概览", "📰"), ("概述", "📰"), ("要点", "📌"), ("关注", "👀"),
    ("趋势", "🔥"), ("热帖", "💬"), ("帖子", "💬"),
)
_DEFAULT_EMOJI = "📝"
_AVATAR_COLORS = ("#2563eb", "#7c3aed", "#db2777", "#ea580c", "#059669", "#0891b2")


@dataclass(frozen=True)
class Meta:
    """渲染邮件头尾要用的元信息。"""

    title: str
    date_label: str  # 如 2026年10月14日
    weekday: str  # 如 周三
    generated: str  # 邮件生成时间，如 2026-10-14 09:05
    fetched: str  # 数据抓取时间，来源没给时为空
    subtitle: str = SUBTITLE


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


def _units(ch: str) -> float:
    return 1.0 if ord(ch) > 0x2E7F else 0.55  # 中日韩和全角符号占满格，拉丁字符约半格


def _tail_width(text: str, line_units: float) -> float:
    """按同样的折行规则模拟排版，返回最后一个视觉行已占用的宽度。"""
    cur = 0.0
    for ch in text:
        u = _units(ch)
        if cur + u > line_units:
            cur = 0.0
        cur += u
    return cur


def clamp_text(text: str, max_lines: int = MAX_POST_LINES, line_units: float = LINE_UNITS) -> List[str]:
    """按估算的折行把正文限制在 max_lines 行内，超出部分截断并以 … 结尾。

    邮件客户端普遍不支持 line-clamp，所以在这里按字符宽度估算；
    HTML 里再配一个 max-height 兜底（手机上折行更多时由它裁掉多余部分）。
    返回原始换行后的若干行（空行已丢弃）。
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()] or [""]
    out = []  # type: List[str]
    visual = 0
    truncated = False
    for raw in lines:
        visual += 1
        if visual > max_lines:
            truncated = True
            break
        cur = 0.0
        buf = []  # type: List[str]
        for ch in raw:
            u = _units(ch)
            if cur + u > line_units:
                visual += 1
                cur = 0.0
                if visual > max_lines:
                    truncated = True
                    break
            cur += u
            buf.append(ch)
        out.append("".join(buf))
        if truncated:
            break
    if truncated and out:
        last = out[-1].rstrip()
        # 给 … 腾位置，避免它折到第 5 行；只量最后一个视觉行，不是整段逻辑行
        while last and _tail_width(last, line_units) + 1 > line_units:
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out


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


def weekday_cn(dt: datetime) -> str:
    return "周" + _WEEKDAYS[dt.weekday()]


def format_dt(raw: str) -> str:
    """把 ISO 时间格式化成 2026-10-14 09:00；无法解析时返回空字符串。"""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def one_line(text: str) -> str:
    return " ".join(text.split())


def fmt_num(n: int) -> str:
    return "{:,}".format(n)


def _starts_with_emoji(text: str) -> bool:
    return bool(text) and (ord(text[0]) >= 0x1F000 or 0x2600 <= ord(text[0]) <= 0x27BF)


def section_emoji(title: str) -> str:
    """按标题关键词挑 emoji；标题自带 emoji 时不再加，避免重复。"""
    if _starts_with_emoji(title.strip()):
        return ""
    for key, emoji in _SECTION_EMOJI:
        if key in title:
            return emoji
    return _DEFAULT_EMOJI


def footer_lines(digest: Digest, meta: Meta) -> List[str]:
    """页脚的数据来源、摘要来源和时间信息；HTML 与纯文本共用，避免两边文案不一致。"""
    summary = "摘要由规则自动生成（%s）" % FALLBACK_NOTICE if digest.fallback else "摘要由 AI 模型生成"
    when = "邮件生成于 %s" % meta.generated
    if meta.fetched:
        when = "数据抓取于 %s · %s" % (meta.fetched, when)
    return [
        "数据来源：X（x.com）趋势与热门帖子，内容未经人工核实，仅供参考。",
        summary,
        when,
    ]


def initial(handle: str) -> str:
    """头像占位用的首字母（中文取首字），取不到时用 ?。"""
    for ch in handle.lstrip("@"):
        if ch.isalnum():
            return ch.upper()
    return "?"


def avatar_color(handle: str) -> str:
    """同一个作者始终同一种颜色（不用 hash()，它每次进程启动都会变）。"""
    return _AVATAR_COLORS[zlib.crc32(handle.encode("utf-8")) % len(_AVATAR_COLORS)]
