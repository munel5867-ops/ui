"""STAGE5 주간 자동보고서 생성 (python-docx)."""
import io
from datetime import date

from docx import Document
from docx.shared import Pt


def build_weekly_report_docx(
    period_start: date,
    period_end: date,
    total_count: int,
    automation_rate: float,
    human_review_count: int,
    crack_or_lop_miss_count: int,
    porosity_miss_count: int,
    anomaly_note: str,
    recommendation: str,
) -> bytes:
    doc = Document()

    title = doc.add_heading("RT 결함 판독 시스템 — 주간 리포트", level=1)
    title.runs[0].font.size = Pt(18)

    doc.add_paragraph(f"기간: {period_start.isoformat()} ~ {period_end.isoformat()}")

    doc.add_heading("요약 지표", level=2)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text = "지표", "값"

    rows = [
        ("총 검사 물량", f"{total_count:,}건"),
        ("자동화율", f"{automation_rate:.1%}"),
        ("사람 확인 건수", f"{human_review_count:,}건"),
        ("균열·용입불량(D1+D4) 미검출", f"{crack_or_lop_miss_count}건"),
        ("기공(D2) 미검출", f"{porosity_miss_count}건"),
    ]
    for k, v in rows:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = k, v

    doc.add_heading("이상 신호", level=2)
    doc.add_paragraph(anomaly_note)

    doc.add_heading("권고사항", level=2)
    doc.add_paragraph(recommendation)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
