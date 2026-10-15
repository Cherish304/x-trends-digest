"""带备用的摘要器：主摘要器超时或出错时，改用规则摘要，保证流程仍能出邮件。"""

import sys
from dataclasses import replace
from typing import Callable, Dict, List

from ..interfaces import Summarizer
from ..models import Digest, Snapshot


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class FallbackSummarizer(Summarizer):
    def __init__(
        self,
        primary: Summarizer,
        backup: Summarizer,
        log: Callable[[str], None] = _stderr,
    ) -> None:
        self.primary = primary
        self.backup = backup
        self._log = log

    def complete(self, messages: List[Dict[str, str]]) -> str:
        return self.primary.complete(messages)

    def summarize(self, snapshot: Snapshot) -> Digest:
        try:
            return self.primary.summarize(snapshot)
        except Exception as exc:  # 任何失败都要退回，否则整封邮件出不来
            # SummarizerError 的消息已面向用户且不含密钥；其他异常只记类型，避免泄露细节
            reason = str(exc) if type(exc).__name__ == "SummarizerError" else type(exc).__name__
            self._log("AI 摘要失败，已改用备用摘要: %s" % reason)
            return replace(
                self.backup.summarize(snapshot), fallback=True, fallback_reason=reason
            )
