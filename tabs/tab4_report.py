import streamlit as st

from utils.mail_ui import render_send_email_popover
from utils.report import weekly_report_bytes, weekly_report_summary
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import BRAND_BLUE, BRAND_NAVY

AUTO_BG = "#e8f4fc"     # 시스템 자동 입력 칸
EXAMPLE_BG = "#f2f2f0"  # 참고용 예시 칸 (실제 시스템 출력 아님)
MANUAL_BG = "#fff4e0"   # 담당자 작성 칸
MANUAL_FG = "#b26b00"


def _row(no, title, kind, content_html, manual_text, stripe):
    """kind: "auto"(시스템이 실제로 채우는 값) 또는 "example"(담당자가 채울 항목이
    어떤 모습일지 보여주는 참고용 예시 — AI가 실제로 판단·확정한 값이 아님을
    표시하려고 "예시" 라벨과 다른 색·기울임체를 쓴다)."""
    bg = "#f5f6f8" if stripe else "#ffffff"
    if kind == "auto":
        content_cell = (
            f'<td style="padding:10px 12px;background:{AUTO_BG};font-size:16px;'
            f'line-height:1.7">{content_html}</td>'
        )
    else:
        content_cell = (
            f'<td style="padding:10px 12px;background:{EXAMPLE_BG};font-size:16px;'
            f'line-height:1.7;font-style:italic;color:#5b5a55">'
            f'<span style="font-style:normal;font-weight:700;color:#8a8880">[예시] </span>'
            f'{content_html}</td>'
        )
    return (
        f'<tr style="background:{bg}">'
        f'<td style="padding:10px 8px;text-align:center">'
        f'<span style="display:inline-block;width:30px;height:30px;line-height:30px;border-radius:50%;'
        f'background:{BRAND_BLUE};color:#fff;font-size:16px;font-weight:700">{no}</span></td>'
        f'<td style="padding:10px 12px;font-size:16px;font-weight:700;white-space:nowrap">{title}</td>'
        f'{content_cell}'
        f'<td style="padding:10px 12px;background:{MANUAL_BG};color:{MANUAL_FG};font-size:16px;'
        f'font-weight:600;line-height:1.7">{manual_text}</td>'
        '</tr>'
    )


