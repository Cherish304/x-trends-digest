import os
import tempfile
import unittest

from x_trends_digest.config import ModelConfig, load_config, load_dotenv
from x_trends_digest.factory import build_fetcher, build_publisher, build_summarizer
from x_trends_digest.fetchers import MockFetcher
from x_trends_digest.models import Digest
from x_trends_digest.pipeline import run_once
from x_trends_digest.publishers import FilePublisher, StdoutPublisher
from x_trends_digest.summarizers import MockSummarizer, OpenAICompatibleSummarizer


class FetcherTest(unittest.TestCase):
    def test_mock_fetcher_returns_data(self):
        snap = MockFetcher().fetch()
        self.assertTrue(snap.trends)
        self.assertTrue(snap.posts)
        self.assertTrue(all(p.url.startswith("https://example.invalid") for p in snap.posts))


class SummarizerTest(unittest.TestCase):
    def test_messages_follow_chat_format(self):
        s = MockSummarizer()
        msgs = s.build_messages(MockFetcher().fetch())
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertIn("#MockTopicA", msgs[1]["content"])

    def test_mock_passthrough(self):
        s = MockSummarizer()
        digest = s.summarize(MockFetcher().fetch())
        self.assertIn("mock 摘要", digest.body)
        self.assertIn("alice_mock", digest.body)
        self.assertEqual(s.last_messages[0]["role"], "system")

    def test_openai_endpoint_and_body(self):
        cfg = ModelConfig(api_key="x", base_url="https://host.invalid/v1/", model="m")
        s = OpenAICompatibleSummarizer(cfg)
        self.assertEqual(s.endpoint, "https://host.invalid/v1/chat/completions")
        body = s.build_request_body([{"role": "user", "content": "hi"}])
        self.assertEqual(body["model"], "m")


class PublisherTest(unittest.TestCase):
    def test_file_publisher_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = FilePublisher(os.path.join(d, "sub")).publish(Digest("T", "正文"))
            with open(path, encoding="utf-8") as f:
                content = f.read()
        self.assertIn("# T", content)
        self.assertIn("正文", content)

    def test_stdout_publisher_prints(self):
        out = []
        dest = StdoutPublisher(out.append).publish(Digest("T", "B"))
        self.assertEqual(dest, "stdout")
        self.assertIn("B", out[0])


class PipelineTest(unittest.TestCase):
    def test_run_once_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = run_once(MockFetcher(), MockSummarizer(), FilePublisher(d))
            self.assertTrue(os.path.isfile(path))


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config({})
        self.assertEqual((cfg.fetcher, cfg.summarizer, cfg.publisher), ("mock", "mock", "file"))
        self.assertEqual(cfg.model.api_key, "")

    def test_reads_env(self):
        cfg = load_config({
            "DEEPSEEK_API_KEY": "k", "DEEPSEEK_BASE_URL": "https://h.invalid",
            "DEEPSEEK_MODEL": "m", "XTD_CRON": "*/5 * * * *",
        })
        self.assertEqual(cfg.model, ModelConfig("k", "https://h.invalid", "m"))
        self.assertEqual(cfg.cron, "*/5 * * * *")

    def test_dotenv_does_not_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w") as f:
                f.write("# c\nA=1\nB=\"2\"\n")
            env = {"A": "keep"}
            load_dotenv(p, env)
        self.assertEqual(env, {"A": "keep", "B": "2"})

    def test_factory_rejects_unknown_implementations(self):
        cfg = load_config({"XTD_FETCHER": "x_api", "XTD_SUMMARIZER": "nope",
                           "XTD_PUBLISHER": "slack"})
        for build in (build_fetcher, build_summarizer, build_publisher):
            with self.assertRaises(ValueError):
                build(cfg)

    def test_timeout_config(self):
        self.assertEqual(load_config({"DEEPSEEK_TIMEOUT": "5"}).model.timeout, 5.0)
        for bad in ("abc", "0", "-1"):
            with self.assertRaises(ValueError):
                load_config({"DEEPSEEK_TIMEOUT": bad})

    def test_model_config_repr_hides_key(self):
        self.assertNotIn("SECRET-VALUE", repr(load_config({"DEEPSEEK_API_KEY": "SECRET-VALUE"})))


if __name__ == "__main__":
    unittest.main()
