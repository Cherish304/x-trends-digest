"""纯文本备用版本：给不显示 HTML 的客户端用。"""

import re
from typing import List, Optional

from ..models import Digest, Snapshot
from ._common import (
    FALLBACK_NOTICE,
    MAX_POSTS,
    MAX_TRENDS,
    one_line,
    safe_url,
    trend_link,
    truncate,
)
from ._md import parse_sections

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def render_text(
    digest: Digest, snapshot: Optional[Snapshot], title: str, date_label: str
) -> str:
    out = ["%s · %s" % (title, date_label), "=" * 30, ""]  # type: List[str]
    if digest.fallback:
        out += ["【%s】以下为根据抓取数据自动生成的简要摘要。" % FALLBACK_NOTICE, ""]

    for heading, blocks in parse_sections(digest.body):
        out.append("## " + _BOLD.sub(r"\1", heading))
        for kind, lines in blocks:
            if kind == "ul":
                out += ["- " + _BOLD.sub(r"\1", item) for item in lines]
            else:
                out.append(_BOLD.sub(r"\1", "\n".join(lines)))
        out.append("")

    if snapshot and snapshot.trends:
        out.append("## 趋势排行")
        for t in snapshot.trends[:MAX_TRENDS]:
            line = "%d. %s" % (t.rank, one_line(t.name))
            if t.post_count is not None:
                line += "（%s）" % t.count_label
            out += [line, "   " + trend_link(t.name)]
        out.append("")

    if snapshot and snapshot.posts:
        out.append("## 热门帖子")
        for p in snapshot.posts[:MAX_POSTS]:
            out.append("@%s：%s" % (one_line(p.author), truncate(p.text)))
            stats = "   点赞 {:,} · 转发 {:,}".format(p.likes, p.reposts)
            link = safe_url(p.url)
            out.append(stats + (" · " + link if link else ""))
            out.append("")

    out += [
        "--",
        "本邮件由 x-trends-digest 自动生成，数据来自 X，内容未经人工核实，仅供参考。",
    ]
    return "\n".join(out).rstrip() + "\n"
