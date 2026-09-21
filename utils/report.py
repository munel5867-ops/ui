"""주간 자동보고서 생성 (python-docx)."""
import io
from datetime import date

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

FONT_NAME = "맑은 고딕"


def _apply_korean(font, element, size=None, bold=None):
    """run/style에 한글이 깨지지 않는 폰트를 명시적으로 지정.
    font.name만 설정하면 ascii/hAnsi(서양문자)만 바뀌고 eastAsia(한글) 폰트는
    그대로 남아 Word가 다른 폰트로 대체하면서 글자가 이상하게 보일 수 있다."""
    font.name = FONT_NAME
    rPr = element.get_or_add_rPr()
    rFonts = rPr.rFonts if rPr.rFonts is not None else rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), FONT_NAME)
    if size is not None:
        font.size = size
    if bold is not None:
        font.bold = bold


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

    normal = doc.styles["Normal"]
    _apply_korean(normal.font, normal.element)

    title = doc.add_heading("RT 결함 판독 시스템 — 주간 리포트", level=1)
    _apply_korean(title.runs[0].font, title.runs[0]._element, size=Pt(18), bold=True)

    p = doc.add_paragraph(f"기간: {period_start.isoformat()} ~ {period_end.isoformat()}")
    _apply_korean(p.runs[0].font, p.runs[0]._element)

    h2 = doc.add_heading("요약 지표", level=2)
    _apply_korean(h2.runs[0].font, h2.runs[0]._element)

    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text = "지표", "값"
    for cell in hdr:
        _apply_korean(cell.paragraphs[0].runs[0].font, cell.paragraphs[0].runs[0]._element, bold=True)

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
        _apply_korean(cells[0].paragraphs[0].runs[0].font, cells[0].paragraphs[0].runs[0]._element)
        _apply_korean(cells[1].paragraphs[0].runs[0].font, cells[1].paragraphs[0].runs[0]._element)

    h3 = doc.add_heading("이상 신호", level=2)
    _apply_korean(h3.runs[0].font, h3.runs[0]._element)
    p2 = doc.add_paragraph(anomaly_note)
    _apply_korean(p2.runs[0].font, p2.runs[0]._element)

    h4 = doc.add_heading("권고사항", level=2)
    _apply_korean(h4.runs[0].font, h4.runs[0]._element)
    p3 = doc.add_paragraph(recommendation)
    _apply_korean(p3.runs[0].font, p3.runs[0]._element)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def weekly_report_bytes(thresholds):
    """탭4·탭3(오늘의 현황) 양쪽에서 같은 로직으로 보고서를 만들기 위한 공용 함수."""
    from datetime import date, timedelta

    from utils.dummy_data import load_validation_predictions
    from utils.routing import compute_kpis

    df = load_validation_predictions()
    kpis = compute_kpis(df, thresholds)

    period_end = date.today()
    period_start = period_end - timedelta(days=6)
    total_count = 3214  # TODO: 실제 이번 주 검사 물량 집계로 교체
    human_review_count = round(total_count * kpis["human_review_rate"])
    crack_or_lop_miss_count = round(total_count * kpis["crack_or_lop_miss_rate"])
    porosity_miss_count = round(total_count * kpis["porosity_miss_rate"])
    anomaly_note = "SPC p-chart에서 UCL 초과 이상점 1건 발생 → 원인분석이 필요합니다."
    recommendation = "균열·용입불량(D1+D4) 통합 임계값(CRACK_OR_LOP_T) 재검토를 권장합니다."

    docx_bytes = build_weekly_report_docx(
        period_start=period_start, period_end=period_end, total_count=total_count,
        automation_rate=kpis["automation_rate"], human_review_count=human_review_count,
        crack_or_lop_miss_count=crack_or_lop_miss_count, porosity_miss_count=porosity_miss_count,
        anomaly_note=anomaly_note, recommendation=recommendation,
    )
    return docx_bytes, f"weekly_report_{period_end.isoformat()}.docx"
