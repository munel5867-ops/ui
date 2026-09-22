import base64
import csv
import io
from datetime import datetime
from pathlib import Path

import numpy as np
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
    "auto_pass": "판정 근거: 무결함 확률 임계값 초과",
    "attention_crack": "판정 근거: 균열·용입불량이 둘 다 의심 수준으로 높음 — 안전장치로 사람 확인",
    "auto_reject": "판정 근거: 균열/용입불량 확률이 임계값을 넘고, margin도 충분해 세부유형까지 확정",
    "attention_margin": "판정 근거: 임계값은 넘었지만 균열/용입불량 확신도(margin)가 부족해 사람 확인",
    "attention": "판정 근거: 애매 구간 (임계값 미도달)",
}

STATUS_ICON = {
    "auto_pass": "✅ 자동 통과",
    "attention": "⚠ 사람 확인",
    "attention_crack": "⚠ 사람 확인 · 균열계열 의심",
    "attention_margin": "⚠ 사람 확인 · 균열/용입불량 경계 모호",
    "auto_reject": "⛔ 자동 배출",
}

HISTORY_MAX = 30
HISTORY_SHOW = 10
HISTORY_THUMB_PX = 168  # 기본(84)의 2배
IMG_MAX_WIDTH_PX = 300  # 3칸 구조라 살짝 줄임


def _boxed_image(img, caption: str | None = None):
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    st.markdown(
        f'<div style="width:100%;max-width:{IMG_MAX_WIDTH_PX}px;aspect-ratio:1/1;'
        f'margin:0 auto;border-radius:8px;'
        f'background-image:url(data:image/png;base64,{b64});'
        f'background-size:cover;background-position:center;"></div>',
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(caption)


def _centered_image_html(title, img, caption_text, box_h, caption_color=None):
    """제목+사진+캡션을 한 덩어리 HTML로 만들어 고정 높이 박스 안에서 위아래·좌우
    모두 중앙 정렬한다. 위젯을 나중에 따로 그려서 감싸려 하면(별도 st 호출들 사이에
    div를 열고 닫는 방식) 실제로 안 감싸지므로, 처음부터 한 번의 st.markdown 호출
    안에 전부 담는다."""
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    color = caption_color or "var(--text-secondary)"
    inner_h = box_h - 60
    return (
        f'<div style="height:{inner_h}px;display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;gap:10px;text-align:center">'
        f'<h3 style="margin:0;font-size:1.15rem;font-weight:600">{title}</h3>'
        f'<div style="width:100%;max-width:260px;aspect-ratio:1/1;border-radius:8px;'
        f'background-image:url(data:image/png;base64,{b64});'
        f'background-size:cover;background-position:center;"></div>'
        f'<p style="font-size:0.82rem;color:{color};margin:0">{caption_text}</p>'
        f'</div>'
    )


def _centered_placeholder_html(title, text, box_h):
    inner_h = box_h - 60
    return (
        f'<div style="height:{inner_h}px;display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;gap:10px;text-align:center">'
        f'<h3 style="margin:0;font-size:1.15rem;font-weight:600">{title}</h3>'
        f'<p style="font-size:0.85rem;color:var(--text-secondary);margin:0">{text}</p>'
        f'</div>'
    )


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


def _log_decision(source: str, probs: dict, status: str, label: str | None, decision: str):
    is_new = not DECISION_LOG.exists()
    with open(DECISION_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(
                ["시각", "이미지출처", "AI판정", "AI세부유형", "무결함", "균열(D1)", "기공(D2)", "용입불량(D4)", "검사자결정"]
            )
        writer.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source, status, label or "",
                f'{probs["무결함"]:.3f}',
                f'{probs["균열(D1)"]:.3f}',
                f'{probs["기공(D2)"]:.3f}',
                f'{probs["용입불량(D4)"]:.3f}',
                decision,
            ]
        )


