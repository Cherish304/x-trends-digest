"""按配置名称选择实现。真实实现未启用，选择它们会明确报错。"""

from .config import Config
from .fetchers import MockFetcher
from .interfaces import Fetcher, Publisher, Summarizer
from .publishers import FilePublisher, StdoutPublisher
from .summarizers import MockSummarizer, OpenAICompatibleSummarizer


def build_fetcher(cfg: Config) -> Fetcher:
    if cfg.fetcher == "mock":
        return MockFetcher()
    raise ValueError("未知或未启用的 fetcher: %r（目前仅支持 mock）" % cfg.fetcher)


def build_summarizer(cfg: Config) -> Summarizer:
    if cfg.summarizer == "mock":
        return MockSummarizer()
    if cfg.summarizer in ("openai", "deepseek"):
        # key 缺失或 base_url 不安全时在这里立即抛 SummarizerConfigError
        return OpenAICompatibleSummarizer(cfg.model)
    raise ValueError(
        "未知的 summarizer: %r（支持 mock / openai / deepseek）" % cfg.summarizer
    )


def build_publisher(cfg: Config) -> Publisher:
    if cfg.publisher == "file":
        return FilePublisher(cfg.output_dir)
    if cfg.publisher == "stdout":
        return StdoutPublisher()
    raise ValueError("未知或未启用的 publisher: %r（支持 file / stdout）" % cfg.publisher)
