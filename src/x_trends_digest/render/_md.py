"""极简 markdown 解析：只支持标题、列表、段落和 **加粗**，足够渲染模型输出。

返回 [(板块标题, [块])]，块为 ("p", [行]) 或 ("ul", [条目])。
这里只切分结构，不做任何转义；转义由 HTML/文本渲染各自负责。
"""

import re
from typing import List, Tuple

Block = Tuple[str, List[str]]
Section = Tuple[str, List[Block]]

DEFAULT_TITLE = "摘要"

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*\S)\s*$")
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")


class _Builder:
    def __init__(self) -> None:
        self.sections = []  # type: List[Section]
        self.title = None  # type: object
        self.blocks = []  # type: List[Block]
        self.para = []  # type: List[str]
        self.items = []  # type: List[str]

    def end_para(self) -> None:
        if self.para:
            self.blocks.append(("p", self.para))
            self.para = []

    def end_items(self) -> None:
        if self.items:
            self.blocks.append(("ul", self.items))
            self.items = []

    def end_blocks(self) -> None:
        self.end_para()
        self.end_items()

    def end_section(self) -> None:
        self.end_blocks()
        if self.blocks:
            self.sections.append((str(self.title or DEFAULT_TITLE), self.blocks))
        self.blocks = []


def parse_sections(body: str) -> List[Section]:
    b = _Builder()
    for line in (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip() or _RULE.match(line):
            b.end_blocks()
            continue
        m = _HEADING.match(line)
        if m:
            b.end_section()
            b.title = m.group(1).strip() or None
            continue
        m = _BULLET.match(line)
        if m:
            b.end_para()
            b.items.append(m.group(1))
            continue
        b.end_items()
        b.para.append(line.strip())
    b.end_section()
    return b.sections
