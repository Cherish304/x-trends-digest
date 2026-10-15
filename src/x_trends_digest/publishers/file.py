"""Mock 推送：把邮件渲染成 .html 和 .txt 写到本地，供外部程序发送。"""

import os
from datetime import datetime
from typing import Optional, Tuple

from ..interfaces import Publisher
from ..models import Digest, Snapshot
from ..render import RenderedEmail, render_email


def write_email_files(
    email: RenderedEmail, directory: str, basename: str
) -> Tuple[str, str]:
    """写出 <basename>.html 和 <basename>.txt，返回两个路径。先写临时文件再改名，避免外部程序读到半截文件。"""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for ext, content in (("html", email.html), ("txt", email.text)):
        path = os.path.join(directory, "%s.%s" % (basename, ext))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
        paths.append(path)
    return paths[0], paths[1]


class FilePublisher(Publisher):
    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir

    def publish(self, digest: Digest, snapshot: Optional[Snapshot] = None) -> str:
        email = render_email(digest, snapshot)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        html_path, _ = write_email_files(email, self.output_dir, "digest-" + stamp)
        return html_path
