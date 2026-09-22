"""'부적합 보고서(NCR)' docx 생성 — 조원이 만든 ISO 9001 양식(부적합보고서_양식_ISO9001.docx)의
표 구조·레이아웃을 그대로 재현한다 (Word 기본 '제목' 스타일 대신 원본처럼 표+굵은 텍스트 사용).

AI/시스템이 이미 알고 있는 값(발견일자·검사방법·제품번호·부적합유형·AI확률·Grad-CAM 확인여부)만
자동으로 채우고, 사람이 판단해야 하는 항목(중대성 분류, 격리·처리 방법, 원인분석, 시정조치,
승인)은 검사자가 나중에 채우도록 빈칸으로 둔다. AI가 원인을 함부로 확정하면 안 되므로
근본원인 체크박스도 자동 체크하지 않는다.
"""
import io
from datetime import date, datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

FONT_NAME = "맑은 고딕"
DEFECT_TYPES = ["균열(D1)", "기공(D2)", "용입불량(D4)"]


def _shade_cell(cell, hex_color):
    """표 셀에 배경색을 입힌다 (python-docx는 기본 API가 없어 xml을 직접 조작)."""
    from docx.oxml import OxmlElement
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def _apply_korean(font, element, size=None, bold=None):
    font.name = FONT_NAME
    rPr = element.get_or_add_rPr()
    rFonts = rPr.rFonts if rPr.rFonts is not None else rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), FONT_NAME)
    if size is not None:
        font.size = size
    if bold is not None:
        font.bold = bold


