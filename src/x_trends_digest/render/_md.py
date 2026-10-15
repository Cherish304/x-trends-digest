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


_SENTENCE = re.compile(r"^(.+?[。！？!?]|.+?\.(?=\s))", re.S)


def _first_sentence(text: str) -> Tuple[str, str]:
    m = _SENTENCE.match(text.strip())
    if not m:
        return text.strip(), ""
    return m.group(1).strip(), text.strip()[m.end():].strip()


def split_lead(sections: List[Section], max_chars: int = 90) -> Tuple[str, List[Section]]:
    """取摘要的第一句话作为「今日一句话」，并把它从正文里拿掉，避免重复。

    返回 (导语, 剩余的板块)。第一句超过 max_chars 时只截断显示、不从正文移除。
    摘要为空时导语为空字符串。
    """
    if not sections or not sections[0][1]:
        return "", sections
    title, blocks = sections[0]
    kind, lines = blocks[0]
    text = " ".join(lines) if kind == "p" else lines[0]
    sentence, rest = _first_sentence(text)
    lead = sentence.replace("**", "").strip()
    if not lead:
        return "", sections
    if len(lead) > max_chars:
        return lead[: max_chars - 1].rstrip() + "…", sections

    new_blocks = list(blocks[1:])
    if kind == "ul":
        items = ([rest] if rest else []) + lines[1:]
        if items:
            new_blocks.insert(0, ("ul", items))
    elif rest:
        new_blocks.insert(0, ("p", [rest]))
    remaining = ([(title, new_blocks)] if new_blocks else []) + sections[1:]
    return lead, remaining


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
