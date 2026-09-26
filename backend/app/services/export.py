"""Export_Service: CSV / PDF of coordination pairs and their briefs (Req 14, Stretch)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from app.core.errors import InvalidExportError
from app.models.dto import CoordinationPairDTO

CSV_COLUMNS = [
    "pair_id", "utility_a", "project_a", "type_a", "utility_b", "project_b", "type_b",
    "distance_miles", "time_gap_days", "window_start", "window_end", "overlap_days",
    "overlap_pct", "composite_score", "brief",
]


@dataclass
class ExportRecord:
    pair_id: str
    utility_a: str
    project_a: str
    type_a: str
    utility_b: str
    project_b: str
    type_b: str
    distance_miles: float
    time_gap_days: str
    window_start: str
    window_end: str
    overlap_days: int
    overlap_pct: str  # share of the combined build span both projects are building
    composite_score: float
    brief: str

    def row(self) -> list[str]:
        return [str(getattr(self, c)) for c in CSV_COLUMNS]


def to_records(pairs: list[CoordinationPairDTO]) -> list[ExportRecord]:
    """Build export records; reject the whole export if any utility is missing (Req 14.3)."""
    missing = [
        p.id for p in pairs
        if not (p.project_a.utility or "").strip() or not (p.project_b.utility or "").strip()
    ]
    if missing:
        raise InvalidExportError(
            f"Export rejected: pair(s) {', '.join(missing)} are missing a utility.",
            fields=missing,
        )
    return [
        ExportRecord(
            pair_id=p.id,
            utility_a=p.project_a.utility, project_a=p.project_a.name or "",
            type_a=p.project_a.type.value if p.project_a.type else "",
            utility_b=p.project_b.utility, project_b=p.project_b.name or "",
            type_b=p.project_b.type.value if p.project_b.type else "",
            distance_miles=round(p.miles, 1),
            time_gap_days="" if p.time_gap_days is None else str(p.time_gap_days),
            window_start=p.window_start.isoformat() if p.window_start else "",
            window_end=p.window_end.isoformat() if p.window_end else "",
            overlap_days=p.overlap_days,
            overlap_pct="" if p.overlap_ratio is None else str(round(p.overlap_ratio * 100)),
            composite_score=round(p.scores.composite, 3),
            brief=p.brief.text if p.brief else "",
        )
        for p in pairs
    ]


def render_csv(records: list[ExportRecord]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in records:
        writer.writerow(r.row())
    return buf.getvalue().encode("utf-8")


def render_pdf(records: list[ExportRecord]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, title="GridMerge coordination briefs",
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph("GridMerge coordination briefs", styles["Title"])]
    if not records:
        story.append(
            Paragraph("No coordination pairs at the current thresholds.", styles["Normal"])
        )
    for r in records:
        story.append(Paragraph(
            escape(f"{r.utility_a} — {r.project_a or 'Unnamed project'}  ↔  "
                   f"{r.utility_b} — {r.project_b or 'Unnamed project'}"),
            styles["Heading3"],
        ))
        story.append(Paragraph(escape(
            f"{r.distance_miles} miles apart · "
            + (f"build windows {r.overlap_pct}% overlapping, shared {r.window_start} to "
               f"{r.window_end} ({r.overlap_days} days)"
               if r.window_start
               else f"in-service dates {r.time_gap_days or 'unknown'} days apart")
            + f" · score {r.composite_score}"
        ), styles["Normal"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            escape(r.brief) if r.brief else "<i>No coordination brief generated yet.</i>",
            styles["BodyText"],
        ))
        story.append(Spacer(1, 12))
    doc.build(story)
    return buf.getvalue()
