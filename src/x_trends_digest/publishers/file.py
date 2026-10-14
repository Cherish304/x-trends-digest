"""Mock 推送：把摘要写成本地 markdown 文件。"""

import os
from datetime import datetime

from ..interfaces import Publisher
from ..models import Digest


class FilePublisher(Publisher):
    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir

    def publish(self, digest: Digest) -> str:
        os.makedirs(self.output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = os.path.join(self.output_dir, "digest-%s.md" % stamp)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (digest.title, digest.body))
        return path
