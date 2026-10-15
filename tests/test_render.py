"""邮件渲染层测试：新闻简报版式、转义、Outlook 降级、纯文本版本、render-email 命令。纯本地，无网络。"""

import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import datetime
from html.parser import HTMLParser
from unittest import mock

from x_trends_digest import cli
from x_trends_digest.models import Digest, Post, Snapshot, Trend
from x_trends_digest.render import render_email
from x_trends_digest.render._common import avatar_color, clamp_text, initial, section_emoji
from x_trends_digest.render._md import parse_sections, split_lead
from x_trends_digest.summarizers import MockSummarizer

BODY = "## 今日概览\n今天很热闹。X 上讨论集中在两件事。\n\n## 重点要点\n- 第一条 **重点**\n- 第二条\n"
NOW = datetime(2026, 10, 14, 9, 5)
UNSUB = "{{UNSUBSCRIBE_URL}}"


def snapshot():
    return Snapshot(
        trends=[Trend(1, "#Alpha Topic", 120000), Trend(2, "Beta", None), Trend(3, "A&B", 0)],
        posts=[Post("1", "alice", "第一条帖子\n第二行", 1200, 30, "https://x.com/alice/status/1")],
        fetched_at="2026-10-14T09:00:00+08:00",
    )


def big_snapshot(n_trends=8):
    return Snapshot(
        trends=[Trend(i, "话题%d" % i, i * 1000) for i in range(1, n_trends + 1)],
        posts=[Post(str(i), "user%d" % i, "正文%d" % i, i, i, "https://x.com/u/status/%d" % i)
               for i in range(1, 4)],
        fetched_at="2026-10-14T09:00:00+08:00",
    )


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs).get("href"))


def parse(html):
    c = Collector()
    c.feed(html)
    return c


