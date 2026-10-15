"""Mock 推送：把纯文本版本打印到标准输出。"""

from typing import Callable, Optional

from ..interfaces import Publisher
from ..models import Digest, Snapshot
from ..render import render_email


class StdoutPublisher(Publisher):
    def __init__(self, printer: Callable[[str], None] = print) -> None:
        self._print = printer

    def publish(self, digest: Digest, snapshot: Optional[Snapshot] = None) -> str:
        email = render_email(digest, snapshot)
        self._print("主题: %s\n\n%s" % (email.subject, email.text))
        return "stdout"
