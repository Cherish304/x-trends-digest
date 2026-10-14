"""json 文件抓取器：从本地 JSON 快照读取趋势和帖子，不访问网络。

字段缺失时尽量宽容：缺少 name 的趋势、缺少 text 的帖子会被跳过；
数字字段缺失、为 null 或无法解析时按 0 处理。
"""

import json
import os
from typing import Any, List

from ..interfaces import Fetcher
from ..models import Post, Snapshot, Trend
from .errors import FetcherConfigError, FetcherError

_MAX_FILE_BYTES = 5 * 1024 * 1024


def to_int(value: Any) -> int:
    """宽容的整数转换：None、布尔、负数、无法解析的值都按 0。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0) if value == value else 0  # 排除 NaN
    if isinstance(value, str):
        try:
            return max(int(value.strip().replace(",", "")), 0)
        except ValueError:
            return 0
    return 0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class JsonFileFetcher(Fetcher):
    def __init__(self, path: str) -> None:
        if not path:
            raise FetcherConfigError("缺少 XTD_SNAPSHOT_PATH：XTD_FETCHER=json 需要指定快照文件路径")
        self.path = path

    def fetch(self) -> Snapshot:
        try:
            if os.path.getsize(self.path) > _MAX_FILE_BYTES:
                raise FetcherError("快照文件过大（超过 %d MB）: %s" % (_MAX_FILE_BYTES // 1024 // 1024, self.path))
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FetcherError:
            raise
        except FileNotFoundError:
            raise FetcherError("快照文件不存在: %s" % self.path) from None
        except (OSError, UnicodeDecodeError) as exc:
            raise FetcherError("无法读取快照文件 %s: %s" % (self.path, exc)) from None
        except ValueError as exc:
            raise FetcherError("快照文件不是合法的 JSON（%s）: %s" % (self.path, exc)) from None
        if not isinstance(data, dict):
            raise FetcherError("快照顶层必须是 JSON 对象: %s" % self.path)

        return Snapshot(
            trends=self._trends(data.get("trends")),
            posts=self._posts(data.get("posts")),
            fetched_at=_text(data.get("fetched_at")),
        )

    @staticmethod
    def _trends(raw: Any) -> List[Trend]:
        out = []  # type: List[Trend]
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or not _text(item.get("name")):
                continue
            out.append(
                Trend(
                    rank=len(out) + 1,
                    name=_text(item["name"]),
                    post_count=to_int(item.get("post_count")),
                    url=_text(item.get("url")),
                )
            )
        return out

    @staticmethod
    def _posts(raw: Any) -> List[Post]:
        out = []  # type: List[Post]
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or not _text(item.get("text")):
                continue
            out.append(
                Post(
                    id=_text(item.get("id")) or str(len(out) + 1),
                    author=_text(item.get("author")).lstrip("@") or "unknown",
                    text=_text(item["text"]),
                    likes=to_int(item.get("likes")),
                    reposts=to_int(item.get("reposts")),
                    url=_text(item.get("url")),
                )
            )
        return out
