"""Ingestion_Service: synchronous validation before any persistence (Req 1)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import FileTooLargeError, MissingMetadataError, UnsupportedFormatError
from app.services.parsing import SUPPORTED_FORMATS, ParsedDocument, detect_format, parse_document

_CHUNK = 1024 * 1024


@dataclass
class ValidatedUpload:
    utility: str
    source_url: str
    filename: str | None
    data: bytes
    document: ParsedDocument

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
    upload: UploadFile | None, utility: str | None, source_url: str | None
) -> ValidatedUpload:
    utility, source_url = validate_metadata(utility, source_url)
    if upload is None:
        raise MissingMetadataError("Missing required file upload.", field="file")
    data = await read_limited(upload)
    document = validate_bytes(data, upload.filename)
    return ValidatedUpload(utility, source_url, upload.filename, data, document)
