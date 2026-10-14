"""配置：全部从环境变量读取，不在代码里写任何密钥。"""

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class ModelConfig:
    # repr=False：避免 print(cfg) / 日志意外带出密钥
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout: float = DEFAULT_TIMEOUT


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
    try:
        timeout = float(env.get("DEEPSEEK_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        raise ValueError("DEEPSEEK_TIMEOUT 必须是数字（秒）")
    if timeout <= 0:
        raise ValueError("DEEPSEEK_TIMEOUT 必须大于 0")
    model = ModelConfig(
        api_key=env.get("DEEPSEEK_API_KEY", ""),
        base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=timeout,
    )
    return Config(
        fetcher=env.get("XTD_FETCHER", "mock"),
        summarizer=env.get("XTD_SUMMARIZER", "mock"),
        publisher=env.get("XTD_PUBLISHER", "file"),
        cron=env.get("XTD_CRON", "0 9 * * *"),
        output_dir=env.get("XTD_OUTPUT_DIR", "out"),
        model=model,
    )
