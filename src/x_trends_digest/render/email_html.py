"""HTML 邮件渲染：新闻简报版式，表格布局 + 仅内联 CSS，宽度不超过 600px。

兼容性约束（QQ 邮箱、Gmail、Outlook）：
- 不用 <style>/<link>/脚本/图片/flex/grid，样式全部写在元素的 style 属性里；
- 外层表格 width=100%，内层 max-width:600px，手机上自动收窄；
- Outlook（Word 渲染引擎）不认 max-width、border-radius、渐变：用 MSO 条件注释
  包一层固定 600px 的表格，其余按"圆角变直角、渐变变纯色"优雅降级；
- 按钮用"边框撑出内边距"的写法（border-width 与背景同色），Outlook 里也有体积。
所有来自抓取数据和模型输出的文本都经过 html.escape，链接只放行 http/https。
"""

import re
from html import escape
from typing import List, Optional

from ..models import Digest, Post, Snapshot, Trend
from ._common import (
    FALLBACK_NOTICE,
    LEAD_MAX_CHARS,
    MAX_POSTS,
    MAX_TRENDS,
    TOP_TRENDS,
    UNSUBSCRIBE_PLACEHOLDER,
    Meta,
    avatar_color,
    clamp_text,
    fmt_num,
    footer_lines,
    initial,
    one_line,
    safe_url,
    section_emoji,
    trend_link,
)
from ._md import parse_sections, split_lead

FONT = "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif"

# 配色：深海蓝头图 + 单一强调色，其余用 slate 灰阶，保证层级清楚
INK = "#0f172a"  # 标题
BODY = "#334155"  # 正文
MUTED = "#64748b"  # 次要信息
LINE = "#e2e8f0"  # 分割线、卡片边框
BG = "#eef2f7"  # 邮件背景
CARD_BG = "#f8fafc"  # 卡片底色
ACCENT = "#2563eb"  # 强调色（链接、按钮、小标题条）
ACCENT_BG = "#eff6ff"
HEAD_A = "#0f172a"  # 头图渐变起止色，同时也是 Outlook 下的纯色回退
HEAD_B = "#1e3a8a"
GOLD, SILVER, BRONZE = "#f59e0b", "#94a3b8", "#c2410c"
RED, GREEN = "#e11d48", "#059669"

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
_PREHEADER_PAD = "&nbsp;&zwnj;" * 40  # 把预览文字后面的正文挤出收件箱列表


def _e(text: str) -> str:
    return escape(text, quote=True)


def _inline(text: str) -> str:
    """先整体转义，再把 **加粗** 换成 <strong>；转义后的文本里不会再有可注入的标签。"""
    return _BOLD.sub(r"<strong>\1</strong>", _e(text))


def _link(url: str, label_html: str, color: str = ACCENT, extra: str = "") -> str:
    return (f'<a href="{_e(url)}" style="color:{color};text-decoration:none;{extra}">'
            f"{label_html}</a>")


def _row(inner: str, pad: str) -> str:
    return f'<tr><td style="padding:{pad};font-family:{FONT};">{inner}</td></tr>'


def _badge(text: str, size: int, bg: str, font_size: int) -> str:
    """编号徽章/头像占位：圆形（Outlook 下是方块）。"""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="{size}" height="{size}" align="center" valign="middle" bgcolor="{bg}" '
        f'style="width:{size}px;height:{size}px;background-color:{bg};border-radius:{size // 2}px;'
        f'font-family:{FONT};font-size:{font_size}px;line-height:{size}px;font-weight:bold;'
        f'color:#ffffff;text-align:center;">{_e(text)}</td></tr></table>'
    )


# ---------------------------------------------------------------- 头图和导语
def _header(meta: Meta) -> str:
    return (
        f'<tr><td bgcolor="{HEAD_A}" style="background-color:{HEAD_A};'
        f"background-image:linear-gradient(135deg,{HEAD_A} 0%,{HEAD_B} 100%);"
        f'border-radius:12px 12px 0 0;padding:30px 28px 28px 28px;font-family:{FONT};">'
        f'<div style="font-size:12px;line-height:18px;font-weight:bold;letter-spacing:2px;'
        f'color:#93c5fd;">X TRENDS DIGEST</div>'
        f'<div style="font-size:28px;line-height:36px;font-weight:bold;color:#ffffff;'
        f'padding-top:8px;">{_e(meta.title)}</div>'
        f'<div style="font-size:14px;line-height:22px;color:#cbd5e1;padding-top:10px;">'
        f"{_e(meta.date_label)} &nbsp;·&nbsp; {_e(meta.weekday)}</div>"
        f'<div style="font-size:13px;line-height:20px;color:#94a3b8;padding-top:2px;">'
        f"{_e(meta.subtitle)}</div></td></tr>"
    )