def visible_text(html):
    """去掉标签、注释和隐藏的预览文字后的可见文本。"""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r'<div style="display:none.*?</div>', "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class HtmlTest(unittest.TestCase):
    def setUp(self):
        self.email = render_email(Digest("t", BODY), snapshot(), now=NOW)
        self.html = self.email.html

    # ---- 兼容性约束 ----
    def test_inline_css_only_and_table_layout(self):
        tags = parse(self.html).tags
        for banned in ("style", "link", "script", "img", "iframe", "svg"):
            self.assertNotIn(banned, tags)
        self.assertIn("table", tags)
        self.assertNotRegex(self.html, r"display\s*:\s*(flex|grid)")
        self.assertNotIn("@media", self.html)

    def test_width_capped_at_600(self):
        self.assertEqual([int(w) for w in re.findall(r"max-width:\s*(\d+)px", self.html)], [600])
        self.assertIn('name="viewport"', self.html)
        for w in re.findall(r'\bwidth="(\d+)"', self.html):
            self.assertLessEqual(int(w), 600)

    def test_outlook_fallbacks(self):
        # Outlook 不认 max-width：条件注释里给一个固定 600px 的外壳，且配对闭合
        self.assertIn("<!--[if mso]>", self.html)
        self.assertRegex(self.html, r'<!--\[if mso\]><table[^>]*width="600"')
        self.assertEqual(self.html.count("<!--[if mso]>"), self.html.count("<![endif]-->"))
        # 渐变头图有纯色回退（bgcolor 属性 + background-color）
        self.assertIn('bgcolor="#0f172a"', self.html)
        self.assertIn("linear-gradient", self.html)
        # 按钮是 <a> 加边框撑内边距，Outlook 里也有体积
        self.assertRegex(self.html, r"border-width:8px 16px[^>]*>|border-width:8px 16px;")

    def test_font_stack(self):
        stack = "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif"
        self.assertIn(stack, self.html)
        self.assertNotIn("Helvetica", self.html)

    # ---- 顶部和导语 ----
    def test_header_brand_title_date_subtitle(self):
        self.assertIn("X TRENDS DIGEST", self.html)
        self.assertIn("X 热点日报", self.html)
        self.assertIn("2026年10月14日", self.html)
        self.assertIn("周三", self.html)  # 2026-10-14 是周三
        self.assertIn("每日 X 热点速览", self.html)
        self.assertEqual(self.email.subject, "X 热点日报 · 2026年10月14日")

    def test_lead_card_takes_first_sentence_once(self):
        text = visible_text(self.html)
        self.assertIn("今日一句话", text)
        self.assertEqual(text.count("今天很热闹。"), 1)  # 导语里一次，正文里不再重复
        self.assertIn("X 上讨论集中在两件事。", text)  # 概览剩余部分仍保留

    def test_preheader_is_hidden_lead(self):
        m = re.search(r'<div style="display:none[^>]*>(.*?)</div>', self.html, re.S)
        self.assertTrue(m.group(1).startswith("今天很热闹。"))
        self.assertIn("mso-hide:all", m.group(0))

    # ---- 摘要分节 ----
    def test_sections_have_emoji_and_titles(self):
        for s in ("📌 重点要点", "🔥 趋势排行", "💬 热门帖子"):
            self.assertIn(s, self.html)
        self.assertIn("<strong>重点</strong>", self.html)

    # ---- 趋势 ----
    def test_top3_badges_distinct_and_links(self):
        for color in ("#f59e0b", "#94a3b8", "#c2410c"):  # 金银铜
            self.assertRegex(self.html, r'bgcolor="%s"[^>]*>[123]</td>' % color)
        links = parse(self.html).links
        self.assertIn("https://x.com/search?q=%23Alpha%20Topic", links)
        self.assertIn("https://x.com/search?q=Beta", links)
        self.assertIn("https://x.com/search?q=A%26B", links)

    def test_missing_count_hidden_but_zero_shown(self):
        self.assertIn("120,000 帖", self.html)
        self.assertIn("0 帖", self.html)
        beta = self.html.split("https://x.com/search?q=Beta")[1].split("</table>")[0]
        self.assertNotIn("帖", beta)

    def test_rank4_plus_uses_two_column_compact_layout(self):
        html = render_email(Digest("t", BODY), big_snapshot(8), now=NOW).html
        compact = html.split("话题3")[1]  # 第 4 名起
        pairs = re.findall(r'<td width="50%"', compact)
        self.assertEqual(len(pairs), 6)  # 第 4~8 名 5 条 -> 3 行，每行 2 格（最后一格补空）
        self.assertIn("话题8", html)

    def test_trend_names_do_not_break_words_mid_word(self):
        # 手机宽度下 break-all 会把 "Launch" 拦腰拆成 "Lau / nch"
        html = render_email(Digest("t", BODY), big_snapshot(6), now=NOW).html
        self.assertNotIn("break-all", html)
        self.assertIn("overflow-wrap:break-word", html)
        self.assertIn("话题1&nbsp;<span", html)  # 箭头不会单独换行

    def test_trends_capped_at_10(self):
        html = render_email(Digest("t", BODY), big_snapshot(15), now=NOW).html
        self.assertIn("话题10", html)
        self.assertNotIn("话题11", html)

    # ---- 热帖卡片 ----
    def test_post_card_parts(self):
        text = visible_text(self.html)
        self.assertIn("@alice", text)
        self.assertIn(">A</td>", self.html)  # 首字母头像
        self.assertIn("1,200", text)
        self.assertIn("30", text)
        self.assertIn("&hearts;", self.html)  # 点赞图标
        self.assertIn("&#8635;", self.html)  # 转发图标
        self.assertIn("第一条帖子<br>第二行", self.html)
        link = re.search(r'<a href="([^"]+)"[^>]*>查看原帖</a>', self.html)
        self.assertEqual(link.group(1), "https://x.com/alice/status/1")

    def test_post_without_url_has_no_button(self):
        snap = Snapshot(posts=[Post("1", "bob", "hi", 1, 1, "")])
        html = render_email(Digest("t", BODY), snap, now=NOW).html
        self.assertNotIn("查看原帖", html)

    def test_post_body_clamped_to_4_lines(self):
        long = "字" * 400
        snap = Snapshot(posts=[Post("1", "bob", long, 1, 1, "")])
        html = render_email(Digest("t", BODY), snap, now=NOW).html
        shown = re.search(r'-webkit-line-clamp:4[^>]*>(.*?)</div>', html, re.S).group(1)
        self.assertTrue(shown.endswith("…"))
        self.assertEqual(shown.count("字"), 4 * 28 - 1)  # 占满 4 行，而不是被砍成 1 行
        self.assertIn("max-height:92px", html)  # 客户端不认估算时的兜底

    # ---- 页脚 ----
    def test_footer_source_time_unsubscribe(self):
        footer = self.html.rsplit("<tr>", 1)[1]
        self.assertIn("数据来源：X", footer)
        self.assertIn("数据抓取于 2026-10-14 09:00", footer)
        self.assertIn("邮件生成于 2026-10-14 09:05", footer)
        self.assertIn("摘要由 AI 模型生成", footer)
        self.assertIn('href="%s"' % UNSUB, footer)
        self.assertIn("退订", footer)

    def test_no_notice_when_not_fallback(self):
        for part in (self.html, self.email.text, self.email.subject):
            self.assertNotIn("AI 摘要暂不可用", part)

    def test_empty_snapshot_still_renders(self):
        html = render_email(Digest("t", BODY), Snapshot(), now=NOW).html
        # 页脚文案里也有"热门帖子"字样，所以按带 emoji 的板块标题判断
        self.assertNotIn("🔥 趋势排行", html)
        self.assertNotIn("💬 热门帖子", html)
        self.assertIn("退订", html)


