"""X API v2 抓取器（仅用标准库 urllib）。

1. GET https://api.x.com/2/trends/by/woeid/{woeid}  取趋势
2. 对前几个趋势调用 GET https://api.x.com/2/tweets/search/recent，
   带 public_metrics，合并去重后按点赞数降序取前 N 条。

Bearer token 只出现在请求头里，不会进入日志或异常信息。
注意：响应字段名（trend_name / tweet_count / public_metrics 等）依据 X API v2
的公开约定编写，尚未用真实 token 联调，上线前必须验证。
"""

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode

from .._http import open_no_redirect
from ..config import XApiConfig
from ..interfaces import Fetcher
from ..models import Post, Snapshot, Trend
from .errors import FetcherConfigError, FetcherError
from .json_file import to_int

API_BASE = "https://api.x.com"
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_QUERY_LEN = 512


class XApiFetcher(Fetcher):
    def __init__(
        self,
        cfg: XApiConfig,
        opener: Optional[Callable[..., Any]] = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        token = cfg.bearer_token
        if not token:
            raise FetcherConfigError(
                "缺少 X_BEARER_TOKEN：XTD_FETCHER=xapi 需要 X API 的 Bearer token"
            )
        if any(c.isspace() for c in token):
            raise FetcherConfigError("X_BEARER_TOKEN 含有空白字符，请检查是否复制完整")
        self.cfg = cfg
        self._open = opener or open_no_redirect
        self._now = now

    # ---- 公共入口 ----
    def fetch(self) -> Snapshot:
        trends = self._fetch_trends()
        posts = self._fetch_posts(trends[: self.cfg.trends_for_posts])
        return Snapshot(trends=trends, posts=posts, fetched_at=self._now().isoformat())

    # ---- 趋势 ----
    def _fetch_trends(self) -> List[Trend]:
        data = self._get("/2/trends/by/woeid/%d" % self.cfg.woeid, {})
        items = data.get("data")
        if not isinstance(items, list):
            raise FetcherError("趋势接口返回格式不符：缺少 data 列表")
        trends = []  # type: List[Trend]
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("trend_name")
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            trends.append(
                Trend(
                    rank=len(trends) + 1,
                    name=name,
                    post_count=to_int(item.get("tweet_count")),
                    url="https://x.com/search?q=" + quote(name),
                )
            )
        return trends

    # ---- 帖子 ----
    @staticmethod
    def _build_query(trend_name: str) -> str:
        name = trend_name.replace('"', " ").strip()
        if any(c.isspace() for c in name):
            name = '"%s"' % " ".join(name.split())
        return ("%s -is:retweet" % name)[:_MAX_QUERY_LEN]

    def _fetch_posts(self, trends: List[Trend]) -> List[Post]:
        # 搜索接口 max_results 的合法范围是 10-100
        per_call = min(max(self.cfg.max_posts, 10), 100)
        by_id = {}  # type: Dict[str, Post]
        for trend in trends:
            params = {
                "query": self._build_query(trend.name),
                "max_results": per_call,
                "tweet.fields": "public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            try:
                data = self._get("/2/tweets/search/recent", params)
            except XRateLimited as exc:
                if by_id:
                    break  # 已有部分结果：被限流就用已取到的，不整体失败
                raise FetcherError(str(exc)) from None
            for post in self._parse_posts(data):
                by_id.setdefault(post.id, post)
        ranked = sorted(by_id.values(), key=lambda p: (-p.likes, -p.reposts, p.id))
        return ranked[: self.cfg.max_posts]

    @staticmethod
    def _parse_posts(data: Dict[str, Any]) -> List[Post]:
        users = {}  # type: Dict[str, str]
        includes = data.get("includes")
        for u in (includes.get("users") if isinstance(includes, dict) else None) or []:
            if isinstance(u, dict) and u.get("id") and u.get("username"):
                users[str(u["id"])] = str(u["username"])
        out = []  # type: List[Post]
        for t in data.get("data") or []:
            if not isinstance(t, dict) or not t.get("id") or not isinstance(t.get("text"), str):
                continue
            metrics = t.get("public_metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            author = users.get(str(t.get("author_id", "")), "unknown")
            pid = str(t["id"])
            out.append(
                Post(
                    id=pid,
                    author=author,
                    text=t["text"].strip(),
                    likes=to_int(metrics.get("like_count")),
                    reposts=to_int(metrics.get("retweet_count")),
                    url="https://x.com/%s/status/%s" % (author, pid) if author != "unknown"
                    else "https://x.com/i/web/status/" + pid,
                )
            )
        return out

    # ---- HTTP ----
    def _redact(self, text: str) -> str:
        return text.replace(self.cfg.bearer_token, "***")

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = API_BASE + path + ("?" + urlencode(params) if params else "")
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": "Bearer " + self.cfg.bearer_token,
                "Accept": "application/json",
            },
        )
        try:
            with self._open(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read(_MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except socket.timeout:
            raise self._timeout_error() from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise self._timeout_error() from None
            raise FetcherError("无法连接 X API：%s" % self._redact(str(exc.reason))) from None
        except OSError as exc:
            raise FetcherError("网络错误：%s" % self._redact(str(exc))) from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise FetcherError("X API 返回的不是合法 JSON") from None
        if not isinstance(data, dict):
            raise FetcherError("X API 返回格式不符：顶层不是 JSON 对象")
        return data

    def _timeout_error(self) -> FetcherError:
        return FetcherError(
            "X API 请求超时（%s 秒）：请稍后重试或调大 XTD_FETCH_TIMEOUT" % self.cfg.timeout
        )

    def _http_error(self, exc: urllib.error.HTTPError) -> FetcherError:
        code = exc.code
        if code == 401:
            return FetcherError(
                "X API 认证失败（HTTP 401）：Bearer token 无效、已撤销或类型不对，请检查 X_BEARER_TOKEN"
            )
        if code == 403:
            return FetcherError(
                "X API 拒绝访问（HTTP 403）：当前 token 所在的应用或套餐无权调用该接口"
            )
        if code == 429:
            reset = exc.headers.get("x-rate-limit-reset") if exc.headers else None
            hint = "（额度重置时间戳 %s）" % reset if reset else ""
            return XRateLimited("X API 请求被限流（HTTP 429）%s：请稍后重试" % hint)
        if 500 <= code < 600:
            return FetcherError("X API 服务端错误（HTTP %d）：服务暂时不可用，请稍后重试" % code)
        detail = ""
        try:
            detail = self._redact(exc.read(500).decode("utf-8", "replace")).strip()
        except Exception:
            pass
        msg = "X API 请求失败（HTTP %d）" % code
        return FetcherError(msg + "：" + detail if detail else msg)


class XRateLimited(FetcherError):
    """429 限流；搜索阶段已有部分结果时允许降级使用。"""
