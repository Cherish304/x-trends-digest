"""邮件渲染层测试：HTML 结构、转义、纯文本版本、render-email 命令。纯本地，无网络。"""

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
from x_trends_digest.render._md import parse_sections
from x_trends_digest.summarizers import MockSummarizer

BODY = "## 今日概览\n今天很热闹。\n\n## 重点要点\n- 第一条 **重点**\n- 第二条\n"
NOW = datetime(2026, 10, 14, 9, 0)


def snapshot():
    return Snapshot(
        trends=[Trend(1, "#Alpha Topic", 120000), Trend(2, "Beta", None), Trend(3, "A&B", 0)],
        posts=[Post("1", "alice", "第一条帖子\n第二行", 1200, 30, "https://x.com/alice/status/1")],
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


class HtmlTest(unittest.TestCase):
    def setUp(self):
        self.email = render_email(Digest("t", BODY), snapshot(), now=NOW)
        self.html = self.email.html

    def test_inline_css_only_and_table_layout(self):
        tags = parse(self.html).tags
        for banned in ("style", "link", "script", "img", "iframe"):
            self.assertNotIn(banned, tags)
        self.assertIn("table", tags)
        self.assertNotRegex(self.html, r"display\s*:\s*(flex|grid)")
        self.assertNotIn("@media", self.html)

    def test_width_capped_at_600(self):
        widths = [int(w) for w in re.findall(r"max-width:\s*(\d+)px", self.html)]
        self.assertEqual(widths, [600])
        self.assertIn('name="viewport"', self.html)
        for w in re.findall(r'\bwidth="(\d+)"', self.html):
            self.assertLessEqual(int(w), 600)

    def test_sections_title_and_date(self):
        self.assertIn("X 热点日报", self.html)
        self.assertIn("2026年10月14日", self.html)
        for s in ("今日概览", "重点要点", "趋势排行", "热门帖子"):
            self.assertIn(s, self.html)
        self.assertIn("<strong>重点</strong>", self.html)
        self.assertEqual(self.email.subject, "X 热点日报 · 2026年10月14日")

    def test_trend_links_and_missing_count(self):
        links = parse(self.html).links
        self.assertIn("https://x.com/search?q=%23Alpha%20Topic", links)
        self.assertIn("https://x.com/search?q=Beta", links)
        self.assertIn("120,000 帖", self.html)
        self.assertIn("0 帖", self.html)  # 真实的 0 要显示
        # Beta 的数量是 None：它所在的单元格里不能出现"帖"
        beta_cell = self.html.split("Beta</a>")[1].split("</td>")[0]
        self.assertNotIn("帖", beta_cell)

    def test_post_card(self):
        self.assertIn("@alice", self.html)
        self.assertIn("第一条帖子<br>第二行", self.html)
        self.assertIn("点赞 1,200", self.html)
        self.assertIn("转发 30", self.html)
        self.assertIn("https://x.com/alice/status/1", parse(self.html).links)

    def test_footer(self):
        self.assertIn("自动生成", self.html.rsplit("<tr>", 1)[1])

    def test_no_notice_when_not_fallback(self):
        self.assertNotIn("AI 摘要暂不可用", self.html)
        self.assertNotIn("AI 摘要暂不可用", self.email.text)
        self.assertNotIn("AI 摘要暂不可用", self.email.subject)


class EscapeTest(unittest.TestCase):
    EVIL = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'

    def render(self):
        snap = Snapshot(
            trends=[Trend(1, self.EVIL, 5, "javascript:alert(1)")],
            posts=[Post("1", self.EVIL, self.EVIL, 1, 1, "javascript:alert(3)"),
                   Post("2", "bob", "ok", 1, 1, 'https://x.com/a" onmouseover="alert(4)')],
        )
        return render_email(Digest("t", "## " + self.EVIL + "\n- " + self.EVIL + "\n" + self.EVIL), snap)

    def test_html_has_no_injected_tags(self):
        c = parse(self.render().html)
        self.assertNotIn("script", c.tags)
        self.assertNotIn("img", c.tags)
        self.assertNotIn("<script", self.render().html)
        self.assertIn("&lt;script&gt;", self.render().html)

    def test_dangerous_urls_dropped(self):
        html = self.render().html
        self.assertNotIn("javascript:", html)
        self.assertNotIn("onmouseover", html)  # 含空白的 URL 被整个丢弃
        for href in parse(html).links:
            self.assertTrue(href.startswith("https://x.com/search?q="), href)

    def test_text_version_is_plain(self):
        text = self.render().text
        self.assertNotIn("javascript:", text)
        self.assertIn("https://x.com/search?q=", text)


class TextTest(unittest.TestCase):
    def test_text_content(self):
        text = render_email(Digest("t", BODY), snapshot(), now=NOW).text
        self.assertIn("X 热点日报 · 2026年10月14日", text)
        self.assertIn("## 今日概览", text)
        self.assertIn("- 第一条 重点", text)  # **加粗** 标记被去掉
        self.assertIn("1. #Alpha Topic（120,000 帖）", text)
        self.assertIn("2. Beta\n", text)  # 数量缺失：不写括号
        self.assertIn("https://x.com/search?q=%23Alpha%20Topic", text)
        self.assertIn("@alice：第一条帖子", text)
        self.assertIn("点赞 1,200 · 转发 30", text)
        self.assertIn("自动生成", text)

    def test_digest_only(self):
        email = render_email(Digest("t", "## A\nhello"))
        self.assertIn("hello", email.html)
        self.assertNotIn("趋势排行", email.html)
        self.assertNotIn("趋势排行", email.text)


class FallbackNoticeTest(unittest.TestCase):
    def test_notice_in_all_three_places(self):
        d = Digest("t", BODY, fallback=True, fallback_reason="SECRET-DETAIL")
        email = render_email(d, snapshot(), now=NOW)
        for part in (email.subject, email.html, email.text):
            self.assertIn("AI 摘要暂不可用", part)
        self.assertNotIn("SECRET-DETAIL", email.html + email.text + email.subject)


class MarkdownTest(unittest.TestCase):
    def test_parse(self):
        secs = parse_sections("前言\n\n## A\n- x\n- y\n段落\n\n## B\n1. one\n2) two\n---\n")
        self.assertEqual([s[0] for s in secs], ["摘要", "A", "B"])
        self.assertEqual(secs[1][1], [("ul", ["x", "y"]), ("p", ["段落"])])
        self.assertEqual(secs[2][1], [("ul", ["one", "two"])])

    def test_empty(self):
        self.assertEqual(parse_sections(""), [])


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
        self.assertIn("Alpha", render_email(digest, snapshot()).html)


if __name__ == "__main__":
    unittest.main()
