import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report

st.set_page_config(
    page_title="RT 용접부 결함 판독 · 자동 판정 보조 시스템",
    page_icon="🔍",
    layout="wide",
)

st.info(
    "⚠️ 스켈레톤 단계 — Grad-CAM/검증셋/SPC 이력은 아직 더미 데이터입니다. "
    "실제 모델·데이터 연동 전까지는 레이아웃/흐름 확인용으로만 사용하세요.",
    icon="⚠️",
)

st.title("🔍 RT 용접부 결함 판독 · 자동 판정 보조 시스템")
st.caption("STAGE4 운영 데모 | STAGE5 SPC 모니터링 | 2조 · 포커스")

tab1, tab2, tab3, tab4 = st.tabs(
    ["① 판정 데모", "② 임계값 조절", "③ STAGE5 대시보드", "④ 자동보고서"]
)

with tab1:
    tab1_inference.render()

with tab2:
    tab2_threshold.render()

with tab3:
    tab3_spc.render()

with tab4:
    tab4_report.render()
