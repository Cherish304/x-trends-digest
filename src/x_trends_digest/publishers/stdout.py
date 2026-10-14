"""Mock 推送：打印到标准输出。"""

from typing import Callable

from ..interfaces import Publisher
from ..models import Digest


class StdoutPublisher(Publisher):
    def __init__(self, printer: Callable[[str], None] = print) -> None:
        self._print = printer

    def publish(self, digest: Digest) -> str:
        self._print("# %s\n\n%s" % (digest.title, digest.body))
        return "stdout"
