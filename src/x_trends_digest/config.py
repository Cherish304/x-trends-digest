"""配置：全部从环境变量读取，不在代码里写任何密钥。"""

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

DEFAULT_TIMEOUT = 30.0
DEFAULT_TOTAL_TIMEOUT = 60.0


@dataclass(frozen=True)
class ModelConfig:
    # repr=False：避免 print(cfg) / 日志意外带出密钥
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout: float = DEFAULT_TIMEOUT  # 单次网络读写超时
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT  # 整个调用的总时长上限


@dataclass(frozen=True)
class XApiConfig:
    bearer_token: str = field(repr=False)  # 不进入 repr / 日志
    woeid: int = 1
    max_posts: int = 10
    trends_for_posts: int = 3
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class Config:
    fetcher: str = "mock"
    summarizer: str = "mock"
    publisher: str = "file"
    cron: str = "0 9 * * *"
    output_dir: str = "out"
    snapshot_path: str = ""
    model: Optional[ModelConfig] = None
    xapi: Optional[XApiConfig] = None


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


def _num(env: Mapping[str, str], name: str, default, cast, lo, hi=None):
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError("%s 必须是%s" % (name, "整数" if cast is int else "数字"))
    if value < lo or (hi is not None and value > hi):
        rng = "不小于 %s" % lo if hi is None else "在 %s 到 %s 之间" % (lo, hi)
        raise ValueError("%s 必须%s" % (name, rng))
    return value


def load_config(environ: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if environ is None else environ
    timeout = _num(env, "DEEPSEEK_TIMEOUT", DEFAULT_TIMEOUT, float, 0.001)
    xapi = XApiConfig(
        bearer_token=env.get("X_BEARER_TOKEN", "").strip(),
        woeid=_num(env, "XTD_WOEID", 1, int, 1),
        max_posts=_num(env, "XTD_MAX_POSTS", 10, int, 1, 100),
        trends_for_posts=_num(env, "XTD_TRENDS_FOR_POSTS", 3, int, 1, 10),
        timeout=_num(env, "XTD_FETCH_TIMEOUT", DEFAULT_TIMEOUT, float, 0.001),
    )
    model = ModelConfig(
        api_key=env.get("DEEPSEEK_API_KEY", ""),
        base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=timeout,
        total_timeout=_num(
            env, "DEEPSEEK_TOTAL_TIMEOUT", DEFAULT_TOTAL_TIMEOUT, float, 0.001
        ),
    )
    return Config(
        fetcher=env.get("XTD_FETCHER", "mock"),
        summarizer=env.get("XTD_SUMMARIZER", "mock"),
        publisher=env.get("XTD_PUBLISHER", "file"),
        cron=env.get("XTD_CRON", "0 9 * * *"),
        output_dir=env.get("XTD_OUTPUT_DIR", "out"),
        snapshot_path=env.get("XTD_SNAPSHOT_PATH", ""),
        model=model,
        xapi=xapi,
    )
