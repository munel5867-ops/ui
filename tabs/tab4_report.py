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
    d1_miss_count = round(total_count * kpis["d1_miss_rate"])
    d4_miss_count = round(total_count * kpis["d4_miss_rate"])
    anomaly_note = "SPC p-chart에서 UCL 초과 이상점 1건 발생 → 원인분석 필요 (더미 데이터 기준)."
    recommendation = "미용착(D4) 검출 임계값(CONFIDENT_T) 재검토 권장."

    st.markdown(
        f"""
<div style="background:#fff;border:1px solid #e6e6ea;border-radius:8px;padding:18px;font-size:13px;line-height:1.7;color:#444;">
<h4 style="margin:0 0 8px;font-size:14px;">RT 결함 판독 시스템 — 주간 리포트 ({period_start.isoformat()} ~ {period_end.isoformat()})</h4>
총 검사 물량: {total_count:,}건 &nbsp;|&nbsp; 자동화율: {kpis['automation_rate']:.1%} &nbsp;|&nbsp; 사람 확인: {human_review_count:,}건<br>
D1(균열) 미검출: {d1_miss_count}건 &nbsp;|&nbsp; D4(미용착) 미검출: {d4_miss_count}건<br><br>
<b>이상 신호:</b> {anomaly_note}<br>
<b>권고사항:</b> {recommendation}
<br><br>
<span style="color:#bbb;font-size:12px;">(python-docx로 자동 생성되는 실제 보고서 내용 — 아래 버튼으로 다운로드 가능)</span>
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
        d1_miss_count=d1_miss_count,
        d4_miss_count=d4_miss_count,
        anomaly_note=anomaly_note,
        recommendation=recommendation,
    )

    st.download_button(
        "⬇ .docx로 다운로드",
        data=docx_bytes,
        file_name=f"weekly_report_{period_end.isoformat()}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
