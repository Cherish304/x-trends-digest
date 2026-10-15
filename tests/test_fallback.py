"""总时长上限、备用摘要和 prompt 修正的测试。全部用假 opener / 假摘要器，无网络。"""

import io
import os
import threading
import time
import unittest
import urllib.error
from unittest import mock

from x_trends_digest import cli
from x_trends_digest.config import ModelConfig, load_config
from x_trends_digest.fetchers import MockFetcher
from x_trends_digest.interfaces import Summarizer
from x_trends_digest.models import Digest, Post, Snapshot, Trend
from x_trends_digest.pipeline import run_once
from x_trends_digest.publishers import FilePublisher
from x_trends_digest.summarizers import (
    FallbackSummarizer,
    MockSummarizer,
    OpenAICompatibleSummarizer,
    RuleBasedSummarizer,
    SummarizerError,
)

KEY = "test-key-NOT-REAL-789"
MSGS = [{"role": "user", "content": "x"}]


def model_cfg(**kw):
    base = dict(api_key=KEY, base_url="https://host.invalid", model="m",
                timeout=5.0, total_timeout=0.3)
    base.update(kw)
    return ModelConfig(**base)


class SlowResponse:
    """每次 read 睡一会儿再给一字节，模拟慢速滴灌的响应。"""

    def __init__(self, delay):
        self.delay = delay

    def read(self, n=-1):
        time.sleep(self.delay)
        return b"x"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TotalTimeoutTest(unittest.TestCase):
    def test_dripping_response_hits_total_timeout(self):
        s = OpenAICompatibleSummarizer(model_cfg(), opener=lambda req, timeout: SlowResponse(0.05))
        t0 = time.monotonic()
        with self.assertRaises(SummarizerError) as ctx:
            s.complete(MSGS)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertIn("总耗时", str(ctx.exception))
        self.assertIn("DEEPSEEK_TOTAL_TIMEOUT", str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_blocked_open_hits_total_timeout(self):
        """opener 本身卡住（如 DNS/连接挂起）时，主线程也能按时返回。"""
        release = threading.Event()

        def stuck(req, timeout):
            release.wait(5)
            raise urllib.error.URLError("late")

        s = OpenAICompatibleSummarizer(model_cfg(), opener=stuck)
        t0 = time.monotonic()
        try:
            with self.assertRaises(SummarizerError) as ctx:
                s.complete(MSGS)
            self.assertLess(time.monotonic() - t0, 2.0)
            self.assertIn("总耗时", str(ctx.exception))
        finally:
            release.set()

    def test_per_request_timeout_is_capped_by_remaining_budget(self):
        seen = []

        def opener(req, timeout):
            seen.append(timeout)
            raise urllib.error.URLError("boom")

        s = OpenAICompatibleSummarizer(model_cfg(timeout=30.0, total_timeout=0.5), opener=opener)
        with self.assertRaises(SummarizerError):
            s.complete(MSGS)
        self.assertLessEqual(seen[0], 0.5)

    def test_errors_propagate_from_worker_thread(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError("https://h", 401, "x", {}, io.BytesIO(b""))

        s = OpenAICompatibleSummarizer(model_cfg(total_timeout=5.0), opener=opener)
        with self.assertRaises(SummarizerError) as ctx:
            s.complete(MSGS)
        self.assertIn("认证失败", str(ctx.exception))

    def test_config(self):
        self.assertEqual(load_config({}).model.total_timeout, 60.0)
        self.assertEqual(load_config({"DEEPSEEK_TOTAL_TIMEOUT": "12"}).model.total_timeout, 12.0)
        for bad in ("abc", "0", "-5"):
            with self.assertRaises(ValueError):
                load_config({"DEEPSEEK_TOTAL_TIMEOUT": bad})


class Boom(Summarizer):
    def __init__(self, exc):
        self.exc = exc

    def complete(self, messages):
        raise self.exc


class FallbackTest(unittest.TestCase):
    def run_with(self, exc):
        logs = []
        fb = FallbackSummarizer(Boom(exc), RuleBasedSummarizer(), log=logs.append)
        return fb.summarize(MockFetcher().fetch()), logs

    def test_summarizer_error_falls_back(self):
        digest, logs = self.run_with(SummarizerError("请求被限流（HTTP 429）"))
        self.assertTrue(digest.fallback)
        self.assertIn("限流", digest.fallback_reason)
        self.assertIn("#MockTopicA", digest.body)
        self.assertIn("限流", logs[0])

    def test_unexpected_error_falls_back_without_leaking_message(self):
        digest, logs = self.run_with(RuntimeError("secret " + KEY))
        self.assertTrue(digest.fallback)
        self.assertNotIn(KEY, digest.fallback_reason + "".join(logs))

    def test_success_is_not_marked_fallback(self):
        fb = FallbackSummarizer(MockSummarizer(), RuleBasedSummarizer(), log=lambda m: None)
        self.assertFalse(fb.summarize(MockFetcher().fetch()).fallback)

    def test_end_to_end_still_produces_email_with_notice(self):
        import tempfile

        fb = FallbackSummarizer(Boom(SummarizerError("超时")), RuleBasedSummarizer(),
                                log=lambda m: None)
        with tempfile.TemporaryDirectory() as d:
            path = run_once(MockFetcher(), fb, FilePublisher(d))
            with open(path, encoding="utf-8") as f:
                html = f.read()
            with open(path[:-5] + ".txt", encoding="utf-8") as f:
                text = f.read()
        self.assertIn("AI 摘要暂不可用", html)
        self.assertIn("AI 摘要暂不可用", text)
        self.assertIn("#MockTopicA", html)

    def test_cli_run_once_with_failing_model_still_succeeds(self):
        import tempfile

        def always_fail(req, timeout):
            raise urllib.error.URLError("down")

        env = {"XTD_SUMMARIZER": "openai", "DEEPSEEK_API_KEY": KEY,
               "DEEPSEEK_BASE_URL": "https://host.invalid"}
        real_init = OpenAICompatibleSummarizer.__init__

        def patched_init(self, cfg, opener=None):
            real_init(self, cfg, opener=always_fail)

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, dict(env, XTD_OUTPUT_DIR=d), clear=True), \
                mock.patch.object(OpenAICompatibleSummarizer, "__init__", patched_init), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cli.main(["--env-file", os.path.join(d, "none.env"), "run-once"])
            names = os.listdir(d)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in names), ["html", "txt"])
        self.assertIn("备用摘要", err.getvalue())
        self.assertNotIn(KEY, err.getvalue())


