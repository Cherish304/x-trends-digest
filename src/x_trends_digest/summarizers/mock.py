"""Mock 摘要：不调用模型，直接把 user 消息透传为摘要正文。"""

from typing import Dict, List

from ..interfaces import Summarizer


class MockSummarizer(Summarizer):
    def __init__(self) -> None:
        self.last_messages = []  # type: List[Dict[str, str]]

    def complete(self, messages: List[Dict[str, str]]) -> str:
        self.last_messages = messages
        user = [m["content"] for m in messages if m.get("role") == "user"]
        return "【mock 摘要，透传输入】\n" + "\n".join(user)
