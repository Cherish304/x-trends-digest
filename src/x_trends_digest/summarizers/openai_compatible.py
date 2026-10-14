"""OpenAI 兼容 chat completions 实现骨架（未启用）。

本次不接真实模型：complete 会直接抛 NotImplementedError，
工厂里也不会返回它。上线时在 complete 里 POST
{base_url}/chat/completions，body 为 build_request_body 的结果，
请求头 Authorization: Bearer <api_key>，再读取 choices[0].message.content。
"""

from typing import Any, Dict, List

from ..config import ModelConfig
from ..interfaces import Summarizer


class OpenAICompatibleSummarizer(Summarizer):
    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg

    @property
    def endpoint(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/chat/completions"

    def build_request_body(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        return {"model": self.cfg.model, "messages": messages, "stream": False}

    def complete(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError(
            "真实模型调用尚未启用：请先实现 HTTP 请求并通过评审后再接入"
        )
