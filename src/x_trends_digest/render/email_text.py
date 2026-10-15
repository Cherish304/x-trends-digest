"""纯文本备用版本：给不显示 HTML 的客户端用，版式与 HTML 一一对应。"""

import re
from typing import List, Optional

from ..models import Digest, Snapshot
from ._common import (
    FALLBACK_NOTICE,
    LEAD_MAX_CHARS,
    MAX_POSTS,
    MAX_TRENDS,
    UNSUBSCRIBE_PLACEHOLDER,
    Meta,
    clamp_text,
    fmt_num,
    footer_lines,
    one_line,
    safe_url,
    section_emoji,
    trend_link,
)
from ._md import parse_sections, split_lead

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RULE = "=" * 36
_THIN = "-" * 36


def _plain(text: str) -> str:
    return _BOLD.sub(r"\1", text)


def _heading(title: str) -> List[str]:
    emoji = section_emoji(title)
    return [("%s %s" % (emoji, _plain(title))).strip(), _THIN]


def render_text(digest: Digest, snapshot: Optional[Snapshot], meta: Meta) -> str:
    out = [
        _RULE,
        "%s  X TRENDS DIGEST" % meta.title,
        "%s · %s" % (meta.date_label, meta.weekday),
        meta.subtitle,
        _RULE,
        "",
    ]  # type: List[str]
    if digest.fallback:
        out += ["⚠️ 【%s】以下为根据抓取数据自动生成的简要摘要。" % FALLBACK_NOTICE, ""]

    lead, sections = split_lead(parse_sections(digest.body), LEAD_MAX_CHARS)
    if lead:
        out += ["💡 今日一句话", "   " + _plain(lead), ""]

    for heading, blocks in sections:
        out += _heading(heading)
        for kind, lines in blocks:
            if kind == "ul":
                out += ["  • " + _plain(item) for item in lines]
            else:
                out.append(_plain("\n".join(lines)))
        out.append("")

    if snapshot and snapshot.trends:
        out += _heading("趋势排行")
        for t in snapshot.trends[:MAX_TRENDS]:
            line = "%2d. %s" % (t.rank, one_line(t.name))
            if t.post_count is not None:
                line += "（%s）" % t.count_label
            out += [line, "    " + trend_link(t.name)]
        out.append("")

    if snapshot and snapshot.posts:
        out += _heading("热门帖子")
        for i, p in enumerate(snapshot.posts[:MAX_POSTS], 1):
            out.append("[%d] @%s" % (i, one_line(p.author) or "unknown"))
            out += ["    " + l for l in clamp_text(p.text)]
            stats = "    ♥ %s   ↻ %s" % (fmt_num(p.likes), fmt_num(p.reposts))
            out.append(stats)
            link = safe_url(p.url)
            if link:
                out.append("    查看原帖：" + link)
            out.append("")

    out += [_THIN] + footer_lines(digest, meta)
    out += ["不想再收到这类邮件？退订：" + UNSUBSCRIBE_PLACEHOLDER]
    return "\n".join(out).rstrip() + "\n"
