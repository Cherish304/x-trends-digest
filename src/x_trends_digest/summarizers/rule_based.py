"""规则摘要：不调用任何模型，按抓取数据拼一份简单的中文摘要，用作 AI 摘要的备用。"""

from typing import Dict, List

from ..interfaces import Summarizer
from ..models import Digest, Snapshot

_TOP_TRENDS = 3
_BULLET_TRENDS = 5
_BULLET_POSTS = 2
_POST_CHARS = 60


def _short(text: str, limit: int = _POST_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RuleBasedSummarizer(Summarizer):
    def complete(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError("规则摘要不使用 chat completions，请直接调用 summarize")

    def summarize(self, snapshot: Snapshot) -> Digest:
        return Digest(title="X 热点摘要", body=self._body(snapshot))

    @staticmethod
    def _body(snapshot: Snapshot) -> str:
        trends, posts = snapshot.trends, snapshot.posts
        if not trends and not posts:
            return "## 今日概览\n本次没有抓取到趋势或热门帖子。"

        lines = ["## 今日概览"]
        parts = []  # type: List[str]
        if trends:
            names = "、".join("「%s」" % t.name for t in trends[:_TOP_TRENDS])
            parts.append("X 上共有 %d 个热门趋势，居前的是%s" % (len(trends), names))
        if posts:
            parts.append("另抓取到 %d 条热门帖子" % len(posts))
        lines.append("，".join(parts) + "。")

        bullets = []  # type: List[str]
        for t in trends[:_BULLET_TRENDS]:
            line = "趋势「%s」排名第 %d" % (t.name, t.rank)
            if t.post_count is not None:  # 数量缺失时不写
                line += "，约 {:,} 帖".format(t.post_count)
            bullets.append(line + "。")
        top_posts = sorted(posts, key=lambda p: (-p.likes, -p.reposts))[:_BULLET_POSTS]
        for p in top_posts:
            bullets.append(
                "热帖 @%s（点赞 {:,}）：%s".format(p.likes) % (p.author, _short(p.text))
            )
        if bullets:
            lines += ["", "## 重点要点"] + ["- " + b for b in bullets]
        return "\n".join(lines)
