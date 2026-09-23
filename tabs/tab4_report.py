from datetime import date, timedelta

import streamlit as st

from utils.dummy_data import load_validation_predictions
from utils.mail_ui import render_send_email_popover
from utils.report import weekly_report_bytes
from utils.routing import DEFAULT_THRESHOLDS, compute_kpis


def render():
    st.subheader("주간 자동보고서 미리보기")

    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)
    df = load_validation_predictions()
    kpis = compute_kpis(df, thresholds)

    period_end = date.today()
    period_start = period_end - timedelta(days=6)
    total_count = 3214  # TODO: 실제 이번 주 검사 물량 집계로 교체
    human_review_count = round(total_count * kpis["human_review_rate"])
    margin_hold_count = round(total_count * kpis["margin_hold_rate"])
    d1_miss_count = round(total_count * kpis["d1_miss_rate"])
    d4_miss_count = round(total_count * kpis["d4_miss_rate"])
    anomaly_note = "SPC p-chart에서 UCL 초과 이상점 1건 발생 → 원인분석이 필요합니다."
    recommendation = (
        f"세부유형 확정 margin 기준(현재 {thresholds['margin_threshold']:.0f}) 재검토를 권장합니다."
    )

    with st.container(border=True):
        st.markdown(
            f"""
<div style="border-left:4px solid #2a78d6;padding:4px 0 4px 14px;font-size:16px;line-height:1.8;color:#333;">
<h4 style="margin:0 0 10px;font-size:18px;color:#184f95;">RT 결함 판독 시스템 — 주간 리포트 ({period_start.isoformat()} ~ {period_end.isoformat()})</h4>
총 검사 물량: <b>{total_count:,}건</b> &nbsp;|&nbsp; 자동화율: <b>{kpis['automation_rate']:.1%}</b> &nbsp;|&nbsp; 사람 확인: <b>{human_review_count:,}건</b><br>
Margin 부족 보류: {margin_hold_count}건 &nbsp;|&nbsp; 균열(D1) 미검출: {d1_miss_count}건 &nbsp;|&nbsp; 용입불량(D4) 미검출: {d4_miss_count}건<br><br>
<b>이상 신호:</b> {anomaly_note}<br>
<b>권고사항:</b> {recommendation}
</div>
""",
            unsafe_allow_html=True,
        )

    # 탭3(오늘의 현황)과 완전히 같은 로직·같은 양식(NCR 스타일)으로 통일된 공용 함수.
    # 여기서 직접 docx를 다시 만들지 않고 그 함수 하나만 호출한다 — 두 곳이 따로
    # 만들면 한쪽만 고쳤을 때 양식이 어긋나는 문제(이번에 난 ImportError의 원인)가 재발한다.
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