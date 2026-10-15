"""各组件之间传递的数据结构。"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Trend:
    rank: int
    name: str
    # None 表示来源没有给出数量（缺失/null/无法解析），展示和 prompt 里都不写数量
    post_count: Optional[int] = None
    url: str = ""

    @property
    def count_label(self) -> str:
        """给人看的数量文案，如 "120,000 帖"；未知时为空字符串。"""
        return "" if self.post_count is None else "{:,} 帖".format(self.post_count)


@dataclass(frozen=True)
class Post:
    id: str
    author: str
    text: str
    likes: int = 0
    reposts: int = 0
    url: str = ""


@dataclass(frozen=True)
class Snapshot:
    """一次抓取的结果。"""

    trends: List[Trend] = field(default_factory=list)
    posts: List[Post] = field(default_factory=list)
    fetched_at: str = ""  # ISO 时间，来源未提供时为空


@dataclass(frozen=True)
class Digest:
    """摘要结果，title 用于推送标题，body 为正文（markdown）。

    fallback=True 表示 AI 摘要不可用，body 是规则生成的备用摘要；
    fallback_reason 只用于日志，不会写进邮件。
    """

    title: str
    body: str
    fallback: bool = False
    fallback_reason: str = ""