def _prob_bar_chart(probs: dict) -> go.Figure:
    labels = list(probs.keys())
    values = list(probs.values())
    colors = [CLASS_COLORS.get(l, "#2a78d6") for l in labels]
    fig = go.Figure(
        go.Bar(x=values, y=labels, orientation="h", marker_color=colors,
               text=[f"{v:.2f}" for v in values], textposition="outside")
    )
    fig.update_layout(
        xaxis=dict(range=[0, 1], title=None, gridcolor="#e1e0d9"),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=10, r=30, t=10, b=10), height=150,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render():
    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)

    from utils import model as rt_model
    from utils.inference_cache import get_or_compute

    st.session_state.setdefault("demo_idx", 0)
    st.session_state.setdefault("demo_playing", False)
    st.session_state.setdefault("demo_speed", 3.0)

    interval = st.session_state["demo_speed"] if st.session_state["demo_playing"] else None

    @st.fragment(run_every=interval)
    def _demo_panel():
        with st.container(border=True):
            st.subheader("1. 이미지 선택")

            uploaded_files = st.file_uploader(
                "이미지 여러 장을 한 번에 선택해서 올리면, 올린 순서대로 넘기며 판정합니다 "
                "(227×227 grayscale 권장, .png/.jpg)",
                type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="uploader",
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
                    format="%.1f초", label_visibility="collapsed", key="speed_slider",
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

        BOX_H = 420  # 세 칸 다 이 높이로 고정 — 내용 양과 무관하게 크기 동일

        col1, col2, col3 = st.columns(3)

        with col1:
            with st.container(height=BOX_H, border=True):
                if pil_image is not None:
                    st.markdown(_centered_image_html("원본 사진", pil_image, "현재 판정 대상", BOX_H),
                                unsafe_allow_html=True)
                else:
                    st.markdown(_centered_placeholder_html("원본 사진",
                                "샘플을 클릭하거나 이미지를 업로드하면 판정 결과가 표시됩니다.", BOX_H),
                                unsafe_allow_html=True)

        with col2:
            with st.container(height=BOX_H, border=True):
                overlay, gradcam_info = (None, None)
                if pil_image is not None:
                    overlay, gradcam_info = rt_model.gradcam_overlay(pil_image)

                if overlay is not None:
                    cap, cap_color = f"🔴 모델 주목 위치 · 예측: {gradcam_info}", None
                    st.markdown(_centered_image_html("Grad-CAM 오버레이", overlay, cap, BOX_H, cap_color),
                                unsafe_allow_html=True)
                else:
                    if pil_image is not None and gradcam_info:
                        cap, cap_color = "⚠ 모델 가중치를 찾을 수 없어 더미 히트맵으로 대체합니다.", "#B8860B"
                    else:
                        cap, cap_color = "이미지 선택 전 — 더미 히트맵 표시 중", None
                    st.markdown(
                        _centered_image_html("Grad-CAM 오버레이", make_mock_gradcam_overlay(), cap, BOX_H, cap_color),
                        unsafe_allow_html=True,
                    )

        with col3:
            with st.container(height=BOX_H, border=True):
                st.subheader("판정 결과")

                probs = None
                if pil_image is not None:
                    probs = get_or_compute(image_bytes, lambda: rt_model.predict_ensemble(pil_image))

                if probs is None:
                    if pil_image is not None:
                        st.warning("⚠ 모델 가중치가 없어 데모 고정값으로 대체합니다.")
                    probs = demo_single_prediction()

                st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

                status, label = classify(
                    probs["무결함"], probs["균열(D1)"], probs["용입불량(D4)"], thresholds
                )
                badge_html = status_badge(status)
                if label:
                    badge_html += f' <span style="margin-left:8px;font-weight:700;">→ {label}</span>'
                st.markdown(badge_html, unsafe_allow_html=True)
                st.caption(REASON[status])

                if pil_image is not None:
                    hist_key = (batch_key, st.session_state["demo_idx"])
                    if st.session_state.get("_last_hist_key") != hist_key:
                        st.session_state["_last_hist_key"] = hist_key
                        st.session_state.setdefault("history", [])
                        st.session_state["history"].append({
                            "name": current_name, "thumb": _thumbnail_bytes(image_bytes),
                            "probs": probs, "status": status, "label": label,
                        })
                        st.session_state["history"] = st.session_state["history"][-HISTORY_MAX:]

                if pil_image is not None and status in ("attention", "attention_crack", "attention_margin"):
                    st.divider()
                    st.caption("AI가 애매하다고 본 건만 — 검사자 결정을 기록합니다 (재학습 라벨 후보).")
                    if st.session_state["demo_playing"]:
                        st.info("자동재생 중에는 기록하지 않습니다 — ⏸ 눌러서 멈춘 뒤 확정해 주세요.")
                    b1, b2 = st.columns(2)
                    if b1.button("✅ 승인", key="approve_btn", width="stretch",
                                  disabled=st.session_state["demo_playing"]):
                        _log_decision(source, probs, status, label, "승인(양품)")
                        st.success("기록됨 — 양품 확정")
                    if b2.button("⛔ 반려", key="reject_btn", width="stretch",
                                  disabled=st.session_state["demo_playing"]):
                        _log_decision(source, probs, status, label, "반려(불량)")
                        st.success("기록됨 — 불량 확정")
                    if DECISION_LOG.exists():
                        n = sum(1 for _ in open(DECISION_LOG, encoding="utf-8-sig")) - 1
                        st.caption(f"검사자 결정 누적: {n}건 (`decision_log.csv`)")

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
                            + (f" ({rec['label']})" if rec.get("label") else "")
                        )

        if st.session_state["demo_playing"] and batch:
            st.session_state["demo_idx"] = (st.session_state["demo_idx"] + 1) % len(batch)

    _demo_panel()
