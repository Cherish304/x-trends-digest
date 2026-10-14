"""Mock 抓取：返回固定数据，不访问任何网络。"""

from ..interfaces import Fetcher
from ..models import Post, Snapshot, Trend


class MockFetcher(Fetcher):
    def fetch(self) -> Snapshot:
        return Snapshot(
            trends=[
                Trend(1, "#MockTopicA", 120000),
                Trend(2, "#MockTopicB", 85000),
                Trend(3, "示例热点", 40000),
            ],
            posts=[
                Post("1", "alice_mock", "这是一条用于测试的示例帖子 A", 1200, 300,
                     "https://example.invalid/1"),
                Post("2", "bob_mock", "Sample post B about #MockTopicB", 800, 150,
                     "https://example.invalid/2"),
                Post("3", "carol_mock", "示例帖子 C", 500, 90,
                     "https://example.invalid/3"),
            ],
        )
