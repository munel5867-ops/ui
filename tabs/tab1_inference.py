import csv
import io
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.dummy_data import demo_single_prediction, make_mock_gradcam_overlay
from utils.routing import DEFAULT_THRESHOLDS, classify
from utils.style import CLASS_COLORS, status_badge

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples"
DECISION_LOG = PROJECT_ROOT / "decision_log.csv"

REASON = {
    "attention_crack": "판정 근거: D1·D4 확률 동시 임계값 초과",
    "auto_reject": "판정 근거: 결함 확률 최댓값 임계값 초과",
    "auto_pass": "판정 근거: 무결함 확률 임계값 초과",
    "attention": "판정 근거: 애매 구간 (임계값 미도달)",
}


def _load_samples():
    if not SAMPLES_DIR.exists():
        return []
    exts = {".png", ".jpg", ".jpeg"}
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in exts)


def _log_decision(source: str, probs: dict, status: str, decision: str):
    """검사자의 최종 확인 결과를 로컬 CSV에 기록 — 나중에 재학습용 라벨 후보로 쓸 수 있는
    최소 형태의 피드백 루프. 실시간 DB는 아니고 로컬 파일이라 이 컴퓨터에서만 쌓인다."""
    is_new = not DECISION_LOG.exists()
    with open(DECISION_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(
                ["시각", "이미지출처", "AI판정", "무결함", "균열(D1)", "기공(D2)", "미용착(D4)", "검사자결정"]
            )
        writer.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source,
                status,
                f'{probs["무결함"]:.3f}',
                f'{probs["균열(D1)"]:.3f}',
                f'{probs["기공(D2)"]:.3f}',
                f'{probs["미용착(D4)"]:.3f}',
                decision,
            ]
        )


def _prob_bar_chart(probs: dict) -> go.Figure:
    labels = list(probs.keys())
    values = list(probs.values())
    colors = [CLASS_COLORS.get(l, "#2a78d6") for l in labels]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.2f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis=dict(range=[0, 1], title=None, gridcolor="#e1e0d9"),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=10, r=30, t=10, b=10),
        height=180,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
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
        with st.container(border=True):
            st.subheader("1. 이미지 선택")

            samples = _load_samples()
            if samples:
                st.caption("샘플 클릭 한 번으로 바로 시연 (발표용)")
                scols = st.columns(len(samples))
                for i, path in enumerate(samples):
                    with scols[i]:
                        st.image(str(path), width="stretch")
                        if st.button(path.stem, key=f"sample_{i}", width="stretch"):
                            st.session_state["demo_image_bytes"] = path.read_bytes()
                            st.session_state["demo_image_source"] = f"샘플:{path.stem}"
                st.divider()
            else:
                st.caption(
                    f"`{SAMPLES_DIR.name}/` 폴더에 대표 이미지 3~5장을 넣으면 "
                    "여기에 클릭용 썸네일이 자동으로 생김."
                )

            uploaded = st.file_uploader(
                "직접 업로드도 가능 (227×227 grayscale, .png/.jpg)",
                type=["png", "jpg", "jpeg"],
            )
            if uploaded is not None:
                st.session_state["demo_image_bytes"] = uploaded.getvalue()
                st.session_state["demo_image_source"] = f"업로드:{uploaded.name}"

            image_bytes = st.session_state.get("demo_image_bytes")
            pil_image = Image.open(io.BytesIO(image_bytes)) if image_bytes else None

            if pil_image is not None:
                st.image(pil_image, caption="현재 판정 대상", width="stretch")
            else:
                st.caption("샘플을 클릭하거나 이미지를 업로드하면 판정 결과가 표시됩니다.")

        with st.container(border=True):
            st.subheader("Grad-CAM 오버레이")
            overlay, gradcam_info = (None, None)
            if pil_image is not None:
                overlay, gradcam_info = rt_model.gradcam_overlay(pil_image)

            if overlay is not None:
                st.image(overlay, width="stretch")
                st.caption(f"🔴 모델 주목 위치 · 예측: {gradcam_info}")
            else:
                if pil_image is not None and gradcam_info:
                    st.warning("⚠ 모델 가중치를 찾을 수 없어 더미 히트맵으로 대체합니다.")
                else:
                    st.caption("이미지 선택 전 — 더미 히트맵 표시 중")
                st.image(make_mock_gradcam_overlay(), width="stretch")

    with col2:
        with st.container(border=True):
            st.subheader("2. 판정 결과")

            probs, missing = (None, None)
            if pil_image is not None:
                probs, missing = rt_model.predict_ensemble(pil_image)

            if probs is None:
                if pil_image is not None:
                    st.warning("⚠ 모델 가중치가 없어 데모 고정값으로 대체합니다.")
                probs = demo_single_prediction()

            st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

            st.subheader("3. 라우팅 결과")
            status = classify(probs["무결함"], probs["균열(D1)"], probs["미용착(D4)"], thresholds)
            st.markdown(status_badge(status), unsafe_allow_html=True)
            st.caption(REASON[status])

        if pil_image is not None and status in ("attention", "attention_crack"):
            with st.container(border=True):
                st.subheader("4. 검사자 최종 확인")
                st.caption("AI가 애매하다고 본 건만 — 검사자 결정을 기록합니다 (재학습 라벨 후보).")
                b1, b2 = st.columns(2)
                source = st.session_state.get("demo_image_source", "unknown")
                if b1.button("✅ 승인 · 양품 확정", key="approve_btn", width="stretch"):
                    _log_decision(source, probs, status, "승인(양품)")
                    st.success("기록됨 — 양품 확정")
                if b2.button("⛔ 반려 · 불량 확정", key="reject_btn", width="stretch"):
                    _log_decision(source, probs, status, "반려(불량)")
                    st.success("기록됨 — 불량 확정")
                if DECISION_LOG.exists():
                    n = sum(1 for _ in open(DECISION_LOG, encoding="utf-8-sig")) - 1
                    st.caption(f"지금까지 기록된 검사자 결정: {n}건 (`decision_log.csv`, 이 컴퓨터에만 저장)")