def _notice() -> str:
    return _row(
        f'<div style="font-size:14px;line-height:22px;color:#92400e;background-color:#fffbeb;'
        f'border:1px solid #fde68a;border-radius:8px;padding:10px 14px;">'
        f"⚠️ <strong>{_e(FALLBACK_NOTICE)}</strong>：以下为根据抓取数据自动生成的简要摘要，"
        f"未经 AI 整理。</div>",
        "20px 24px 0 24px",
    )


def _lead(lead: str) -> str:
    return _row(
        f'<table {_TABLE}><tr>'
        f'<td bgcolor="{ACCENT_BG}" style="background-color:{ACCENT_BG};'
        f"border-left:4px solid {ACCENT};border-radius:0 8px 8px 0;padding:16px 18px;"
        f'font-family:{FONT};">'
        f'<div style="font-size:12px;line-height:18px;font-weight:bold;color:{ACCENT};">'
        f"💡 今日一句话</div>"
        f'<div style="font-size:17px;line-height:28px;font-weight:bold;color:{INK};'
        f'padding-top:4px;">{_inline(lead)}</div></td></tr></table>',
        "22px 24px 2px 24px",
    )


# ---------------------------------------------------------------- 摘要分节
def _section_title(title: str) -> str:
    emoji = section_emoji(title)
    label = emoji + " " if emoji else ""
    bar = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="28" height="3" bgcolor="{ACCENT}" style="width:28px;height:3px;'
        f'background-color:{ACCENT};font-size:1px;line-height:3px;">&nbsp;</td></tr></table>'
    )
    return _row(
        f'<div style="font-size:18px;line-height:26px;font-weight:bold;color:{INK};'
        f'padding-bottom:6px;">{label}{_inline(title)}</div>{bar}',
        "28px 24px 12px 24px",
    )


def _summary_rows(sections) -> List[str]:
    rows = []  # type: List[str]
    for heading, blocks in sections:
        rows.append(_section_title(heading))
        for kind, lines in blocks:
            if kind == "ul":
                items = "".join(
                    f'<tr><td valign="top" width="18" style="width:18px;font-family:{FONT};'
                    f'font-size:15px;line-height:26px;color:{ACCENT};">&#9679;</td>'
                    f'<td style="font-family:{FONT};font-size:15px;line-height:26px;color:{BODY};'
                    f'padding-bottom:8px;">{_inline(item)}</td></tr>'
                    for item in lines
                )
                rows.append(_row(f"<table {_TABLE}>{items}</table>", "0 24px 0 24px"))
            else:
                text = "<br>".join(_inline(l) for l in lines)
                rows.append(_row(
                    f'<div style="font-size:15px;line-height:26px;color:{BODY};">{text}</div>',
                    "0 24px 8px 24px"))
    return rows


# ---------------------------------------------------------------- 趋势排行
def _count_html(t: Trend, size: int) -> str:
    if t.post_count is None:  # 数量缺失时不显示
        return ""
    return (f'<div style="font-size:{size}px;line-height:{size + 5}px;color:{MUTED};">'
            f"{_e(t.count_label)}</div>")


def _trend_name(t: Trend, size: int) -> str:
    # 只在一个词本身放不下时才断词（不用 break-all，否则英文单词会被拦腰截断）；
    # 箭头用不换行空格接在最后一个词后面，避免它单独占一行
    return _link(
        trend_link(t.name),
        f'{_e(one_line(t.name))}&nbsp;<span style="color:{ACCENT};">&#8599;</span>',
        INK, f"font-size:{size}px;line-height:{size + 7}px;font-weight:bold;"
             "word-wrap:break-word;overflow-wrap:break-word;word-break:break-word;")


