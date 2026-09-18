import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.dummy_data import demo_single_prediction, make_mock_gradcam_overlay
from utils.routing import DEFAULT_THRESHOLDS, classify

BADGE_STYLE = {
    "auto_pass": ("✅ 자동 통과", "#21a366"),
    "auto_reject": ("⛔ 자동 배출(거부)", "#e03e3e"),
    "attention": ("⚠ 사람 확인 필요", "#e8a33d"),
    "attention_crack": ("⚠ 사람 확인 필요 — 균열계열 의심", "#e8a33d"),
}


def _prob_bar_chart(probs: dict) -> go.Figure:
    labels = list(probs.keys())
    values = list(probs.values())
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color="#ff4b4b",
            text=[f"{v:.2f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis=dict(range=[0, 1], title=None),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=10, r=30, t=10, b=10),
        height=180,
    )
    return fig


def render():
    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)

    # 실제 모델(TensorFlow/Keras) 연동 모듈. weights/ 폴더에 가중치 파일이 없으면
    # import 자체는 되지만 load_fold_models()가 빈 리스트를 돌려주고, 이 화면은
    # 자동으로 더미 데이터로 대체 표시한다 (앱이 죽지 않음).
    from utils import model as rt_model

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("1. 이미지 업로드")
        uploaded = st.file_uploader(
            "RT 이미지를 업로드하세요 (227×227 grayscale, .png/.jpg)",
            type=["png", "jpg", "jpeg"],
        )

        pil_image = None
        if uploaded is not None:
            pil_image = Image.open(uploaded)
            st.image(pil_image, caption="업로드한 원본 이미지", width="stretch")
        else:
            st.caption("이미지를 업로드하면 실제 모델 판정 결과가 여기 표시됩니다. (지금은 데모용 고정 결과)")

        st.subheader("Grad-CAM 오버레이")
        overlay, gradcam_info = (None, None)
        if pil_image is not None:
            overlay, gradcam_info = rt_model.gradcam_overlay(pil_image)

        if overlay is not None:
            st.image(overlay, width="stretch")
            st.caption(f"🔴 5-fold 앙상블 평균 기준, 모델이 주목한 위치 (예측: {gradcam_info})")
        else:
            if pil_image is not None and gradcam_info:
                st.warning(
                    "⚠ 모델 가중치 파일(`weights/efficientnetb0_filmopt_fold0~4_last.weights.h5`)"
                    "을 찾을 수 없어 더미 히트맵으로 대체합니다. 프로젝트의 `weights/` 폴더에 "
                    "5개 파일을 넣어주세요."
                )
            else:
                st.caption("⚠ 이미지를 업로드하기 전 상태 — 아래는 위치만 보여주는 더미 히트맵입니다.")
            st.image(make_mock_gradcam_overlay(), width="stretch")

    with col2:
        st.subheader("2. 판정 결과")

        probs, missing = (None, None)
        if pil_image is not None:
            probs, missing = rt_model.predict_ensemble(pil_image)

        if probs is None:
            if pil_image is not None:
                st.warning("⚠ 모델 가중치가 없어 실제 판정을 할 수 없습니다. 데모 고정값으로 대체합니다.")
            probs = demo_single_prediction()

        st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

        st.subheader("3. 3단계 라우팅 결과")
        status = classify(probs["무결함"], probs["균열(D1)"], probs["미용착(D4)"], thresholds)
        label, color = BADGE_STYLE[status]
        st.markdown(
            f'<span style="background:{color};color:#fff;padding:5px 14px;'
            f'border-radius:20px;font-size:13px;font-weight:700;">{label}</span>',
            unsafe_allow_html=True,
        )

        if status == "attention_crack":
            st.caption(
                f"D1·D4 확률이 둘 다 임계값(ATTENTION_T={thresholds['attention_t']:.2f}) 이상이라 "
                "균열계열 의심으로 분류 — 자동 배출/통과 대신 검사자 확인으로 라우팅됨."
            )
        elif status == "auto_reject":
            st.caption(
                f"결함 확률 최댓값이 임계값(CONFIDENT_T={thresholds['confident_t']:.2f}) 이상이라 자동 배출."
            )
        elif status == "auto_pass":
            st.caption(
                f"무결함 확률이 임계값(ND_CONFIDENT={thresholds['nd_confident']:.2f}) 이상이라 자동 통과."
            )
        else:
            st.caption("어느 조건에도 확실히 해당하지 않아 사람 확인으로 라우팅됨.")

        st.caption("(2탭에서 임계값을 바꾸면 이 판정도 즉시 바뀝니다)")
