import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report
from tabs.tab3_spc import CORE_KPIS, CRACK_SUSPECT_N, ROUTING_SUMMARY
from utils.dummy_data import spc_daily_defect_rate
from utils.priority import six_m_ranking, spc_alert
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import inject_css

st.set_page_config(
    page_title="RT 용접부 결함 판독 · 자동 판정 보조 시스템",
    page_icon="🔍",
    layout="wide",
)

inject_css()

alert = spc_alert(spc_daily_defect_rate())
if alert["breached"]:
    st.markdown(
        f'<div class="rt-alert-banner">⚠ <b>관리한계 이탈 감지</b> — '
        f'{alert["date"].strftime("%Y-%m-%d")} 불량률 {alert["value"]:.1%} '
        f'(UCL {alert["ucl"]:.1%} 초과)</div>',
        unsafe_allow_html=True,
    )
    with st.expander("6M 원인 스크리닝 요약 보기"):
        st.dataframe(six_m_ranking(), width="stretch", hide_index=True)

st.markdown(
    """
    <div class="rt-header">
        <h1>🔍 RT 용접부 결함 판독 · 자동 판정 보조 시스템</h1>
        <p>AI 자동 판정 · SPC 실시간 모니터링 · 2조</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# 상단 고정 요약 바 — 어느 탭에 있든 관리자가 1초 만에 오늘 상황을 파악할 수 있게.
st.session_state.setdefault("thresholds", dict(DEFAULT_THRESHOLDS))
thresholds = st.session_state["thresholds"]

total_n = sum(r["n"] for r in ROUTING_SUMMARY)
human_review_n = ROUTING_SUMMARY[2]["n"]
automation_rate = CORE_KPIS[0][1]

k1, k2, k3, k4 = st.columns(4)
k1.metric("금일 검사 물량", f"{total_n:,}건")
k2.metric("자동화율", f"{automation_rate:.1%}")
k3.metric("사람확인 대기", f"{human_review_n:,}건", f"균열의심 {CRACK_SUSPECT_N}건 우선", delta_color="off")
k4.metric(
    "자동배출 임계값 (균열·용입불량/기공)",
    f"{thresholds['crack_or_lop_t']:.2f} / {thresholds['porosity_t']:.2f}",
)

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(
    ["① 오늘의 현황", "② 판정 데모", "③ 임계값 조절", "④ 자동보고서"]
)

with tab1:
    tab3_spc.render()

with tab2:
    tab1_inference.render()

with tab3:
    tab2_threshold.render()

with tab4:
    tab4_report.render()
