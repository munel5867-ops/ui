from datetime import date, timedelta

import streamlit as st

from utils.dummy_data import load_validation_predictions
from utils.report import build_weekly_report_docx
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
    crack_or_lop_miss_count = round(total_count * kpis["crack_or_lop_miss_rate"])
    porosity_miss_count = round(total_count * kpis["porosity_miss_rate"])
    anomaly_note = "SPC p-chart에서 UCL 초과 이상점 1건 발생 → 원인분석 필요."
    recommendation = "균열·용입불량(D1+D4) 통합 임계값(CRACK_OR_LOP_T) 재검토 권장."

    with st.container(border=True):
        st.markdown(
            f"""
<div style="border-left:4px solid #2a78d6;padding:4px 0 4px 14px;font-size:13px;line-height:1.8;color:#333;">
<h4 style="margin:0 0 10px;font-size:15px;color:#184f95;">RT 결함 판독 시스템 — 주간 리포트 ({period_start.isoformat()} ~ {period_end.isoformat()})</h4>
총 검사 물량: <b>{total_count:,}건</b> &nbsp;|&nbsp; 자동화율: <b>{kpis['automation_rate']:.1%}</b> &nbsp;|&nbsp; 사람 확인: <b>{human_review_count:,}건</b><br>
균열·용입불량(D1+D4) 미검출: {crack_or_lop_miss_count}건 &nbsp;|&nbsp; 기공(D2) 미검출: {porosity_miss_count}건<br><br>
<b>이상 신호:</b> {anomaly_note}<br>
<b>권고사항:</b> {recommendation}
</div>
""",
            unsafe_allow_html=True,
        )

    docx_bytes = build_weekly_report_docx(
        period_start=period_start,
        period_end=period_end,
        total_count=total_count,
        automation_rate=kpis["automation_rate"],
        human_review_count=human_review_count,
        crack_or_lop_miss_count=crack_or_lop_miss_count,
        porosity_miss_count=porosity_miss_count,
        anomaly_note=anomaly_note,
        recommendation=recommendation,
    )

    st.download_button(
        "⬇ .docx로 다운로드",
        data=docx_bytes,
        file_name=f"weekly_report_{period_end.isoformat()}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
