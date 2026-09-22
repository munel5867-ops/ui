import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report, tab5_model_data, tab6_limits
from tabs.tab3_spc import CORE_KPIS, CRACK_SUSPECT_N, ROUTING_SUMMARY
from utils.dummy_data import spc_daily_defect_rate
from utils.mailer import default_recipient, is_configured, send_email
from utils.priority import six_m_ranking, spc_alert
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import inject_css

st.set_page_config(
    page_title="AI 용접부 RT 결함 자동선별 시스템",
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

    if is_configured():
        with st.popover("🚨 담당자에게 긴급 보고"):
            to = st.text_input("받는 사람 (쉼표로 여러 명 가능)", value=default_recipient(), key="alert_mail_to")
            if st.button("긴급 메일 전송", key="alert_mail_send", type="primary"):
                body = (
                    f"SPC 관리한계 이탈 감지\n\n"
                    f"일자: {alert['date'].strftime('%Y-%m-%d')}\n"
                    f"불량률: {alert['value']:.1%}\n"
                    f"관리상한(UCL): {alert['ucl']:.1%}\n"
                    f"중심선(CL): {alert['cl']:.1%}\n\n"
                    f"대시보드의 6M 원인 스크리닝 결과를 확인해 즉시 조치 바랍니다."
                )
                try:
                    send_email("[긴급] RT 검사 SPC 관리한계 이탈 경보", body, to)
                    st.success(f"{to} 로 긴급 보고 메일을 전송했습니다.")
                except Exception as e:
                    st.error(f"전송 실패: {e}")
    else:
        st.caption("긴급 메일 전송을 쓰려면 `.streamlit/secrets.toml`에 SMTP 설정이 필요합니다.")

st.markdown(
    """
    <div class="rt-header">
        <h1>🔍 AI 용접부 RT 결함 자동선별 시스템</h1>
        <p>AI 자동 판정 · SPC 실시간 모니터링 · 2조</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("thresholds", dict(DEFAULT_THRESHOLDS))
thresholds = st.session_state["thresholds"]

total_n = sum(r["n"] for r in ROUTING_SUMMARY)
human_review_n = ROUTING_SUMMARY[2]["n"]
automation_rate = CORE_KPIS[0][1]

resolved_n = len(st.session_state.get("resolved_queue_items", {}))

k1, k2, k3, k4 = st.columns(4)
k1.metric("금일 검사 물량", f"{total_n:,}건")
k2.metric("자동화율", f"{automation_rate:.1%}")
k3.metric("사람확인 대기", f"{human_review_n:,}건", f"균열의심 {CRACK_SUSPECT_N}건 우선", delta_color="off")
k4.metric(
    "오늘 처리 완료",
    f"{resolved_n}건",
    help="검사자가 사람확인 대기열에서 최종 승인/반려로 확정한 건수 (① 오늘의 현황 탭 기준)",
)

st.divider()

# 탭(가로) 대신 사이드바 메뉴(세로)로 페이지를 전환한다. st.tabs는 선택 안 한 탭도
# 매번 다 계산·렌더링하지만(숨기기만 함), 이 방식은 선택된 페이지만 실행해서
# 더 가볍기도 하다.
PAGES = {
    "① 오늘의 현황": tab3_spc.render,
    "② 판정 데모": tab1_inference.render,
    "③ 임계값 조절": tab2_threshold.render,
    "④ 모델·데이터 검증": tab5_model_data.render,
    "⑤ 한계·조치": tab6_limits.render,
    "⑥ 자동보고서": tab4_report.render,
}

with st.sidebar:
    st.markdown("### 📋 메뉴")
    selected_page = st.radio("페이지 선택", list(PAGES.keys()), label_visibility="collapsed")

PAGES[selected_page]()
