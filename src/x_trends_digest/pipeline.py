"""抓取 -> 摘要 -> 推送 的一次完整执行。"""

from typing import Tuple

from .interfaces import Fetcher, Publisher, Summarizer
from .models import Digest, Snapshot


def build_digest(fetcher: Fetcher, summarizer: Summarizer) -> Tuple[Snapshot, Digest]:
    snapshot = fetcher.fetch()
    return snapshot, summarizer.summarize(snapshot)


def run_once(fetcher: Fetcher, summarizer: Summarizer, publisher: Publisher) -> str:
    snapshot, digest = build_digest(fetcher, summarizer)
    return publisher.publish(digest, snapshot)