class RuleBasedTest(unittest.TestCase):
    def test_chinese_summary_with_sections(self):
        body = RuleBasedSummarizer().summarize(MockFetcher().fetch()).body
        self.assertIn("## 今日概览", body)
        self.assertIn("## 重点要点", body)
        self.assertIn("#MockTopicA", body)
        self.assertIn("120,000", body)

    def test_missing_count_not_written(self):
        snap = Snapshot(trends=[Trend(1, "NoCount", None)], posts=[])
        body = RuleBasedSummarizer().summarize(snap).body
        self.assertIn("NoCount", body)
        self.assertNotIn("约", body)

    def test_empty_snapshot(self):
        self.assertIn("没有抓取到", RuleBasedSummarizer().summarize(Snapshot()).body)

    def test_posts_only(self):
        snap = Snapshot(posts=[Post("1", "a", "hello", 5, 1)])
        self.assertIn("@a", RuleBasedSummarizer().summarize(snap).body)


class PromptTest(unittest.TestCase):
    def test_missing_post_count_not_sent_to_model(self):
        snap = Snapshot(trends=[Trend(1, "HasCount", 1500), Trend(2, "NoCount", None),
                                Trend(3, "RealZero", 0)])
        user = MockSummarizer().build_messages(snap)[1]["content"]
        lines = {l.split(" ", 1)[1].split(" (")[0]: l for l in user.splitlines() if l[:1].isdigit()}
        self.assertIn("(1500 帖)", lines["HasCount"])
        self.assertEqual(lines["NoCount"], "2. NoCount")  # 一个字都不多写
        self.assertIn("(0 帖)", lines["RealZero"])  # 真实的 0 仍然写

    def test_openai_prompt_has_sections_and_no_count_rule(self):
        cfg = model_cfg()
        msgs = OpenAICompatibleSummarizer(cfg).build_messages(Snapshot(trends=[Trend(1, "T", None)]))
        self.assertIn("## 今日概览", msgs[0]["content"])
        self.assertIn("## 重点要点", msgs[0]["content"])
        self.assertIn("没有标注帖子数量", msgs[0]["content"])
        self.assertNotIn("帖)", msgs[1]["content"])


if __name__ == "__main__":
    unittest.main()
