from eagleeye_core.config import get_settings

from ingest_worker.parsing.base import Parser
from ingest_worker.parsing.docling_pdf import DoclingPdfParser
from ingest_worker.parsing.pdf import PdfParser
from ingest_worker.parsing.text import MarkdownParser, TextParser
from ingest_worker.parsing.word import DocxParser
from ingest_worker.sniff import FileKind

_PARSERS: dict[FileKind, Parser] = {
    "docx": DocxParser(),
    "markdown": MarkdownParser(),
    "text": TextParser(),
}
_PDF: dict[str, Parser] = {"docling": DoclingPdfParser(), "pypdf": PdfParser()}


def parser_for(kind: FileKind) -> Parser:
    if kind == "pdf":
        return _PDF.get(get_settings().pdf_parser, _PDF["docling"])
    return _PARSERS[kind]
