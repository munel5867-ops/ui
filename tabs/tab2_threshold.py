import pandas as pd
import streamlit as st

from utils.dummy_data import load_validation_predictions
from utils.routing import DEFAULT_THRESHOLDS, compute_kpis


def _linked_slider_number(label, dict_key, thresholds, min_value, max_value, step=0.01, fmt="%.2f"):
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
            step=step, format=fmt, key=slider_key, on_change=_on_slider_change,
        )
    with col_b:
        st.number_input(
            "직접 입력", min_value=min_value, max_value=max_value,
            step=step, format=fmt, key=number_key, on_change=_on_number_change,
            label_visibility="collapsed",
        )

    thresholds[dict_key] = st.session_state[slider_key]
    return thresholds[dict_key]


def render():
    st.session_state.setdefault("thresholds", dict(DEFAULT_THRESHOLDS))
    thresholds = st.session_state["thresholds"]
    for _k, _v in DEFAULT_THRESHOLDS.items():
        thresholds.setdefault(_k, _v)

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("라우팅 임계값 조절")
            st.caption("균열·용입불량 점수로 1차 선별하고, 유형 AI확신도가 부족하면 추정 유형과 함께 사람 확인으로 보냅니다.")
            _linked_slider_number("CRACK_T (균열·용입불량 1차 선별 기준)", "crack_t", thresholds, 0.00, 1.00,
                                  step=0.0001, fmt="%.4f")
            _linked_slider_number("AI확신도 (균열/용입불량 확정 기준, %)", "margin_threshold", thresholds, 0.0, 100.0, step=1.0)

    with col2:
        with st.container(border=True):
            st.subheader("실시간 성능 지표")
            df = load_validation_predictions()
            kpis = compute_kpis(df, thresholds)

            m1, m2 = st.columns(2)
            m1.metric("자동화율", f"{kpis['automation_rate']:.1%}")
            m2.metric("사람 확인 비율", f"{kpis['human_review_rate']:.1%}")

            m3, m4 = st.columns(2)
            m3.metric("D1(균열) 미검출률", f"{kpis['d1_miss_rate']:.1%}",
                       delta=None if kpis["d1_miss_rate"] == 0 else "주의", delta_color="inverse")
            m4.metric("D4(용입불량) 미검출률", f"{kpis['d4_miss_rate']:.1%}",
                       delta=None if kpis["d4_miss_rate"] == 0 else "주의", delta_color="inverse")

            m5, m6 = st.columns(2)
            m5.metric("AI확신도 부족으로 보류된 비율", f"{kpis['margin_hold_rate']:.1%}")

            st.caption(f"검증셋 {kpis['n']:,}건 기준 (현재 더미 검증셋)")

    with st.expander("📊 비용기반 임계값 매트릭스 (참고자료 — 펼쳐서 보기)"):
        st.caption(
            "통합보고서 STAGE3 기준 실측값입니다 (EfficientNetB0 finetune · filmopt OOF 15,348장, "
            "3클래스 교차보정 + Saerens 운영 불량률 1%). 위 CRACK_T 기본값 0.3781은 이 표의 3:1 행입니다."
        )
        cost_matrix = pd.DataFrame({
            "비용비(미검:과검)": ["3:1", "5:1", "10:1", "20:1", "30:1", "50:1"],
            "임계값": [0.3781, 0.2161, 0.0003, 0.0001, 0.0001, 0.0000],
            "재현율": [0.9582, 0.9624, 0.9905, 0.9943, 0.9943, 0.9979],
            "정밀도": [0.9652, 0.9481, 0.7912, 0.7477, 0.7477, 0.6910],
            "오경보율": [0.0348, 0.0531, 0.2635, 0.3382, 0.3382, 0.4498],
            "운영 특성": ["정밀도 우선", "", "재현율 우선", "", "", "미검출 최소화"],
        })
        st.dataframe(
            cost_matrix.style.format({
                "임계값": "{:.4f}", "재현율": "{:.2%}", "정밀도": "{:.2%}", "오경보율": "{:.2%}",
            }),
            width="stretch", hide_index=True, height=250,
        )
        st.caption(
            "3:1(정밀도 우선)이 현재 기본값입니다. 10:1(재현율 우선)부터는 오경보율이 26.35%로 급격히 올라가고, "
            "50:1에서는 44.98%까지 올라갑니다."
        )
        st.caption("기공(D2)은 균열·용입불량 점수가 임계값 미만일 때 기공 vs 양품 비교로 판정하며, 비용비 스윕 대상이 아닙니다.")
