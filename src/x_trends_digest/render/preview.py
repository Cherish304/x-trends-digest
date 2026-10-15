"""用 examples/ 下的数据渲染样例邮件。

固定了摘要正文和生成时间，输出是确定的，所以测试可以校验 examples/preview.html
和当前渲染器是否同步。重新生成：

    PYTHONPATH=src python3 -m x_trends_digest.render.preview
"""

import os
import sys
from datetime import datetime
from typing import Optional

from ..fetchers import JsonFileFetcher
from ..interfaces import Fetcher
from ..models import Digest
from . import RenderedEmail, render_email

SAMPLE_BODY = """## 今日概览
AI 与硬件发布占据了今天 X 的热榜。开发者社区在围绕新模型的定价和工具链展开讨论。

## 重点要点
- **新模型发布**：多位开发者分享了上手体验，讨论集中在响应速度和 API 价格上。
- **硬件新品**：新款家用设备的发布引发了对隐私与生态封闭性的争论。
- **开源动态**：几个热门项目宣布了新版本，评论里有不少迁移经验分享。

## 值得关注
- 价格调整是否会持续，目前只有零星信息，建议继续观察。
- 关于数据来源的争论仍在发酵，暂无定论。"""

# 固定时间，保证输出稳定
GENERATED_AT = datetime(2026, 10, 14, 9, 5)


def build_preview(fetcher: Fetcher) -> RenderedEmail:
    return render_email(Digest("X 热点摘要", SAMPLE_BODY), fetcher.fetch(), now=GENERATED_AT)


def main(root: Optional[str] = None) -> int:
    root = root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    examples = os.path.join(root, "examples")
    email = build_preview(JsonFileFetcher(os.path.join(examples, "snapshot.json")))
    for name, content in (("preview.html", email.html), ("preview.txt", email.text)):
        with open(os.path.join(examples, name), "w", encoding="utf-8") as f:
            f.write(content)
        print("已写入 examples/" + name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
