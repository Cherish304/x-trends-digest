"""真实抓取器测试：json 文件用临时文件，xapi 用注入的假 opener，不产生真实网络请求。"""

import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
from urllib.parse import parse_qs, urlparse

from x_trends_digest.config import XApiConfig, load_config
from x_trends_digest.factory import build_fetcher
from x_trends_digest.fetchers import (
    FetcherConfigError,
    FetcherError,
    JsonFileFetcher,
    XApiFetcher,
)

TOKEN = "test-token-NOT-REAL-456"
EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "snapshot.json")


class JsonFetcherTest(unittest.TestCase):
    def write(self, d, obj, raw=None):
        p = os.path.join(d, "s.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(obj))
        return p

    def test_example_file_parses(self):
        snap = JsonFileFetcher(EXAMPLE).fetch()
        self.assertEqual(snap.fetched_at, "2026-10-14T09:00:00+08:00")
        self.assertEqual([t.name for t in snap.trends], ["#ExampleTopicA", "#ExampleTopicB", "示例热点"])
        self.assertEqual([t.rank for t in snap.trends], [1, 2, 3])
        self.assertEqual(snap.trends[0].post_count, 120000)
        self.assertEqual(snap.trends[1].post_count, 0)  # null -> 0
        self.assertEqual(len(snap.posts), 3)
        self.assertEqual(snap.posts[2].likes, 0)  # 缺失 -> 0

    def test_tolerant_of_bad_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write(d, {
                "trends": [{"name": "  ok  ", "post_count": "1,234"}, {"post_count": 5},
                           "junk", {"name": ""}, {"name": "neg", "post_count": -3},
                           {"name": "bool", "post_count": True}],
                "posts": [{"author": "@alice", "text": "hi", "likes": "7", "reposts": 2.9},
                          {"author": "x"}, 42, {"text": "no author"}],
            })
            snap = JsonFileFetcher(p).fetch()
        self.assertEqual([t.name for t in snap.trends], ["ok", "neg", "bool"])
        self.assertEqual([t.post_count for t in snap.trends], [1234, 0, 0])
        self.assertEqual([t.rank for t in snap.trends], [1, 2, 3])
        self.assertEqual((snap.posts[0].author, snap.posts[0].likes, snap.posts[0].reposts),
                         ("alice", 7, 2))
        self.assertEqual(snap.posts[1].author, "unknown")
        self.assertEqual(snap.fetched_at, "")

    def test_missing_sections_ok(self):
        with tempfile.TemporaryDirectory() as d:
            snap = JsonFileFetcher(self.write(d, {})).fetch()
        self.assertEqual((snap.trends, snap.posts), ([], []))

    def test_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for raw in ("not json", "[1, 2]"):
                with self.assertRaises(FetcherError):
                    JsonFileFetcher(self.write(d, None, raw=raw)).fetch()
            with self.assertRaises(FetcherError) as ctx:
                JsonFileFetcher(os.path.join(d, "missing.json")).fetch()
            self.assertIn("不存在", str(ctx.exception))

    def test_missing_path_fails_immediately(self):
        with self.assertRaises(FetcherConfigError) as ctx:
            JsonFileFetcher("")
        self.assertIn("XTD_SNAPSHOT_PATH", str(ctx.exception))

    def test_factory_and_config(self):
        cfg = load_config({"XTD_FETCHER": "json", "XTD_SNAPSHOT_PATH": EXAMPLE})
        self.assertIsInstance(build_fetcher(cfg), JsonFileFetcher)
        with self.assertRaises(FetcherConfigError):
            build_fetcher(load_config({"XTD_FETCHER": "json"}))


class FakeResponse:
    def __init__(self, payload):
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self, n=-1):
        return self._raw if n < 0 else self._raw[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Router:
    """按路径返回响应；值为 Exception 则抛出，为列表则依次消费。"""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        self.timeouts = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        self.timeouts.append(timeout)
        path = urlparse(req.full_url).path
        result = self.routes[path]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError("https://api.x.com/x", code, "err", headers or {}, io.BytesIO(body))


TRENDS = {"data": [{"trend_name": "Alpha Topic", "tweet_count": 5000},
                   {"trend_name": "#Beta", "tweet_count": 300},
                   {"trend_name": "Gamma"}, {"trend_name": "Delta"}]}


def tweets(*items):
    """items: (id, author_id, likes, rts)"""
    return {
        "data": [{"id": i, "text": "text " + i, "author_id": a,
                  "public_metrics": {"like_count": l, "retweet_count": r}}
                 for i, a, l, r in items],
        "includes": {"users": [{"id": "u1", "username": "alice"}, {"id": "u2", "username": "bob"}]},
    }


def make(routes, **kw):
    cfg = XApiConfig(bearer_token=TOKEN, **kw)
    opener = Router(routes)
    return XApiFetcher(cfg, opener=opener, now=lambda: __import__("datetime").datetime(2026, 1, 1)), opener


SEARCH = "/2/tweets/search/recent"


class XApiTest(unittest.TestCase):
    def test_requests_and_ranking(self):
        f, op = make({
            "/2/trends/by/woeid/23424977": TRENDS,
            SEARCH: [tweets(("1", "u1", 10, 1), ("2", "u2", 500, 5)),
                     tweets(("2", "u2", 500, 5), ("3", "u1", 90, 0))],
        }, woeid=23424977, max_posts=2, trends_for_posts=2, timeout=9.0)
        snap = f.fetch()
        self.assertEqual([t.name for t in snap.trends], ["Alpha Topic", "#Beta", "Gamma", "Delta"])
        self.assertEqual(snap.trends[0].post_count, 5000)
        self.assertEqual([p.id for p in snap.posts], ["2", "3"])  # 按点赞降序、去重、截断
        self.assertEqual(snap.posts[0].author, "bob")
        self.assertEqual(snap.posts[0].url, "https://x.com/bob/status/2")
        self.assertEqual(snap.fetched_at, "2026-01-01T00:00:00")
        # 1 次趋势 + 2 次搜索（只对前 2 个趋势）
        self.assertEqual(len(op.requests), 3)
        self.assertEqual(op.timeouts, [9.0] * 3)
        for r in op.requests:
            self.assertEqual(r.get_method(), "GET")
            self.assertEqual(r.get_header("Authorization"), "Bearer " + TOKEN)
            self.assertTrue(r.full_url.startswith("https://api.x.com/2/"))
            self.assertNotIn(TOKEN, r.full_url)
        q = parse_qs(urlparse(op.requests[1].full_url).query)
        self.assertEqual(q["query"], ['"Alpha Topic" -is:retweet'])  # 含空格的趋势加引号
        self.assertEqual(q["max_results"], ["10"])  # 搜索接口下限 10
        self.assertIn("public_metrics", q["tweet.fields"][0])
        q2 = parse_qs(urlparse(op.requests[2].full_url).query)
        self.assertEqual(q2["query"], ["#Beta -is:retweet"])

    def test_missing_token_fails_immediately(self):
        with self.assertRaises(FetcherConfigError) as ctx:
            XApiFetcher(XApiConfig(bearer_token=""))
        self.assertIn("X_BEARER_TOKEN", str(ctx.exception))
        with self.assertRaises(FetcherConfigError) as ctx:
            build_fetcher(load_config({"XTD_FETCHER": "xapi"}))
        self.assertIn("X_BEARER_TOKEN", str(ctx.exception))

    def test_token_with_whitespace_rejected_without_echo(self):
        with self.assertRaises(FetcherConfigError) as ctx:
            XApiFetcher(XApiConfig(bearer_token="abc def"))
        self.assertNotIn("abc", str(ctx.exception))

    def test_config_defaults_and_validation(self):
        cfg = load_config({"X_BEARER_TOKEN": TOKEN})
        self.assertEqual((cfg.xapi.woeid, cfg.xapi.max_posts), (1, 10))
        self.assertNotIn(TOKEN, repr(cfg))
        cfg = load_config({"XTD_WOEID": "23424977", "XTD_MAX_POSTS": "25"})
        self.assertEqual((cfg.xapi.woeid, cfg.xapi.max_posts), (23424977, 25))
        for k, v in (("XTD_MAX_POSTS", "0"), ("XTD_MAX_POSTS", "101"), ("XTD_MAX_POSTS", "x"),
                     ("XTD_WOEID", "abc")):
            with self.assertRaises(ValueError):
                load_config({k: v})

    def _trend_error(self, exc):
        f, _ = make({"/2/trends/by/woeid/1": exc})
        with self.assertRaises(FetcherError) as ctx:
            f.fetch()
        self.assertNotIn(TOKEN, str(ctx.exception))
        return str(ctx.exception)

    def test_401(self):
        msg = self._trend_error(http_error(401))
        self.assertIn("认证失败", msg)
        self.assertIn("X_BEARER_TOKEN", msg)

    def test_403(self):
        self.assertIn("拒绝访问", self._trend_error(http_error(403)))

    def test_429_on_trends_fails(self):
        msg = self._trend_error(http_error(429, headers={"x-rate-limit-reset": "1760000000"}))
        self.assertIn("限流", msg)
        self.assertIn("1760000000", msg)

    def test_5xx_and_other(self):
        self.assertIn("服务端错误", self._trend_error(http_error(503)))
        msg = self._trend_error(http_error(400, body=("bad " + TOKEN).encode()))
        self.assertIn("400", msg)
        self.assertIn("***", msg)

    def test_timeout_and_connection(self):
        self.assertIn("超时", self._trend_error(socket.timeout("t")))
        self.assertIn("超时", self._trend_error(urllib.error.URLError(socket.timeout("t"))))
        self.assertIn("无法连接", self._trend_error(urllib.error.URLError("dns")))

    def test_429_on_search_degrades_when_partial(self):
        f, _ = make({"/2/trends/by/woeid/1": TRENDS,
                     SEARCH: [tweets(("1", "u1", 10, 1)), http_error(429)]}, trends_for_posts=2)
        snap = f.fetch()
        self.assertEqual([p.id for p in snap.posts], ["1"])

    def test_429_on_first_search_fails(self):
        f, _ = make({"/2/trends/by/woeid/1": TRENDS, SEARCH: [http_error(429)]})
        with self.assertRaises(FetcherError) as ctx:
            f.fetch()
        self.assertIn("限流", str(ctx.exception))

    def test_401_on_search_fails(self):
        f, _ = make({"/2/trends/by/woeid/1": TRENDS, SEARCH: [http_error(401)]})
        with self.assertRaises(FetcherError) as ctx:
            f.fetch()
        self.assertIn("认证失败", str(ctx.exception))

    def test_malformed_responses(self):
        for payload in (b"<html>", {"errors": []}, [1], {"data": "x"}):
            f, _ = make({"/2/trends/by/woeid/1": payload})
            with self.assertRaises(FetcherError):
                f.fetch()

    def test_tolerates_odd_tweets(self):
        odd = {"data": [{"id": "1", "text": "ok", "author_id": "zz"}, {"text": "no id"},
                        {"id": "2"}, "junk"]}
        f, _ = make({"/2/trends/by/woeid/1": TRENDS, SEARCH: [odd]}, trends_for_posts=1)
        snap = f.fetch()
        self.assertEqual(len(snap.posts), 1)
        self.assertEqual((snap.posts[0].author, snap.posts[0].likes), ("unknown", 0))
        self.assertEqual(snap.posts[0].url, "https://x.com/i/web/status/1")

    def test_factory_selects_xapi(self):
        cfg = load_config({"XTD_FETCHER": "xapi", "X_BEARER_TOKEN": TOKEN})
        self.assertIsInstance(build_fetcher(cfg), XApiFetcher)


if __name__ == "__main__":
    unittest.main()
