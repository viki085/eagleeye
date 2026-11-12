"""Plain text and Markdown. Blank lines separate paragraphs; `#` lines are headings."""

import re

from ingest_worker.parsing.base import ParsedDocument, ParsedElement

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _paragraphs(lines: list[str]) -> list[str]:
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip():
            buf.append(line.rstrip())
        elif buf:
            paras.append("\n".join(buf))
            buf = []
    if buf:
        paras.append("\n".join(buf))
    return paras


class TextParser:
    def parse(self, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8").replace("\r\n", "\n")
        return ParsedDocument(tuple(ParsedElement(p) for p in _paragraphs(text.split("\n"))))


class MarkdownParser:
    def parse(self, data: bytes) -> ParsedDocument:
        lines = data.decode("utf-8").replace("\r\n", "\n").split("\n")
        elements: list[ParsedElement] = []
        pending: list[str] = []
        in_fence = False

        def flush() -> None:
            elements.extend(ParsedElement(p) for p in _paragraphs(pending))
            pending.clear()

        for line in lines:
            if _FENCE.match(line):
                in_fence = not in_fence
            match = None if in_fence else _MD_HEADING.match(line)
            if match:
                flush()
                elements.append(ParsedElement(match.group(2), heading_level=len(match.group(1))))
            else:
                pending.append(line)
        flush()
        return ParsedDocument(tuple(elements))
