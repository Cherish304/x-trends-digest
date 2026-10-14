"""抓取 -> 摘要 -> 推送 的一次完整执行。"""

from .interfaces import Fetcher, Publisher, Summarizer


def run_once(fetcher: Fetcher, summarizer: Summarizer, publisher: Publisher) -> str:
    snapshot = fetcher.fetch()
    digest = summarizer.summarize(snapshot)
    return publisher.publish(digest)
