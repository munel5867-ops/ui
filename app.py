import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report
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
