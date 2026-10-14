"""各组件之间传递的数据结构。"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Trend:
    rank: int
    name: str
    post_count: int = 0


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


@dataclass(frozen=True)
class Digest:
    """摘要结果，title 用于推送标题，body 为正文（markdown）。"""

    title: str
    body: str
