class FetcherConfigError(ValueError):
    """配置问题（缺少路径或 token 等），在构造时立即抛出。"""


class FetcherError(RuntimeError):
    """抓取失败。消息已面向用户，且不包含密钥。"""
