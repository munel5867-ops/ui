import streamlit as st

from tabs import tab1_inference, tab2_threshold, tab3_spc, tab4_report, tab5_model_data, tab6_limits
from tabs.tab3_spc import CORE_KPIS, CRACK_SUSPECT_N, ROUTING_SUMMARY
from utils.dummy_data import spc_daily_defect_rate
from utils.mailer import default_recipient, is_configured, send_email
from utils.priority import six_m_ranking, spc_alert
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import BRAND_BLUE, BRAND_NAVY, inject_css

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
    <div class="rt-header-sticky-wrap">
        <div class="rt-header">
            <h1>🔍 AI 용접부 RT 결함 자동선별 시스템</h1>
            <p>AI 자동 판정 · SPC 실시간 모니터링 · 2조</p>
        </div>
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


def _kpi_card(label, value, icon, icon_bg, note=None, progress_pct=None):
    bottom_html = ""
    if progress_pct is not None:
        bottom_html = (
            f'<div style="height:6px;border-radius:3px;background:#eef0f2;margin-top:10px;overflow:hidden">'
            f'<div style="height:100%;width:{progress_pct * 100:.0f}%;background:{icon_bg};border-radius:3px"></div>'
            f'</div>'
        )
    elif note:
        bottom_html = f'<p style="font-size:13px;color:var(--text-muted);margin:10px 0 0">{note}</p>'
    else:
        # note/progress가 없는 카드도 아래 여백이 같아야 네 장 높이가 동일하게 맞음
        bottom_html = '<div style="height:19px"></div>'
    return (
        '<div style="background:#fff;border-radius:16px;padding:18px 20px;'
        'box-shadow:0 1px 4px rgba(0,0,0,0.07);height:128px;'
        'display:flex;flex-direction:column;justify-content:space-between;box-sizing:border-box;">'
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
        '<div>'
        f'<p style="font-size:15px;color:var(--text-secondary);margin:0;font-weight:600">{label}</p>'
        f'<p style="font-size:28px;font-weight:800;margin:6px 0 0">{value}</p>'
        '</div>'
        f'<div style="width:42px;height:42px;border-radius:12px;background:{icon_bg}22;'
        'display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0">'
        f'{icon}</div>'
        '</div>'
        f'{bottom_html}'
        '</div>'
    )


k1, k2, k3, k4 = st.columns(4)
k1.markdown(_kpi_card("금일 검사 물량", f"{total_n:,}건", "📋", BRAND_NAVY), unsafe_allow_html=True)
k2.markdown(_kpi_card("자동화율", f"{automation_rate:.1%}", "⚡", "#0ca30c",
                       progress_pct=automation_rate), unsafe_allow_html=True)
k3.markdown(_kpi_card("사람확인 대기", f"{human_review_n:,}건", "🔍", "#eda100",
                       note=f"균열의심 {CRACK_SUSPECT_N}건 우선"), unsafe_allow_html=True)
k4.markdown(_kpi_card("오늘 처리 완료", f"{resolved_n}건", "✅", BRAND_BLUE,
                       note="검사자가 최종 승인/반려로 확정한 건수"), unsafe_allow_html=True)

st.divider()

# 탭(가로) 대신 사이드바 메뉴(세로)로 페이지를 전환한다. st.tabs는 선택 안 한 탭도
# 매번 다 계산·렌더링하지만(숨기기만 함), 이 방식은 선택된 페이지만 실행해서
# 더 가볍기도 하다.

# 탭(가로) 대신 사이드바 메뉴(세로)로 페이지를 전환한다. st.tabs는 선택 안 한 탭도
# 매번 다 계산·렌더링하지만(숨기기만 함), 이 방식은 선택된 페이지만 실행해서
# 더 가볍기도 하다.
PAGES = {
    "오늘의 현황": tab3_spc.render,
    "판정 데모": tab1_inference.render,
    "임계값 조절": tab2_threshold.render,
    "모델·데이터 검증": tab5_model_data.render,
    "한계·조치": tab6_limits.render,
    "자동보고서": tab4_report.render,
}
PAGE_ICONS = {
    # 색이 있는 이모지(📊🔍 등)는 어두운 사이드바 테마와 안 어울려서, 앱 다른
    # 곳(☀ 입력 밝기, ⚠ 경고배너)과 톤을 맞춘 단색 기호로 바꿈. "\ufe0e"는
    # 이모지 대신 텍스트(단색) 형태로 그리라는 지시자.
    "오늘의 현황": "▦",
    "판정 데모": "◎",
    "임계값 조절": "⚙\ufe0e",
    "모델·데이터 검증": "☑\ufe0e",
    "한계·조치": "⚠\ufe0e",
    "자동보고서": "▤",
}

# 전에 쓰던 streamlit-option-menu는 iframe 안에서 그려지는 외부 컴포넌트라,
# 이 페이지의 CSS(여백 제거, sticky 등)가 그 안까지 닿지 않는 근본적인 한계가
# 있었다. 그래서 순수 Streamlit 버튼으로 다시 만든다 — iframe이 없으니
# 이 파일의 CSS로 완전히 제어된다.
st.session_state.setdefault("current_page", list(PAGES.keys())[0])

with st.sidebar:
    st.markdown('<p class="rt-sidebar-title">🔍 AI RT 자동선별</p>', unsafe_allow_html=True)
    for label in PAGES:
        is_active = st.session_state["current_page"] == label
        if st.button(
            f"{PAGE_ICONS[label]}  {label}",
            key=f"nav_{label}",
            width="stretch",
            type="primary" if is_active else "secondary",
        ):
            st.session_state["current_page"] = label
            st.rerun()

PAGES[st.session_state["current_page"]]()
