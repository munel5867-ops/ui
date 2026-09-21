import streamlit as st

from utils.dummy_data import load_validation_predictions
from utils.routing import DEFAULT_THRESHOLDS, compute_kpis


def _linked_slider_number(label, dict_key, thresholds, min_value, max_value, step=0.01):
    """슬라이더 + 숫자입력창을 나란히 두고 서로 값이 항상 같게 동기화한다.
    둘 중 어느 쪽을 바꿔도 thresholds[dict_key]에 즉시 반영됨."""
    slider_key = f"{dict_key}_slider"
    number_key = f"{dict_key}_number"

    if slider_key not in st.session_state:
        st.session_state[slider_key] = thresholds[dict_key]
    if number_key not in st.session_state:
        st.session_state[number_key] = thresholds[dict_key]

    def _on_slider_change():
        st.session_state[number_key] = st.session_state[slider_key]

    def _on_number_change():
        v = min(max(st.session_state[number_key], min_value), max_value)
        st.session_state[number_key] = v
        st.session_state[slider_key] = v

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.slider(
            label, min_value, max_value,
            step=step, key=slider_key, on_change=_on_slider_change,
        )
    with col_b:
        st.number_input(
            "직접 입력", min_value=min_value, max_value=max_value,
            step=step, format="%.2f", key=number_key, on_change=_on_number_change,
            label_visibility="collapsed",
        )

    thresholds[dict_key] = st.session_state[slider_key]
    return thresholds[dict_key]


def render():
    st.session_state.setdefault("thresholds", dict(DEFAULT_THRESHOLDS))
    thresholds = st.session_state["thresholds"]

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("라우팅 임계값 조절")
            st.caption("균열(D1)·미용착(D4)을 하나의 판정 범주로 통합해 적용합니다.")
            _linked_slider_number("ND_CONFIDENT (무결함 자동통과 기준)", "nd_confident", thresholds, 0.50, 1.00)
            _linked_slider_number(
                "CRACK_OR_LOP_T (균열·용입불량 통합 자동배출 기준)", "crack_or_lop_t", thresholds, 0.00, 0.50
            )
            _linked_slider_number("POROSITY_T (기공 자동배출 기준)", "porosity_t", thresholds, 0.30, 0.90)

    with col2:
        with st.container(border=True):
            st.subheader("실시간 성능 지표")
            df = load_validation_predictions()
            kpis = compute_kpis(df, thresholds)

            m1, m2 = st.columns(2)
            m1.metric("자동화율", f"{kpis['automation_rate']:.1%}")
            m2.metric("사람 확인 비율", f"{kpis['human_review_rate']:.1%}")

            m3, m4 = st.columns(2)
            m3.metric("균열·용입불량 미검출률", f"{kpis['crack_or_lop_miss_rate']:.1%}",
                       delta=None if kpis["crack_or_lop_miss_rate"] == 0 else "주의", delta_color="inverse")
            m4.metric("기공 미검출률", f"{kpis['porosity_miss_rate']:.1%}",
                       delta=None if kpis["porosity_miss_rate"] == 0 else "주의", delta_color="inverse")

            st.caption(f"검증셋 {kpis['n']:,}건 기준 (현재 더미 검증셋)")
