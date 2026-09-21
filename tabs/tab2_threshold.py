import pandas as pd
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

    st.divider()
    st.subheader("비용기반 임계값 매트릭스")
    st.caption(
        "STAGE3 최종 보고서(2026-09-19) 기준 실측값입니다. 이진은 기저모델(백본 동결), "
        "균열·용입불량(D1+D4)은 현재 배포 중인 미세조정+증강 모델 기준입니다."
    )
    cost_matrix = pd.DataFrame({
        "비용비(미검:과검)": ["3:1", "5:1", "10:1", "20:1", "50:1", "100:1"],
        "이진 임계값": [0.0008, 0.0005, 0.0004, 0.0002, 0.0002, 0.0001],
        "이진 재현율": [0.9879, 0.9925, 0.9940, 0.9985, 0.9985, 1.0000],
        "이진 오경보율": [0.0889, 0.1391, 0.1892, 0.6393, 0.6393, 0.9731],
        "균열·용입불량 임계값": [0.2823, 0.2258, 0.0002, 0.0002, 0.0001, 0.0000],
        "균열·용입불량 재현율": [0.9598, 0.9639, 0.9934, 0.9968, 0.9988, 0.9996],
        "균열·용입불량 오경보율": [0.0262, 0.0398, 0.2518, 0.2964, 0.3641, 0.4139],
    })
    st.dataframe(
        cost_matrix.style.format({
            "이진 임계값": "{:.4f}", "이진 재현율": "{:.2%}", "이진 오경보율": "{:.2%}",
            "균열·용입불량 임계값": "{:.4f}", "균열·용입불량 재현율": "{:.2%}", "균열·용입불량 오경보율": "{:.2%}",
        }),
        width="stretch", hide_index=True,
    )
    st.caption(
        "3:1~5:1 구간이 실용적 운영 범위입니다. 10:1을 넘어가면 오경보율이 급격히 상승해 "
        "실질적 의미가 줄어듭니다 (자세한 근거는 STAGE3 최종 보고서 참고). "
        "현재 기본값(CRACK_OR_LOP_T=0.2823)은 비용비 3:1 기준 최종 채택값입니다."
    )
    st.caption("기공(D2)은 형태학적으로 명확히 구분되는 결함이라 이번 비용기반 스윕 대상에서 제외되었습니다.")