def _bold_line(doc, text, size=11):
    """원본 양식의 '**1  부적합 식별 정보**' 같은 섹션 제목 — Word 기본 Heading 스타일(과하게
    큰 글씨) 대신 표 구조는 원본 그대로 두고, 색만 남색(브랜드 컬러)으로 입힌다."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    _apply_korean(run.font, run._element, size=Pt(size), bold=True)
    run.font.color.rgb = RGBColor(0x18, 0x4F, 0x95)  # 브랜드 남색
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    return p


def _cell(cell, text, bold=False, size=10, align_center=False):
    cell.text = ""
    p = cell.paragraphs[0]
    if align_center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    _apply_korean(run.font, run._element, size=Pt(size), bold=bold)


def _checkbox_line(checked_label, all_labels, gap="   "):
    parts = []
    for lab in all_labels:
        mark = "☑" if lab == checked_label else "☐"
        parts.append(f"{mark} {lab}")
    return gap.join(parts)


def _grid_table(doc, rows, cols):
    t = doc.add_table(rows=rows, cols=cols)
    t.style = "Light Grid Accent 1"  # 파란 계열 컬러 그리드 — 흑백 Table Grid 대신 사용
    return t


def build_ncr_docx(
    image_id: str,
    dominant_class: str,
    ai_prob: float,
    decision: str = "반려(불량)",
    report_no: str = None,
    found_date: date = None,
) -> bytes:
    found_date = found_date or date.today()
    report_no = report_no or f"NCR-{found_date.strftime('%Y%m')}-{image_id}"

    doc = Document()
    normal = doc.styles["Normal"]
    _apply_korean(normal.font, normal.element, size=Pt(10))
    for section in doc.sections:
        section.left_margin = section.right_margin = Pt(42)

    # ------------------------------------------------------------
    # 제목 테이블 — 원본과 동일하게 1행 2열 표로 (Heading 스타일 안 씀)
    # ------------------------------------------------------------
    title_t = doc.add_table(rows=1, cols=2)
    title_t.style = "Table Grid"
    title_t.columns[0].width = Pt(200)
    tc0, tc1 = title_t.rows[0].cells
    _shade_cell(tc0, "184F95")  # 남색 배경
    p0 = tc0.paragraphs[0]
    r0 = p0.add_run("부적합 보고서")
    _apply_korean(r0.font, r0._element, size=Pt(14), bold=True)
    r0.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    r0b = p0.add_run("  Nonconformance Report (NCR)")
    _apply_korean(r0b.font, r0b._element, size=Pt(9))
    r0b.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    _cell(
        tc1,
        f"적용 표준: ISO 9001:2015   관련 조항: 8.7 / 10.2   "
        f"문서번호: {report_no}   개정: Rev.0",
        size=9,
    )

    note_p = doc.add_paragraph()
    note_run = note_p.add_run(
        "※ 음영 없는 빈칸은 검사자/품질팀이 직접 작성해야 하는 항목입니다. "
        "발견일자·검사방법·제품번호·부적합유형·판정근거는 시스템이 자동으로 채웠습니다."
    )
    _apply_korean(note_run.font, note_run._element, size=Pt(8))
    note_p.paragraph_format.space_before = Pt(4)
    note_p.paragraph_format.space_after = Pt(2)

    # ------------------------------------------------------------
    # 1. 부적합 식별 정보
    # ------------------------------------------------------------
    _bold_line(doc, "1  부적합 식별 정보")
    t1 = _grid_table(doc, rows=4, cols=4)
    rows1 = [
        ("발견일자", found_date.isoformat(), "보고번호", report_no),
        ("발견 공정/단계", "", "발견자", ""),
        ("검사방법", "RT(방사선투과검사) / AI 1차 판정 + 검사원 확인", "소속부서", ""),
    ]
    for r, (k1, v1, k2, v2) in enumerate(rows1):
        _cell(t1.cell(r, 0), k1, bold=True)
        _cell(t1.cell(r, 1), v1)
        _cell(t1.cell(r, 2), k2, bold=True)
        _cell(t1.cell(r, 3), v2)
    # 마지막 행: "제품/로트/필름 번호"는 원본처럼 한 줄 전체를 쓰도록 뒤 3칸 병합
    last = t1.rows[3].cells
    merged_val = last[1].merge(last[2]).merge(last[3])
    _cell(last[0], "제품/로트/필름 번호", bold=True)
    _cell(merged_val, image_id)

    # ------------------------------------------------------------
    # 2. 부적합 내용
    # ------------------------------------------------------------
    _bold_line(doc, "2  부적합 내용 (What / Where / How)")
    t2 = _grid_table(doc, rows=4, cols=2)
    defect_line = _checkbox_line(dominant_class, DEFECT_TYPES + ["기타(_______________)"])
    judge_line = (
        f"AI 판정 확률: {ai_prob:.2f}   /   검사원 최종 판정: {decision}   /   "
        "Grad-CAM 근거 확인 여부: 예"
    )
    severity_line = _checkbox_line(
        "", ["경미(Minor) — 국소 재작업 가능", "중대(Major) — 안전/구조 영향", "치명적(Critical) — 즉시 보고"]
    )
    _cell(t2.cell(0, 0), "부적합 유형", bold=True)
    _cell(t2.cell(0, 1), defect_line)
    _cell(t2.cell(1, 0), "판정 근거", bold=True)
    _cell(t2.cell(1, 1), judge_line)
    _cell(t2.cell(2, 0), "중대성 분류", bold=True)
    _cell(t2.cell(2, 1), severity_line)
    _cell(t2.cell(3, 0), "상세 내용 기술", bold=True)
    _cell(t2.cell(3, 1), "")

    # ------------------------------------------------------------
    # 3. 즉시조치
    # ------------------------------------------------------------
    _bold_line(doc, "3  즉시조치 — ISO 9001 8.7 부적합 출력물 관리")
    t3 = _grid_table(doc, rows=4, cols=2)
    _cell(t3.cell(0, 0), "격리 조치", bold=True)
    _cell(t3.cell(0, 1), _checkbox_line("", ["즉시 격리(Hold)", "라인 정지", "해당없음"]))
    _cell(t3.cell(1, 0), "처리 방법", bold=True)
    _cell(t3.cell(1, 1), _checkbox_line("", ["재작업(Rework)", "특채(Concession)", "폐기(Scrap)", "반품(Return)"]))
    _cell(t3.cell(2, 0), "재작업 방법", bold=True)
    _cell(t3.cell(2, 1), "예: 백가우징 후 재용접 / 그라인딩 후 재검사 (해당 시 기재)")
    _cell(t3.cell(3, 0), "조치자 / 조치일", bold=True)
    _cell(t3.cell(3, 1), "")

    # ------------------------------------------------------------
    # 4. 원인분석
    # ------------------------------------------------------------
    _bold_line(doc, "4  원인분석 — ISO 9001 10.2 부적합 및 시정조치")
    t4 = _grid_table(doc, rows=3, cols=2)
    cause_labels = ["용접전류", "이음부간격", "작업자숙련도", "모재청결도",
                     "실드가스유량", "모재수분/유분", "용접봉건조", "아크길이"]
    _cell(t4.cell(0, 0), "직접원인 (What happened)", bold=True)
    _cell(t4.cell(0, 1), "")
    _cell(t4.cell(1, 0), "근본원인 (Why — 5Why/특성요인)", bold=True)
    _cell(t4.cell(1, 1), "점검 대상: " + "  ".join(f"☐ {c}" for c in cause_labels) + "  ☐ 기타(_______________)")
    _cell(t4.cell(2, 0), "유사 부적합 이력 확인", bold=True)
    _cell(t4.cell(2, 1), _checkbox_line("", ["최초 발생", "반복 발생 — 이전 NCR 번호: ______"]))

    # ------------------------------------------------------------
    # 5. 시정조치 계획
    # ------------------------------------------------------------
    _bold_line(doc, "5  시정조치 계획 (Corrective Action Plan)")
    t5 = _grid_table(doc, rows=4, cols=5)
    for c, head in enumerate(["No", "조치 내용", "담당자", "완료예정일", "상태"]):
        _shade_cell(t5.cell(0, c), "184F95")
        _cell(t5.cell(0, c), head, bold=True, align_center=True)
        t5.cell(0, c).paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for i in range(1, 4):
        _cell(t5.cell(i, 0), str(i), align_center=True)
        for c in range(1, 5):
            _cell(t5.cell(i, c), "")

    # ------------------------------------------------------------
    # 6. 시정조치 효과성 검증
    # ------------------------------------------------------------
    _bold_line(doc, "6  시정조치 효과성 검증 (Verification of Effectiveness)")
    t6 = _grid_table(doc, rows=4, cols=2)
    _cell(t6.cell(0, 0), "검증 방법", bold=True)
    _cell(t6.cell(0, 1), _checkbox_line("", ["재검사(RT)", "후속 로트 모니터링", "SPC 관리도 추적", "기타(_______________)"]))
    _cell(t6.cell(1, 0), "검증 기간", bold=True)
    _cell(t6.cell(1, 1), "____년 __월 __일  ~  ____년 __월 __일")
    _cell(t6.cell(2, 0), "검증 결과", bold=True)
    _cell(t6.cell(2, 1), _checkbox_line("", ["효과 있음(종결)", "효과 미흡(재조치 필요)", "검증 예정"]))
    _cell(t6.cell(3, 0), "검증자 / 검증일", bold=True)
    _cell(t6.cell(3, 1), "")

    # ------------------------------------------------------------
    # 7. 승인
    # ------------------------------------------------------------
    _bold_line(doc, "7  승인 (Approval)")
    t7 = _grid_table(doc, rows=2, cols=4)
    for c, head in enumerate(["작성자", "검토자 (품질팀)", "승인자 (팀장)", "승인일자"]):
        _shade_cell(t7.cell(0, c), "184F95")
        _cell(t7.cell(0, c), head, bold=True, align_center=True)
        t7.cell(0, c).paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for c in range(4):
        _cell(t7.cell(1, c), "")

    foot_p = doc.add_paragraph()
    foot_run = foot_p.add_run(
        "본 양식은 ISO 9001:2015 8.7(부적합한 출력물의 관리) 및 10.2(부적합 및 시정조치) "
        "요구사항에 따라 작성되었습니다. AI 용접부 RT 자동선별 시스템 — 포커스팀"
    )
    _apply_korean(foot_run.font, foot_run._element, size=Pt(8))
    foot_run.italic = True
    foot_p.paragraph_format.space_before = Pt(10)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def ncr_bytes_for_case(item, decision_note: str = "반려(불량)"):
    image_id = item["image_id"]
    dominant_class = item.get("dominant_class") or "기타"
    ai_prob = item.get("calibrated_prob", 0.0)
    docx_bytes = build_ncr_docx(
        image_id=image_id,
        dominant_class=dominant_class,
        ai_prob=ai_prob,
        decision=decision_note,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"NCR_{image_id}_{ts}.docx"
    return docx_bytes, filename
