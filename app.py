import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report
from tabs.tab3_spc import CORE_KPIS, CRACK_SUSPECT_N, ROUTING_SUMMARY
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import inject_css

st.set_page_config(
    page_title="RT 용접부 결함 판독 · 자동 판정 보조 시스템",
    page_icon="🔍",
    layout="wide",
)

inject_css()

st.markdown(
    """
    <div class="rt-header">
        <h1>🔍 RT 용접부 결함 판독 · 자동 판정 보조 시스템</h1>
        <p>STAGE4 운영 데모 · STAGE5 SPC 모니터링 · 2조 · 포커스</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# 상단 고정 요약 바 — 어느 탭에 있든 관리자가 1초 만에 오늘 상황을 파악할 수 있게.
# (①오늘의 현황 탭의 상세 내용과 같은 확정 결과 기준, 임계값만 ③탭 조절값을 반영)
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

# "오늘의 현황"(구 STAGE5 대시보드)을 첫 화면으로 — 발표 시작하자마자
# 처리 현황/자동배출 숫자가 바로 보이는 게 가시성이 더 좋다는 팀 판단.
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
