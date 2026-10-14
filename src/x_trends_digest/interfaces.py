"""三块功能的可替换接口。"""

from abc import ABC, abstractmethod
from typing import Dict, List

from .models import Digest, Snapshot


class Fetcher(ABC):
    """抓取 X 趋势和热门帖子。"""

    @abstractmethod
    def fetch(self) -> Snapshot:
        ...


class Summarizer(ABC):
    """把抓取结果变成摘要。

    summarize 默认走 OpenAI 兼容的 chat completions 消息格式：
    先用 build_messages 构造 messages，再交给 complete 得到文本。
    """

    @abstractmethod
    def complete(self, messages: List[Dict[str, str]]) -> str:
        """输入 chat completions 的 messages，返回助手回复文本。"""

    def build_messages(self, snapshot: Snapshot) -> List[Dict[str, str]]:
        lines = ["今日趋势："]
        for t in snapshot.trends:
            lines.append("%d. %s (%d 帖)" % (t.rank, t.name, t.post_count))
        lines.append("")
        lines.append("热门帖子：")
        for p in snapshot.posts:
            lines.append(
                "- @%s: %s (赞 %d / 转 %d)" % (p.author, p.text, p.likes, p.reposts)
            )
        return [
            {
                "role": "system",
                "content": "你是资讯编辑，请把 X 上的热点整理成简洁的中文摘要。",
            },
            {"role": "user", "content": "\n".join(lines)},
        ]

    def summarize(self, snapshot: Snapshot) -> Digest:
        text = self.complete(self.build_messages(snapshot))
        return Digest(title="X 热点摘要", body=text)


class Publisher(ABC):
    """把摘要推送出去。"""

    @abstractmethod
    def publish(self, digest: Digest) -> str:
        """返回一个描述推送去向的字符串（路径或渠道名）。"""
