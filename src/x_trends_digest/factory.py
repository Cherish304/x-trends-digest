"""按配置名称选择实现。真实实现未启用，选择它们会明确报错。"""

from .config import Config
from .fetchers import JsonFileFetcher, MockFetcher, XApiFetcher
from .interfaces import Fetcher, Publisher, Summarizer
from .publishers import FilePublisher, StdoutPublisher
from .summarizers import MockSummarizer, OpenAICompatibleSummarizer


def build_fetcher(cfg: Config) -> Fetcher:
    if cfg.fetcher == "mock":
        return MockFetcher()
    if cfg.fetcher == "json":
        return JsonFileFetcher(cfg.snapshot_path)  # 缺路径时立即报错
    if cfg.fetcher == "xapi":
        return XApiFetcher(cfg.xapi)  # 缺 token 时立即报错
    raise ValueError("未知的 fetcher: %r（支持 mock / json / xapi）" % cfg.fetcher)


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