class EscapeTest(unittest.TestCase):
    EVIL = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'

    def render(self):
        snap = Snapshot(
            trends=[Trend(1, self.EVIL, 5, "javascript:alert(1)")],
            posts=[Post("1", self.EVIL, self.EVIL, 1, 1, "javascript:alert(3)"),
                   Post("2", "bob", "ok", 1, 1, 'https://x.com/a" onmouseover="alert(4)')],
        )
        return render_email(
            Digest("t", "## " + self.EVIL + "\n" + self.EVIL + "。\n- " + self.EVIL), snap, now=NOW)

    def test_html_has_no_injected_tags(self):
        email = self.render()
        c = parse(email.html)
        self.assertNotIn("script", c.tags)
        self.assertNotIn("img", c.tags)
        self.assertNotIn("<script", email.html)
        self.assertNotIn("onerror=alert(2)>", email.html.replace("&gt;", ""))
        self.assertIn("&lt;script&gt;", email.html)

    def test_dangerous_urls_dropped(self):
        html = self.render().html
        self.assertNotIn("javascript:", html)
        self.assertNotIn("onmouseover", html)  # 含空白的 URL 被整个丢弃
        self.assertNotIn("查看原帖", html)  # 两条帖子的链接都不安全，所以没有按钮
        for href in parse(html).links:
            self.assertTrue(href.startswith("https://x.com/search?q=") or href == UNSUB, href)

    def test_text_version_is_plain(self):
        text = self.render().text
        self.assertNotIn("javascript:", text)
        self.assertIn("https://x.com/search?q=", text)


class TextTest(unittest.TestCase):
    def setUp(self):
        self.text = render_email(Digest("t", BODY), snapshot(), now=NOW).text

    def test_layout(self):
        t = self.text
        self.assertIn("X 热点日报  X TRENDS DIGEST", t)
        self.assertIn("2026年10月14日 · 周三", t)
        self.assertIn("💡 今日一句话\n   今天很热闹。", t)
        self.assertIn("📌 重点要点\n" + "-" * 36, t)
        self.assertIn("  • 第一条 重点", t)  # **加粗** 标记被去掉
        self.assertIn(" 1. #Alpha Topic（120,000 帖）", t)
        self.assertIn(" 2. Beta\n", t)  # 数量缺失：不写括号
        self.assertIn("https://x.com/search?q=%23Alpha%20Topic", t)
        self.assertIn("[1] @alice\n    第一条帖子\n    第二行", t)
        self.assertIn("♥ 1,200   ↻ 30", t)
        self.assertIn("查看原帖：https://x.com/alice/status/1", t)

    def test_footer_matches_html(self):
        for s in ("数据来源：X", "数据抓取于 2026-10-14 09:00", "邮件生成于 2026-10-14 09:05",
                  "退订：" + UNSUB):
            self.assertIn(s, self.text)

    def test_digest_only(self):
        email = render_email(Digest("t", "## A\nhello"), now=NOW)
        self.assertIn("hello", email.html)
        self.assertNotIn("趋势排行", email.html)
        self.assertNotIn("趋势排行", email.text)

    def test_plain_has_no_markup(self):
        self.assertNotRegex(self.text, r"<[a-z/]")
        self.assertNotIn("**", self.text)


class FallbackNoticeTest(unittest.TestCase):
    def test_notice_in_all_places(self):
        d = Digest("t", BODY, fallback=True, fallback_reason="SECRET-DETAIL")
        email = render_email(d, snapshot(), now=NOW)
        for part in (email.subject, email.html, email.text):
            self.assertIn("AI 摘要暂不可用", part)
        self.assertIn("摘要由规则自动生成", email.html)
        self.assertNotIn("SECRET-DETAIL", email.html + email.text + email.subject)
        # 提示条在头图之后、导语之前
        self.assertLess(email.html.index("X 热点日报"), email.html.index("⚠️"))
        self.assertLess(email.html.index("⚠️"), email.html.index("今日一句话"))


