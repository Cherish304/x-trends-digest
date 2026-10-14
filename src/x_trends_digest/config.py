"""配置：全部从环境变量读取，不在代码里写任何密钥。"""

import os
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class Config:
    fetcher: str = "mock"
    summarizer: str = "mock"
    publisher: str = "file"
    cron: str = "0 9 * * *"
    output_dir: str = "out"
    model: Optional[ModelConfig] = None


def load_dotenv(path: str, environ: Optional[dict] = None) -> None:
    """极简 .env 读取：只补充尚未设置的变量。文件不存在则忽略。"""
    env = os.environ if environ is None else environ
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value


def load_config(environ: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if environ is None else environ
    model = ModelConfig(
        api_key=env.get("DEEPSEEK_API_KEY", ""),
        base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=env.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    return Config(
        fetcher=env.get("XTD_FETCHER", "mock"),
        summarizer=env.get("XTD_SUMMARIZER", "mock"),
        publisher=env.get("XTD_PUBLISHER", "file"),
        cron=env.get("XTD_CRON", "0 9 * * *"),
        output_dir=env.get("XTD_OUTPUT_DIR", "out"),
        model=model,
    )
