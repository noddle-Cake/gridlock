"""Ingestion_Service: synchronous validation before any persistence (Req 1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import (
    FileTooLargeError,
    InvalidFieldError,
    MissingMetadataError,
    UnsupportedFormatError,
)
from app.services.parsing import SUPPORTED_FORMATS, ParsedDocument, detect_format, parse_document

_CHUNK = 1024 * 1024


@dataclass
class ValidatedUpload:
    utility: str
    source_url: str
    filename: str | None
    data: bytes
    document: ParsedDocument
    page_range: str | None = None  # normalized, e.g. "18-45,50"; None = whole file

    @property
    def format(self) -> str:
        return self.document.format


def validate_metadata(utility: str | None, source_url: str | None) -> tuple[str, str]:
    missing = [
        name for name, value in (("utility", utility), ("source_url", source_url))
        if value is None or not value.strip()
    ]
    if missing:
        raise MissingMetadataError(
            f"Missing required metadata: {', '.join(missing)}.",
            field=missing[0], fields=missing,
        )
    return utility.strip(), source_url.strip()  # type: ignore[union-attr]


def validate_bytes(data: bytes, filename: str | None) -> ParsedDocument:
    """Format, size, and readability checks on in-memory content. Persists nothing."""
    limit = get_settings().max_upload_bytes
    if len(data) > limit:
        raise FileTooLargeError(
            f"The file exceeds the {limit // (1024 * 1024)} MB maximum size limit."
        )
    fmt = detect_format(data, filename)
    if fmt not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"Unsupported file format '{fmt}'. Supported formats: PDF, XLSX, CSV.",
            detected_format=fmt,
        )
    return parse_document(data, fmt)  # raises CorruptFileError


_RANGE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")


def parse_page_range(spec: str | None, page_count: int) -> tuple[str | None, set[int] | None]:
    """'18-45, 50' -> ('18-45,50', {18..45, 50}). Blank means the whole file.

    Long regional filings (e.g. SERTP covers seven balancing areas) only need a slice;
    extracting the rest costs model calls and floods the map with unrelated projects.
    """
    if spec is None or not spec.strip():
        return None, None
    keep: set[int] = set()
    parts: list[str] = []
    for token in spec.split(","):
        m = _RANGE.match(token.strip())
        if not m:
            raise InvalidFieldError(
                f"pages: {token.strip()!r} is not a page or range like 18-45.", field="pages",
                fields=["pages"],
            )
        first = int(m.group(1))
        last = int(m.group(2) or first)
        if first < 1 or last < first or last > page_count:
            raise InvalidFieldError(
                f"pages: {token.strip()!r} is outside 1-{page_count} (the file has "
                f"{page_count} pages).", field="pages", fields=["pages"],
            )
        keep.update(range(first, last + 1))
        parts.append(f"{first}-{last}" if last > first else str(first))
    return ",".join(parts), keep


async def read_limited(upload: UploadFile) -> bytes:
    """Read an upload, bailing out as soon as it passes the size limit."""
    limit = get_settings().max_upload_bytes
    buf = bytearray()
    while chunk := await upload.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > limit:
            raise FileTooLargeError(
                f"The file exceeds the {limit // (1024 * 1024)} MB maximum size limit."
            )
    return bytes(buf)


async def validate_upload(
    upload: UploadFile | None, utility: str | None, source_url: str | None,
    pages: str | None = None,
) -> ValidatedUpload:
    utility, source_url = validate_metadata(utility, source_url)
    if upload is None:
        raise MissingMetadataError("Missing required file upload.", field="file")
    data = await read_limited(upload)
    document = validate_bytes(data, upload.filename)
    page_range, keep = parse_page_range(pages, document.page_count)
    if keep is not None:
        document = document.only_pages(keep)
        if not any(document.pages):
            raise InvalidFieldError(
                f"pages: the selected pages ({page_range}) contain no extractable text.",
                field="pages", fields=["pages"],
            )
    return ValidatedUpload(utility, source_url, upload.filename, data, document, page_range)