class HelpersTest(unittest.TestCase):
    def test_clamp_text(self):
        self.assertEqual(clamp_text("短文"), ["短文"])
        self.assertEqual(clamp_text("a\n\nb"), ["a", "b"])  # 空行丢弃
        out = clamp_text("字" * 500)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("…"))
        # 一段长文本应该正好占满 4 行（每行 28 个全角字），…占最后一格：4*28-1 个字 + …
        self.assertEqual(len(out[0]), 4 * 28)
        self.assertEqual(out[0].count("字"), 4 * 28 - 1)
        many = clamp_text("\n".join("行%d" % i for i in range(10)))
        self.assertEqual(len(many), 4)
        self.assertTrue(many[-1].endswith("…"))

    def test_clamp_counts_latin_as_narrower(self):
        out = clamp_text("a" * 100)  # 拉丁字符更窄：一行能放更多
        self.assertGreater(len(out[0]), 28 - 1)

    def test_initial_and_color(self):
        self.assertEqual(initial("alice"), "A")
        self.assertEqual(initial("@bob"), "B")
        self.assertEqual(initial("张三"), "张")
        self.assertEqual(initial("__"), "?")
        self.assertEqual(avatar_color("alice"), avatar_color("alice"))  # 稳定，不随进程变

    def test_section_emoji(self):
        self.assertEqual(section_emoji("今日概览"), "📰")
        self.assertEqual(section_emoji("重点要点"), "📌")
        self.assertEqual(section_emoji("值得关注"), "👀")
        self.assertEqual(section_emoji("其他"), "📝")
        self.assertEqual(section_emoji("🚀 发布"), "")  # 标题自带 emoji 时不重复


class MarkdownTest(unittest.TestCase):
    def test_parse(self):
        secs = parse_sections("前言\n\n## A\n- x\n- y\n段落\n\n## B\n1. one\n2) two\n---\n")
        self.assertEqual([s[0] for s in secs], ["摘要", "A", "B"])
        self.assertEqual(secs[1][1], [("ul", ["x", "y"]), ("p", ["段落"])])
        self.assertEqual(secs[2][1], [("ul", ["one", "two"])])

    def test_empty(self):
        self.assertEqual(parse_sections(""), [])

    def test_split_lead_removes_sentence_from_body(self):
        lead, rest = split_lead(parse_sections("## 概览\n第一句。第二句。\n## 要点\n- a"))
        self.assertEqual(lead, "第一句。")
        self.assertEqual(rest[0], ("概览", [("p", ["第二句。"])]))
        self.assertEqual(rest[1][0], "要点")

    def test_split_lead_drops_section_when_only_sentence(self):
        lead, rest = split_lead(parse_sections("## 概览\n只有一句。\n## 要点\n- a"))
        self.assertEqual(lead, "只有一句。")
        self.assertEqual([s[0] for s in rest], ["要点"])

    def test_split_lead_from_bullets_and_bold(self):
        lead, rest = split_lead(parse_sections("## 要点\n- **加粗**的第一条\n- 第二条"))
        self.assertEqual(lead, "加粗的第一条")
        self.assertEqual(rest, [("要点", [("ul", ["第二条"])])])

    def test_split_lead_too_long_is_truncated_not_removed(self):
        body = "## 概览\n" + "长" * 200
        lead, rest = split_lead(parse_sections(body), max_chars=90)
        self.assertEqual(len(lead), 90)
        self.assertTrue(lead.endswith("…"))
        self.assertEqual(rest, parse_sections(body))

    def test_split_lead_empty(self):
        self.assertEqual(split_lead([]), ("", []))


class RenderCommandTest(unittest.TestCase):
    def test_render_email_writes_exactly_two_files(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(out):
            rc = cli.main(["--env-file", os.path.join(d, "none.env"),
                           "render-email", "--out-dir", d, "--name", "mail"])
            names = sorted(os.listdir(d))
            with open(os.path.join(d, "mail.html"), encoding="utf-8") as f:
                html = f.read()
            with open(os.path.join(d, "mail.txt"), encoding="utf-8") as f:
                text = f.read()
        self.assertEqual(rc, 0)
        self.assertEqual(names, ["mail.html", "mail.txt"])
        self.assertIn("#MockTopicA", html)
        self.assertIn("#MockTopicA", text)
        self.assertIn("mail.html", out.getvalue())

    def test_mock_summarizer_still_renders(self):
        digest = MockSummarizer().summarize(snapshot())
        self.assertIn("Alpha", render_email(digest, snapshot(), now=NOW).html)


class ExamplePreviewTest(unittest.TestCase):
    """examples/preview.html 必须和当前渲染器同步，样例改了或渲染器改了都要重新生成。"""

    def test_preview_in_sync(self):
        from x_trends_digest.fetchers import JsonFileFetcher
        from x_trends_digest.render import preview

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "examples", "preview.html")
        if not os.path.exists(path):
            self.skipTest("examples/preview.html 尚未生成")
        expected = preview.build_preview(JsonFileFetcher(os.path.join(root, "examples", "snapshot.json")))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), expected.html)
        with open(path[:-5] + ".txt", encoding="utf-8") as f:
            self.assertEqual(f.read(), expected.text)


if __name__ == "__main__":
    unittest.main()
