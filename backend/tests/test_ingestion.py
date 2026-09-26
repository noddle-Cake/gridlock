import inspect
import io

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import (
    CorruptFileError,
    FileTooLargeError,
    GridMergeError,
    MissingMetadataError,
    UnsupportedFormatError,
)
from app.services.ingestion import validate_bytes, validate_metadata
from app.services.parsing import detect_format


def make_pdf(pages: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def make_xlsx(rows: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CSV = (
    b"Project,Type,kV,Location,Start,End\n"
    b"Hanover breakers,substation,138,Hanover PA,Q2 2026,Q4 2026\n"
)
PDF = make_pdf(["Capital plan 2026", "Hanover 138kV breaker replacement Q2 2026"])
XLSX = make_xlsx([["Project", "kV"], ["Hanover breakers", 138]])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
DOCX_LIKE = b"PK\x03\x04" + b"\x00" * 64  # zip header, broken container
JSON = b'{"projects": []}'

FILES = {
    "pdf": (PDF, "plan.pdf", "pdf"),
    "xlsx": (XLSX, "plan.xlsx", "xlsx"),
    "csv": (CSV, "plan.csv", "csv"),
    "png": (PNG, "plan.png", None),
    "json": (JSON, "plan.json", None),
    "zip": (DOCX_LIKE, "plan.zip", None),
    "png-renamed": (PNG, "plan.pdf", None),  # extension lies; content wins
}

metadata = st.one_of(st.none(), st.just(""), st.just("   "), st.text(min_size=1, max_size=20))


# Feature: gridmerge, Property 16: Ingestion accept/reject invariant
@given(st.sampled_from(list(FILES)), metadata, metadata, st.booleans())
def test_accept_reject_invariant(kind, utility, source_url, oversize):
    data, filename, expected_format = FILES[kind]
    from app.core.config import get_settings

    settings = get_settings()
    limit = settings.max_upload_bytes
    if oversize:
        settings.max_upload_bytes = len(data) - 1
    try:
        meta_ok = all(v is not None and v.strip() for v in (utility, source_url))
        should_accept = meta_ok and expected_format is not None and not oversize
        try:
            validate_metadata(utility, source_url)
            doc = validate_bytes(data, filename)
        except MissingMetadataError as exc:
            assert not meta_ok
            missing = [n for n, v in (("utility", utility), ("source_url", source_url))
                       if v is None or not v.strip()]
            assert exc.fields == missing and exc.field == missing[0]
            return
        except FileTooLargeError as exc:
            assert oversize and "maximum size limit" in exc.message
            return
        except UnsupportedFormatError as exc:
            assert expected_format is None
            assert exc.detected_format and exc.detected_format in exc.message
            return
        assert should_accept
        assert doc.format == expected_format
    finally:
        settings.max_upload_bytes = limit


def test_size_error_names_the_limit():
    from app.core.config import get_settings

    settings = get_settings()
    limit = settings.max_upload_bytes
    settings.max_upload_bytes = 50 * 1024 * 1024
    try:
        with pytest.raises(FileTooLargeError, match="50 MB"):
            validate_bytes(b"a,b\n" * (13 * 1024 * 1024 + 1), "big.csv")
    finally:
        settings.max_upload_bytes = limit


@pytest.mark.parametrize(
    ("data", "filename"),
    [
        (b"%PDF-1.7\n this is not really a pdf", "broken.pdf"),
        (b"PK\x03\x04garbage-not-a-zip", "broken.xlsx"),
        (b"", "empty.csv"),
        (b"\n\n\n", "blank.csv"),
    ],
)
def test_corrupt_supported_files_rejected(data, filename):
    with pytest.raises(CorruptFileError, match="could not be read"):
        validate_bytes(data, filename)


def test_detect_format_by_content():
    assert detect_format(PDF, "whatever.bin") == "pdf"
    assert detect_format(XLSX, "plan") == "xlsx"
    assert detect_format(CSV, "plan.txt") == "csv"
    assert detect_format(PNG, "plan.csv") == "png"


def test_pages_are_annotated():
    doc = validate_bytes(PDF, "plan.pdf")
    assert doc.page_count == 2
    assert "Hanover" in doc.pages[1]
    assert validate_bytes(XLSX, "p.xlsx").pages[0].startswith("Sheet:")
    assert "Row 2:" in validate_bytes(CSV, "p.csv").pages[0]


def test_errors_are_gridmerge_errors():
    for cls in (CorruptFileError, FileTooLargeError, MissingMetadataError, UnsupportedFormatError):
        assert issubclass(cls, GridMergeError)
    from app.services.ingestion import validate_upload

    assert inspect.iscoroutinefunction(validate_upload)
