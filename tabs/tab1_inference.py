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
    "auto_reject": "판정 근거: 균열·용입불량(D1+D4) 또는 기공 확률이 임계값 초과",
    "auto_pass": "판정 근거: 무결함 확률 임계값 초과",
    "attention": "판정 근거: 애매 구간 (임계값 미도달)",
}

STATUS_ICON = {
    "auto_pass": "✅ 자동 통과",
    "attention": "⚠ 사람 확인",
    "auto_reject": "⛔ 자동 배출",
}

HISTORY_MAX = 30
HISTORY_SHOW = 10
HISTORY_THUMB_PX = 84


def _thumbnail_bytes(raw_bytes: bytes, size: int = HISTORY_THUMB_PX) -> bytes:
    img = Image.open(io.BytesIO(raw_bytes)).convert("L")
    img.thumbnail((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_samples():
    if not SAMPLES_DIR.exists():
        return []
    exts = {".png", ".jpg", ".jpeg"}
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in exts)


def _log_decision(source: str, probs: dict, status: str, decision: str):
    is_new = not DECISION_LOG.exists()
    with open(DECISION_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(
                ["시각", "이미지출처", "AI판정", "무결함", "균열·용입불량(D1+D4)", "기공(D2)", "검사자결정"]
            )
        writer.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source,
                status,
                f'{probs["무결함"]:.3f}',
                f'{probs["균열·용입불량(D1+D4)"]:.3f}',
                f'{probs["기공(D2)"]:.3f}',
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

    from utils import model as rt_model

    st.session_state.setdefault("demo_idx", 0)
    st.session_state.setdefault("demo_playing", False)
    st.session_state.setdefault("demo_speed", 3.0)

    interval = st.session_state["demo_speed"] if st.session_state["demo_playing"] else None

    @st.fragment(run_every=interval)
    def _demo_panel():
        col1, col2 = st.columns(2)

        with col1:
            with st.container(border=True):
                st.subheader("1. 이미지 선택")

                uploaded_files = st.file_uploader(
                    "이미지 여러 장을 한 번에 선택해서 올리면, 올린 순서대로 넘기며 판정합니다 "
                    "(227×227 grayscale 권장, .png/.jpg)",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key="uploader",
                )

                if uploaded_files:
                    fingerprint = tuple((f.name, f.size) for f in uploaded_files)
                    if st.session_state.get("_upload_fingerprint") != fingerprint:
                        st.session_state["_upload_fingerprint"] = fingerprint
                        st.session_state["demo_idx"] = 0
                        st.session_state["demo_playing"] = False
                    batch = [(f.name, f.getvalue()) for f in uploaded_files]
                    batch_label = "업로드"
                else:
                    st.session_state["_upload_fingerprint"] = None
                    folder_samples = _load_samples()
                    batch = [(p.stem, p.read_bytes()) for p in folder_samples]
                    batch_label = "샘플"

                batch_key = (batch_label, tuple(n for n, _ in batch))
                if st.session_state.get("_hist_batch_key") != batch_key:
                    st.session_state["_hist_batch_key"] = batch_key
                    st.session_state["history"] = []
                    st.session_state["_last_hist_key"] = None

                if batch:
                    st.session_state["demo_idx"] %= len(batch)

                    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1.3, 1.6])
                    if ctrl1.button("◀ 이전", width="stretch", disabled=len(batch) < 2, key="prev_btn"):
                        st.session_state["demo_idx"] = (st.session_state["demo_idx"] - 1) % len(batch)
                        st.session_state["demo_playing"] = False
                    if ctrl2.button("다음 ▶", width="stretch", disabled=len(batch) < 2, key="next_btn"):
                        st.session_state["demo_idx"] = (st.session_state["demo_idx"] + 1) % len(batch)
                        st.session_state["demo_playing"] = False
                    play_label = "⏸ 일시정지" if st.session_state["demo_playing"] else "▶ 자동재생"
                    if ctrl3.button(play_label, type="primary", width="stretch",
                                     disabled=len(batch) < 2, key="play_btn"):
                        st.session_state["demo_playing"] = not st.session_state["demo_playing"]
                    st.session_state["demo_speed"] = ctrl4.slider(
                        "속도(초)", min_value=1.0, max_value=10.0,
                        value=st.session_state["demo_speed"], step=0.5,
                        format="%.1f초", label_visibility="collapsed",
                        key="speed_slider",
                    )

                    status_txt = "자동재생 중" if st.session_state["demo_playing"] else "일시정지"
                    current_name, image_bytes = batch[st.session_state["demo_idx"]]
                    st.caption(
                        f"{st.session_state['demo_idx'] + 1} / {len(batch)} ({batch_label}) · {status_txt} · "
                        f"{st.session_state['demo_speed']:.1f}초 간격 · {current_name}"
                    )
                    source = f"{batch_label}:{current_name}"
                else:
                    st.caption(
                        f"위에 이미지를 여러 장 올리거나, `{SAMPLES_DIR.name}/` 폴더에 대표 이미지를 "
                        "넣어두면 여기서 순서대로 넘기며 판정합니다."
                    )
                    image_bytes = None
                    source = "unknown"

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

                probs, missing, breakdown = (None, None, None)
                if pil_image is not None:
                    probs, missing, breakdown = rt_model.predict_ensemble(pil_image)

                if probs is None:
                    if pil_image is not None:
                        st.warning("⚠ 모델 가중치가 없어 데모 고정값으로 대체합니다.")
                    probs = demo_single_prediction()

                st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

                st.subheader("3. 라우팅 결과")
                status = classify(
                    probs["무결함"], probs["균열·용입불량(D1+D4)"], probs["기공(D2)"], thresholds
                )
                st.markdown(status_badge(status), unsafe_allow_html=True)
                st.caption(REASON[status])
                if breakdown is not None and status in ("attention", "auto_reject"):
                    st.caption(
                        f"세부 추정 (참고용, 판정에는 반영 안 됨): "
                        f"균열(D1) {breakdown['균열(D1) 추정']:.0%} · "
                        f"용입불량(D4) {breakdown['용입불량(D4) 추정']:.0%}"
                    )

                if pil_image is not None:
                    hist_key = (batch_key, st.session_state["demo_idx"])
                    if st.session_state.get("_last_hist_key") != hist_key:
                        st.session_state["_last_hist_key"] = hist_key
                        st.session_state.setdefault("history", [])
                        st.session_state["history"].append(
                            {
                                "name": current_name,
                                "thumb": _thumbnail_bytes(image_bytes),
                                "probs": probs,
                                "status": status,
                            }
                        )
                        st.session_state["history"] = st.session_state["history"][-HISTORY_MAX:]

            if pil_image is not None and status == "attention":
                with st.container(border=True):
                    st.subheader("4. 검사자 최종 확인")
                    st.caption("AI가 애매하다고 본 건만 — 검사자 결정을 기록합니다 (재학습 라벨 후보).")
                    if st.session_state["demo_playing"]:
                        st.info("자동재생 중에는 기록하지 않습니다 — ⏸ 눌러서 멈춘 뒤 확정해 주세요.")
                    b1, b2 = st.columns(2)
                    if b1.button("✅ 승인 · 양품 확정", key="approve_btn", width="stretch",
                                  disabled=st.session_state["demo_playing"]):
                        _log_decision(source, probs, status, "승인(양품)")
                        st.success("기록됨 — 양품 확정")
                    if b2.button("⛔ 반려 · 불량 확정", key="reject_btn", width="stretch",
                                  disabled=st.session_state["demo_playing"]):
                        _log_decision(source, probs, status, "반려(불량)")
                        st.success("기록됨 — 불량 확정")
                    if DECISION_LOG.exists():
                        n = sum(1 for _ in open(DECISION_LOG, encoding="utf-8-sig")) - 1
                        st.caption(f"지금까지 기록된 검사자 결정: {n}건 (`decision_log.csv`, 이 컴퓨터에만 저장)")

        history = st.session_state.get("history", [])
        if history:
            st.divider()
            with st.container(border=True):
                st.subheader("판정 이력 (이번 세션에서 본 사진들)")
                recent = history[-HISTORY_SHOW:]
                skipped = len(history) - len(recent)
                st.caption(
                    (f"전체 {len(history)}장 중 최근 {len(recent)}장 표시 · " if skipped > 0 else "")
                    + "왼쪽이 먼저 본 것, 오른쪽이 가장 최근"
                )
                hcols = st.columns(len(recent))
                for j, rec in enumerate(recent):
                    with hcols[j]:
                        st.image(rec["thumb"], width=HISTORY_THUMB_PX)
                        top_label = max(rec["probs"], key=rec["probs"].get)
                        top_val = rec["probs"][top_label]
                        st.caption(
                            f"**{rec['name']}**  \n"
                            f"{top_label} {top_val:.0%}  \n"
                            f"{STATUS_ICON.get(rec['status'], rec['status'])}"
                        )

        if st.session_state["demo_playing"] and batch:
            st.session_state["demo_idx"] = (st.session_state["demo_idx"] + 1) % len(batch)

    _demo_panel()
