"""Content-based format detection and page-annotated parsing (Req 1.3, 1.6, 2.7).

Pages: a PDF page is a page; each XLSX worksheet is a page; a CSV is a single page.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass

from app.core.errors import CorruptFileError

SUPPORTED_FORMATS = ("pdf", "xlsx", "csv")
MAX_CELL_CHARS = 300


@dataclass
class ParsedDocument:
    format: str
    pages: list[str]  # pages[i] is the text of page i + 1

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _decode_text(data: bytes) -> str | None:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        # Real text has (almost) no control characters other than whitespace.
        controls = sum(1 for ch in text[:4096] if ord(ch) < 32 and ch not in "\r\n\t\f")
        if controls == 0:
            return text
    return None


def detect_format(data: bytes, filename: str | None = None) -> str:
    """Detect a file's format from its bytes; the extension only breaks ties for text."""
    ext = _extension(filename)
    head = data[:8]
    if not data:
        return ext if ext in SUPPORTED_FORMATS else "empty"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            # Looks like a zip container but is broken; if it claims to be xlsx, it's corrupt.
            return "xlsx" if ext == "xlsx" else "zip"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls/doc (legacy OLE)"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"

    text = _decode_text(data)
    if text is None:
        return "binary"
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
            return "json"
        except ValueError:
            pass
    low = stripped[:200].lower()
    if low.startswith(("<!doctype html", "<html")):
        return "html"
    if low.startswith("<?xml") or low.startswith("<"):
        return "xml"
    if ext == "csv":
        return "csv"
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        rows = list(csv.reader(io.StringIO(sample), dialect))
        widths = {len(r) for r in rows[:20] if r}
        if len(widths) >= 1 and max(widths) >= 2:
            return "csv"
    except csv.Error:
        pass
    return "text"


# ---------------------------------------------------------------- parsers


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\n", " ")
    return text[:MAX_CELL_CHARS]


def _render_rows(rows: list[list[str]]) -> str:
    """Render tabular rows as 'Row N: Header=value; ...' lines for the LLM."""
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    header = rows[0]
    lines = ["Columns: " + " | ".join(header)]
    for i, row in enumerate(rows[1:], start=2):
        cells = []
        for j, value in enumerate(row):
            if not value:
                continue
            name = header[j] if j < len(header) and header[j] else f"col{j + 1}"
            cells.append(f"{name}={value}")
        if cells:
            lines.append(f"Row {i}: " + "; ".join(cells))
    return "\n".join(lines)


def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise CorruptFileError("The PDF is encrypted and could not be read.")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except CorruptFileError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise CorruptFileError(f"The PDF could not be read: {exc}") from exc
    if not pages:
        raise CorruptFileError("The PDF could not be read: it contains no pages.")
    if not any(pages):
        raise CorruptFileError(
            "The PDF could not be read: no extractable text (is it a scanned image?)."
        )
    return ParsedDocument("pdf", pages)


def parse_xlsx(data: bytes) -> ParsedDocument:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        pages = []
        for ws in wb.worksheets:
            rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
            body = _render_rows(rows)
            pages.append(f"Sheet: {ws.title}\n{body}" if body else "")
        wb.close()
    except Exception as exc:  # openpyxl raises a wide variety of errors on bad input
        raise CorruptFileError(f"The spreadsheet could not be read: {exc}") from exc
    if not any(pages):
        raise CorruptFileError("The spreadsheet could not be read: it contains no data.")
    return ParsedDocument("xlsx", pages)


def parse_csv(data: bytes) -> ParsedDocument:
    text = _decode_text(data)
    if text is None:
        raise CorruptFileError("The CSV could not be read: it is not valid text.")
    try:
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[_cell(v) for v in row] for row in csv.reader(io.StringIO(text), dialect)]
    except csv.Error as exc:
        raise CorruptFileError(f"The CSV could not be read: {exc}") from exc
    body = _render_rows(rows)
    if not body:
        raise CorruptFileError("The CSV could not be read: it contains no rows.")
    return ParsedDocument("csv", [body])


def parse_document(data: bytes, fmt: str) -> ParsedDocument:
    match fmt:
        case "pdf":
            return parse_pdf(data)
        case "xlsx":
            return parse_xlsx(data)
        case "csv":
            return parse_csv(data)
    raise ValueError(f"unsupported format: {fmt}")