def _top_trend(t: Trend, idx: int) -> str:
    color = (GOLD, SILVER, BRONZE)[idx]
    bg, border = ("#fffbeb", "#fde68a") if idx == 0 else (CARD_BG, LINE)
    return (
        f'<tr><td style="padding-bottom:8px;">'
        f'<table {_TABLE} style="background-color:{bg};border:1px solid {border};border-radius:8px;">'
        f'<tr><td width="56" valign="middle" style="width:56px;padding:12px 0 12px 14px;">'
        f"{_badge(str(t.rank), 36, color, 16)}</td>"
        f'<td valign="middle" style="padding:12px 14px 12px 8px;font-family:{FONT};">'
        f"{_trend_name(t, 16)}{_count_html(t, 13)}</td></tr></table></td></tr>"
    )


def _compact_cell(t: Optional[Trend], left: bool) -> str:
    pad = "0 5px 8px 0" if left else "0 0 8px 5px"
    if t is None:
        return f'<td width="50%" style="width:50%;padding:{pad};">&nbsp;</td>'
    return (
        f'<td width="50%" valign="top" style="width:50%;padding:{pad};">'
        f'<table {_TABLE} style="border-bottom:1px solid {LINE};"><tr>'
        f'<td width="32" valign="top" style="width:32px;padding:6px 0 8px 0;">'
        f'{_badge(str(t.rank), 24, "#94a3b8", 12)}</td>'
        f'<td valign="top" style="padding:4px 0 8px 6px;font-family:{FONT};">'
        f"{_trend_name(t, 14)}{_count_html(t, 12)}</td></tr></table></td>"
    )


def _trend_rows(snapshot: Snapshot) -> List[str]:
    shown = snapshot.trends[:MAX_TRENDS]
    if not shown:
        return []
    top, rest = shown[:TOP_TRENDS], shown[TOP_TRENDS:]
    body = "".join(_top_trend(t, i) for i, t in enumerate(top))
    out = [_section_title("趋势排行"), _row(f"<table {_TABLE}>{body}</table>", "0 24px 4px 24px")]
    if rest:  # 第 4 名起用两列紧凑布局
        pairs = "".join(
            "<tr>%s%s</tr>" % (
                _compact_cell(rest[i], True),
                _compact_cell(rest[i + 1] if i + 1 < len(rest) else None, False))
            for i in range(0, len(rest), 2)
        )
        out.append(_row(f"<table {_TABLE}>{pairs}</table>", "4px 24px 0 24px"))
    return out


# ---------------------------------------------------------------- 热帖卡片
def _button(url: str) -> str:
    return (
        f'<a href="{_e(url)}" style="display:inline-block;background-color:{ACCENT};'
        f"border-style:solid;border-color:{ACCENT};border-width:8px 16px;border-radius:6px;"
        f"color:#ffffff;font-family:{FONT};font-size:13px;line-height:16px;font-weight:bold;"
        f'text-decoration:none;">查看原帖</a>'
    )


def _post_card(p: Post, idx: int) -> str:
    handle = one_line(p.author) or "unknown"
    text = "<br>".join(_e(l) for l in clamp_text(p.text))
    url = safe_url(p.url)
    stats = (f'<span style="color:{RED};">&hearts;</span> {fmt_num(p.likes)}'
             f'&nbsp;&nbsp;&nbsp;<span style="color:{GREEN};">&#8635;</span> {fmt_num(p.reposts)}')
    button = f'<td align="right" valign="middle">{_button(url)}</td>' if url else ""
    return (
        f'<tr><td style="padding-bottom:12px;">'
        f'<table {_TABLE} style="background-color:#ffffff;border:1px solid {LINE};border-radius:10px;">'
        f'<tr><td style="padding:14px 16px 0 16px;font-family:{FONT};">'
        # 头像占位（首字母圆圈）+ @handle
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="46" valign="middle" style="width:46px;">'
        f"{_badge(initial(handle), 36, avatar_color(handle), 16)}</td>"
        f'<td valign="middle" style="font-family:{FONT};">'
        f'<div style="font-size:15px;line-height:20px;font-weight:bold;color:{INK};">'
        f"@{_e(handle)}</div>"
        f'<div style="font-size:12px;line-height:18px;color:{MUTED};">热帖 No.{idx}</div>'
        f"</td></tr></table></td></tr>"
        # 正文：最多 4 行（先按字数估算截断，max-height 和 line-clamp 兜底）
        f'<tr><td style="padding:10px 16px 0 16px;font-family:{FONT};">'
        f'<div style="font-size:15px;line-height:23px;color:{BODY};max-height:92px;'
        f"overflow:hidden;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;"
        f'word-break:break-word;">{text}</div></td></tr>'
        # 数据 + 按钮
        f'<tr><td style="padding:12px 16px 14px 16px;font-family:{FONT};">'
        f'<table {_TABLE}><tr>'
        f'<td valign="middle" style="font-family:{FONT};font-size:14px;line-height:20px;'
        f'color:{MUTED};">{stats}</td>{button}</tr></table></td></tr></table></td></tr>'
    )


