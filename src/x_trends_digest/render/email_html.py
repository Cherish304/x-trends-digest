"""HTML 邮件渲染：表格布局 + 仅内联 CSS，宽度不超过 600px，手机上自动收窄。

兼容性约束（QQ 邮箱、Gmail）：不用 <style>/<link>/脚本，不用 flex/grid，
所有样式写在元素的 style 属性里；外层表格 width=100%，内层 max-width:600px。
所有来自抓取数据和模型输出的文本都经过 html.escape，链接只放行 http/https。
"""

import re
from html import escape
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

FONT = "-apple-system,'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif"
INK = "#1f2933"
MUTED = "#6b7785"
LINE = "#e4e7eb"
ACCENT = "#1d6fd1"
BG = "#f3f5f7"

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _e(text: str) -> str:
    return escape(text, quote=True)


def _inline(text: str) -> str:
    """先整体转义，再把 **加粗** 换成 <strong>；转义后的文本里不会再有可注入的标签。"""
    return _BOLD.sub(r"<strong>\1</strong>", _e(text))


def _link(url: str, label_html: str, extra_style: str = "") -> str:
    return '<a href="%s" style="color:%s;text-decoration:none;%s">%s</a>' % (
        _e(url), ACCENT, extra_style, label_html)


def _section_title(text_html: str) -> str:
    return (
        '<tr><td style="padding:22px 24px 8px 24px;font-family:%s;font-size:17px;'
        'line-height:24px;font-weight:bold;color:%s;border-top:1px solid %s;">%s</td></tr>'
        % (FONT, INK, LINE, text_html)
    )


def _row(inner: str, pad: str = "0 24px 8px 24px") -> str:
    return '<tr><td style="padding:%s;">%s</td></tr>' % (pad, inner)


def _summary_rows(digest: Digest) -> List[str]:
    rows = []  # type: List[str]
    for heading, blocks in parse_sections(digest.body):
        rows.append(_section_title(_inline(heading)))
        for kind, lines in blocks:
            if kind == "ul":
                items = "".join(
                    '<tr><td valign="top" width="16" style="font-family:%s;font-size:15px;'
                    'line-height:24px;color:%s;">&bull;</td>'
                    '<td style="font-family:%s;font-size:15px;line-height:24px;color:%s;'
                    'padding-bottom:6px;">%s</td></tr>'
                    % (FONT, ACCENT, FONT, INK, _inline(item))
                    for item in lines
                )
                rows.append(_row(
                    '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
                    'border="0">%s</table>' % items))
            else:
                rows.append(_row(
                    '<div style="font-family:%s;font-size:15px;line-height:24px;color:%s;">%s</div>'
                    % (FONT, INK, "<br>".join(_inline(l) for l in lines))))
    return rows


def _trend_rows(snapshot: Snapshot) -> List[str]:
    if not snapshot.trends:
        return []
    cells = []
    for t in snapshot.trends[:MAX_TRENDS]:
        name = _link(trend_link(t.name), _e(one_line(t.name)), "font-weight:bold;")
        count = ""
        if t.post_count is not None:  # 数量缺失时不显示
            count = ('<div style="font-size:13px;line-height:18px;color:%s;">%s</div>'
                     % (MUTED, _e(t.count_label)))
        cells.append(
            '<tr><td valign="top" width="32" style="padding:8px 0;border-bottom:1px solid %s;'
            'font-family:%s;font-size:16px;line-height:22px;font-weight:bold;color:%s;">%d</td>'
            '<td valign="top" style="padding:8px 0;border-bottom:1px solid %s;font-family:%s;'
            'font-size:15px;line-height:22px;color:%s;word-break:break-all;">%s%s</td></tr>'
            % (LINE, FONT, ACCENT, t.rank, LINE, FONT, INK, name, count)
        )
    table = ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
             'border="0">%s</table>' % "".join(cells))
    return [_section_title("趋势排行"), _row(table)]


def _post_cards(snapshot: Snapshot) -> List[str]:
    if not snapshot.posts:
        return []
    rows = [_section_title("热门帖子")]
    for p in snapshot.posts[:MAX_POSTS]:
        url = safe_url(p.url)
        origin = (" &nbsp;|&nbsp; " + _link(url, "查看原帖")) if url else ""
        card = (
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
            'style="border:1px solid %s;border-radius:6px;background-color:#ffffff;"><tr>'
            '<td style="padding:12px 14px;font-family:%s;">'
            '<div style="font-size:14px;line-height:20px;font-weight:bold;color:%s;">@%s</div>'
            '<div style="font-size:15px;line-height:23px;color:%s;padding:6px 0 8px 0;'
            'word-break:break-word;">%s</div>'
            '<div style="font-size:13px;line-height:18px;color:%s;">'
            '点赞 %s &nbsp;|&nbsp; 转发 %s%s</div></td></tr></table>'
            % (LINE, FONT, INK, _e(one_line(p.author)), INK,
               "<br>".join(_e(l) for l in truncate(p.text).splitlines()),
               MUTED, "{:,}".format(p.likes), "{:,}".format(p.reposts), origin)
        )
        rows.append(_row(card, "0 24px 10px 24px"))
    return rows


def render_html(
    digest: Digest, snapshot: Optional[Snapshot], title: str, date_label: str
) -> str:
    notice = ""
    if digest.fallback:
        notice = _row(
            '<div style="font-family:%s;font-size:14px;line-height:21px;color:#8a5a00;'
            'background-color:#fff4d6;border:1px solid #f0d58a;border-radius:6px;'
            'padding:10px 12px;"><strong>%s</strong>：以下为根据抓取数据自动生成的简要摘要，'
            '未经 AI 整理。</div>' % (FONT, _e(FALLBACK_NOTICE)),
            "16px 24px 0 24px",
        )
    body = [
        '<tr><td style="padding:24px 24px 14px 24px;font-family:%s;">'
        '<div style="font-size:22px;line-height:30px;font-weight:bold;color:%s;">%s</div>'
        '<div style="font-size:13px;line-height:20px;color:%s;">%s</div></td></tr>'
        % (FONT, INK, _e(title), MUTED, _e(date_label)),
        notice,
    ]
    body += _summary_rows(digest)
    if snapshot:
        body += _trend_rows(snapshot)
        body += _post_cards(snapshot)
    body.append(
        '<tr><td style="padding:20px 24px 24px 24px;border-top:1px solid %s;font-family:%s;'
        'font-size:12px;line-height:18px;color:%s;">本邮件由 x-trends-digest 自动生成，'
        '数据来自 X，内容未经人工核实，仅供参考。</td></tr>' % (LINE, FONT, MUTED)
    )
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>%s</title></head>\n'
        '<body style="margin:0;padding:0;background-color:%s;">\n'
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:%s;"><tr><td align="center" style="padding:12px 8px;">\n'
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%%;max-width:600px;background-color:#ffffff;border-radius:8px;">\n'
        '%s\n</table>\n</td></tr></table>\n</body></html>\n'
        % (_e("%s · %s" % (title, date_label)), BG, BG, "\n".join(r for r in body if r))
    )
