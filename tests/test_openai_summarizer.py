"""OpenAI 兼容摘要器测试：全部用假 opener 注入，不产生任何真实网络请求。"""

import io
import json
import socket
import unittest
import urllib.error

from x_trends_digest.config import load_config
from x_trends_digest.factory import build_summarizer
from x_trends_digest.fetchers import MockFetcher
from x_trends_digest.summarizers import (
    FallbackSummarizer,
    RuleBasedSummarizer,
    OpenAICompatibleSummarizer,
    SummarizerConfigError,
    SummarizerError,
)
from x_trends_digest.config import ModelConfig

KEY = "test-key-NOT-REAL-123"


class FakeResponse:
    """像真实响应一样推进读取位置：读完后 read 返回 b""。"""

    def __init__(self, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self._buf = io.BytesIO(raw)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """记录请求；按 result 返回响应或抛出异常。"""

    def __init__(self, result):
        self.result = result
        self.requests = []
        self.timeouts = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        self.timeouts.append(timeout)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def ok_payload(text="摘要内容"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError(
        "https://host.invalid/chat/completions", code, "err", headers or {}, io.BytesIO(body)
    )


def make(opener, base_url="https://host.invalid/v1", timeout=7.0):
    cfg = ModelConfig(api_key=KEY, base_url=base_url, model="m1", timeout=timeout)
    return OpenAICompatibleSummarizer(cfg, opener=opener)


class RequestTest(unittest.TestCase):
    def test_request_shape_and_result(self):
        opener = FakeOpener(FakeResponse(ok_payload("  今日热点  ")))
        digest = make(opener).summarize(MockFetcher().fetch())
        self.assertEqual(digest.body, "今日热点")
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://host.invalid/v1/chat/completions")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], "m1")
        self.assertFalse(body["stream"])
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("中文", body["messages"][0]["content"])
        self.assertIn("#MockTopicA", body["messages"][1]["content"])
        self.assertIn("alice_mock", body["messages"][1]["content"])
        self.assertNotIn(KEY, req.data.decode("utf-8"))

    def test_timeout_is_passed(self):
        opener = FakeOpener(FakeResponse(ok_payload()))
        make(opener, timeout=7.0).complete([{"role": "user", "content": "x"}])
        self.assertEqual(opener.timeouts, [7.0])


class ConfigErrorTest(unittest.TestCase):
    def test_missing_key_fails_immediately(self):
        cfg = ModelConfig(api_key="", base_url="https://host.invalid", model="m")
        with self.assertRaises(SummarizerConfigError) as ctx:
            OpenAICompatibleSummarizer(cfg)
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))

    def test_plain_http_remote_rejected(self):
        cfg = ModelConfig(api_key=KEY, base_url="http://host.invalid", model="m")
        with self.assertRaises(SummarizerConfigError) as ctx:
            OpenAICompatibleSummarizer(cfg)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_http_localhost_allowed(self):
        cfg = ModelConfig(api_key=KEY, base_url="http://localhost:8080", model="m")
        OpenAICompatibleSummarizer(cfg)

    def test_factory_selects_openai_and_deepseek(self):
        env = {"DEEPSEEK_API_KEY": KEY, "DEEPSEEK_BASE_URL": "https://host.invalid"}
        for name in ("openai", "deepseek"):
            cfg = load_config(dict(env, XTD_SUMMARIZER=name))
            s = build_summarizer(cfg)
            self.assertIsInstance(s, FallbackSummarizer)
            self.assertIsInstance(s.primary, OpenAICompatibleSummarizer)
            self.assertIsInstance(s.backup, RuleBasedSummarizer)

    def test_factory_missing_key_raises(self):
        cfg = load_config({"XTD_SUMMARIZER": "openai"})
        with self.assertRaises(SummarizerConfigError):
            build_summarizer(cfg)


class HttpErrorTest(unittest.TestCase):
    def call(self, exc):
        with self.assertRaises(SummarizerError) as ctx:
            make(FakeOpener(exc)).complete([{"role": "user", "content": "x"}])
        self.assertNotIn(KEY, str(ctx.exception))
        return str(ctx.exception)

    def test_401(self):
        msg = self.call(http_error(401))
        self.assertIn("认证失败", msg)
        self.assertIn("401", msg)

    def test_429_with_retry_after(self):
        msg = self.call(http_error(429, headers={"Retry-After": "12"}))
        self.assertIn("限流", msg)
        self.assertIn("12", msg)

    def test_429_without_header(self):
        self.assertIn("限流", self.call(http_error(429)))

    def test_5xx(self):
        for code in (500, 502, 503):
            msg = self.call(http_error(code))
            self.assertIn("服务端错误", msg)
            self.assertIn(str(code), msg)

    def test_other_4xx_redacts_key_in_body(self):
        msg = self.call(http_error(400, body=("bad request " + KEY).encode()))
        self.assertIn("400", msg)
        self.assertIn("***", msg)

    def test_timeout(self):
        self.assertIn("超时", self.call(socket.timeout("timed out")))

    def test_urlerror_timeout(self):
        self.assertIn("超时", self.call(urllib.error.URLError(socket.timeout("t"))))

    def test_connection_error(self):
        msg = self.call(urllib.error.URLError("dns failure"))
        self.assertIn("无法连接", msg)


class ResponseParseTest(unittest.TestCase):
    def call(self, payload):
        with self.assertRaises(SummarizerError) as ctx:
            make(FakeOpener(FakeResponse(payload))).complete([{"role": "user", "content": "x"}])
        return str(ctx.exception)

    def test_not_json(self):
        self.assertIn("格式", self.call(b"<html>oops</html>"))

    def test_missing_choices(self):
        self.assertIn("格式", self.call({"error": "x"}))

    def test_empty_choices(self):
        self.assertIn("格式", self.call({"choices": []}))

    def test_empty_content(self):
        self.assertIn("空内容", self.call(ok_payload("   ")))

    def test_null_content(self):
        self.assertIn("空内容", self.call({"choices": [{"message": {"content": None}}]}))


class CliErrorTest(unittest.TestCase):
    def run_cli(self, env, summarizer=None):
        import contextlib
        import os
        import tempfile
        from unittest import mock

        from x_trends_digest import cli

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, dict(env, XTD_OUTPUT_DIR=d), clear=True), \
                contextlib.redirect_stderr(err):
            patch = mock.patch.object(cli, "build_summarizer", return_value=summarizer) \
                if summarizer else contextlib.nullcontext()
            with patch:
                rc = cli.main(["--env-file", os.path.join(d, "none.env"), "run-once"])
        return rc, err.getvalue()

    def test_missing_key_exits_2_with_clear_message(self):
        rc, err = self.run_cli({"XTD_SUMMARIZER": "openai"})
        self.assertEqual(rc, 2)
        self.assertIn("DEEPSEEK_API_KEY", err)

    def test_api_failure_exits_1_without_key(self):
        s = make(FakeOpener(http_error(401)))
        rc, err = self.run_cli({}, summarizer=s)
        self.assertEqual(rc, 1)
        self.assertIn("认证失败", err)
        self.assertNotIn(KEY, err)


if __name__ == "__main__":
    unittest.main()