def _post_rows(snapshot: Snapshot) -> List[str]:
    shown = snapshot.posts[:MAX_POSTS]
    if not shown:
        return []
    cards = "".join(_post_card(p, i + 1) for i, p in enumerate(shown))
    return [_section_title("热门帖子"), _row(f"<table {_TABLE}>{cards}</table>", "0 24px 4px 24px")]


# ---------------------------------------------------------------- 页脚和整页
def _footer(digest: Digest, meta: Meta) -> str:
    lines = "".join(
        f'<div style="font-size:12px;line-height:19px;color:{MUTED};">{_e(l)}</div>'
        for l in footer_lines(digest, meta)
    )
    return (
        f'<tr><td bgcolor="{CARD_BG}" align="center" style="background-color:{CARD_BG};'
        f"border-top:1px solid {LINE};border-radius:0 0 12px 12px;padding:24px 24px 28px 24px;"
        f'font-family:{FONT};text-align:center;">'
        f'<div style="font-size:13px;line-height:20px;font-weight:bold;color:{INK};'
        f'padding-bottom:6px;">X Trends Digest</div>{lines}'
        f'<div style="font-size:12px;line-height:19px;color:{MUTED};padding-top:10px;">'
        f"不想再收到这类邮件？{_link(UNSUBSCRIBE_PLACEHOLDER, '退订', ACCENT, 'text-decoration:underline;')}"
        f"</div></td></tr>"
    )


def render_html(digest: Digest, snapshot: Optional[Snapshot], meta: Meta) -> str:
    lead, sections = split_lead(parse_sections(digest.body), LEAD_MAX_CHARS)
    rows = [_header(meta)]
    if digest.fallback:
        rows.append(_notice())
    if lead:
        rows.append(_lead(lead))
    rows += _summary_rows(sections)
    if snapshot:
        rows += _trend_rows(snapshot)
        rows += _post_rows(snapshot)
    rows.append(_footer(digest, meta))

    preheader = lead or "%s · %s" % (meta.title, meta.date_label)
    title = "%s · %s" % (meta.title, meta.date_label)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN" xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office">\n'
        '<head><meta charset="utf-8">'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        f"<title>{_e(title)}</title>\n"
        "<!--[if mso]><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch>"
        "</o:OfficeDocumentSettings></xml><![endif]-->\n"
        "</head>\n"
        f'<body style="margin:0;padding:0;background-color:{BG};-webkit-text-size-adjust:100%;">\n'
        # 预览文字（收件箱列表里显示在标题后面），正文里不可见
        '<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;'
        f'opacity:0;overflow:hidden;mso-hide:all;color:{BG};">{_e(preheader)}{_PREHEADER_PAD}</div>\n'
        f'<table {_TABLE} style="background-color:{BG};"><tr>'
        '<td align="center" style="padding:20px 10px;">\n'
        # Outlook 不认 max-width：给它一个固定 600px 的外壳
        '<!--[if mso]><table role="presentation" width="600" align="center" cellpadding="0" '
        'cellspacing="0" border="0"><tr><td><![endif]-->\n'
        f'<table {_TABLE} style="width:100%;max-width:600px;background-color:#ffffff;'
        'border-radius:12px;">\n'
        + "\n".join(rows) +
        "\n</table>\n"
        "<!--[if mso]></td></tr></table><![endif]-->\n"
        "</td></tr></table>\n</body></html>\n"
    )
