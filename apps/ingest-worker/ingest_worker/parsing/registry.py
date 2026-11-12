from ingest_worker.parsing.base import Parser
from ingest_worker.parsing.pdf import PdfParser
from ingest_worker.parsing.text import MarkdownParser, TextParser
from ingest_worker.parsing.word import DocxParser
from ingest_worker.sniff import FileKind

_PARSERS: dict[FileKind, Parser] = {
    "pdf": PdfParser(),
    "docx": DocxParser(),
    "markdown": MarkdownParser(),
    "text": TextParser(),
}


def parser_for(kind: FileKind) -> Parser:
    return _PARSERS[kind]