def render():
    st.subheader("주간 자동보고서 미리보기")

    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)
    # 다운로드 파일(weekly_report_bytes)과 완전히 같은 값 — 화면과 파일이 어긋나지 않도록
    # 둘 다 utils/report.py의 weekly_report_summary() 하나에서 값을 받는다.
    s = weekly_report_summary(thresholds)

    st.markdown(
        f'<div style="border-left:4px solid {BRAND_BLUE};background:#eef6fc;padding:12px 16px;'
        f'border-radius:8px;font-size:16px;line-height:1.8;margin-bottom:14px">'
        f'<b style="color:{BRAND_NAVY}">보고 기간 {s["period_start"].isoformat()} ~ {s["period_end"].isoformat()}'
        f' · 문서번호 {s["report_no"]}</b><br>'
        '주간 집계값은 양식의 해당 칸에 맞춰 시스템이 자동으로 채우고, '
        '사람이 판단해야 하는 항목은 빈칸으로 두어 담당자가 직접 작성합니다.'
        '</div>',
        unsafe_allow_html=True,
    )

    auto1 = (
        f'발견일자: <b>{s["period_end"].isoformat()}</b><br>'
        f'보고번호: <b>{s["report_no"]}</b><br>'
        '검사방법: RT(방사선투과검사) / AI 1차 판정 + 검사원 확인<br>'
        f'제품/로트/필름 번호: <b>{s["product_text"]}</b>'
    )
    auto2 = (
        f'부적합 유형: <b>☑ {s["dominant"]}</b> '
        f'(미검출 건수가 더 많은 쪽 — 균열(D1) {s["d1_miss_count"]}건 · 용입불량(D4) {s["d4_miss_count"]}건)<br>'
        f'판정 근거: AI 판정 확률 칸 <b>{s["automation_rate"]:.2f}</b> '
        f'(= 이번 주 자동화율 {s["automation_rate"]:.1%}) / '
        f'검사원 최종 판정 <b>{s["decision"]}</b> / Grad-CAM 근거 확인 여부 <b>예</b>'
    )

    example3 = (
        "격리 조치: 즉시 격리(Hold) / 처리 방법: 재작업(Rework)<br>"
        "재작업 방법: 백가우징 후 재용접 / 조치자·조치일: 미기재(담당자 작성)"
    )
    example4 = (
        "직접원인: 용접 전류값 이탈 의심 / 근본원인 점검 대상: 용접전류 · 이음부간격<br>"
        "유사 부적합 이력: 최초 발생 또는 이전 NCR 번호 기재"
    )
    example5 = "1) 용접기 전류 캘리브레이션 재점검 — 담당자·완료예정일은 담당자가 확정"
    example6 = (
        "검증 방법: 재검사(RT) + 후속 로트 모니터링<br>"
        "검증 기간·검증 결과: 검증 완료 후 담당자가 기재"
    )
    example7 = "작성자: 품질팀 담당자 / 검토자·승인자·승인일자: 결재선 확정 후 기재"

    rows = [
        (1, "부적합 식별 정보", "auto", auto1, "발견 공정/단계 · 발견자 · 소속부서"),
        (2, "부적합 내용", "auto", auto2, "중대성 분류(경미/중대/치명적) · 상세 내용 기술"),
        (3, "즉시조치 (8.7)", "example", example3, "격리 조치 · 처리 방법 · 재작업 방법 · 조치자/조치일"),
        (4, "원인분석 (10.2)", "example", example4, "직접원인 · 근본원인 점검 대상 체크 · 유사 부적합 이력"),
        (5, "시정조치 계획", "example", example5, "조치 내용 · 담당자 · 완료예정일 · 상태 (3행)"),
        (6, "효과성 검증", "example", example6, "검증 방법 · 검증 기간 · 검증 결과 · 검증자/검증일"),
        (7, "승인", "example", example7, "작성자 · 검토자(품질팀) · 승인자(팀장) · 승인일자"),
    ]
    head_style = (f'padding:10px 12px;background:{BRAND_NAVY};color:#fff;font-size:16px;'
                  'font-weight:700;text-align:left')
    table_html = (
        '<div style="overflow-x:auto">'
        '<table style="width:100%;border-collapse:collapse;border:1px solid #e1e4e8">'
        '<tr>'
        f'<th style="{head_style};text-align:center;width:56px">No</th>'
        f'<th style="{head_style};width:170px">섹션</th>'
        f'<th style="{head_style}">시스템 자동 입력</th>'
        f'<th style="{head_style};width:30%">담당자 직접 작성</th>'
        '</tr>'
        + "".join(_row(no, t, k, c, m, i % 2 == 1) for i, (no, t, k, c, m) in enumerate(rows))
        + '</table></div>'
    )
    with st.container(border=True):
        st.markdown(table_html, unsafe_allow_html=True)
        st.caption("[예시] 표시된 3~7번 섹션은 담당자가 채울 항목이 어떤 모습일지 보여주는 참고용 "
                   "예시일 뿐입니다 — AI가 원인을 확정하면 안 되므로, 실제 다운로드되는 문서에서는 "
                   "즉시조치·원인분석·시정조치·검증·승인 항목이 전부 빈칸으로 나갑니다 "
                   "(근본원인 체크박스도 빈칸).")

    docx_bytes, docx_name = weekly_report_bytes(thresholds)

    c1, c2 = st.columns([1, 1])
    with c1:
        st.download_button(
            "⬇ .docx로 다운로드",
            data=docx_bytes,
            file_name=docx_name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
        )
    with c2:
        render_send_email_popover(
            docx_bytes, docx_name,
            subject="[RT 검사] 주간 자동보고서",
            body="첨부된 주간 자동보고서를 확인해 주세요. (대시보드에서 자동 생성됨)",
            key_prefix="weekly_tab4",
            label="✉️ 메일로 전송",
        )
