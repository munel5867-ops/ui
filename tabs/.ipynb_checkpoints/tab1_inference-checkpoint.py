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

HISTORY_MAX = 30  # 세션 내내 무한정 쌓이지 않게 최근 것만 유지
HISTORY_SHOW = 10  # 화면에 한 번에 보여줄 개수 (스트림릿엔 진짜 드래그 스크롤이 없어서 최근 N장만 나란히)
HISTORY_THUMB_PX = 84  # 이력 칸의 썸네일은 작게 — 위쪽 '현재 판정 대상' 큰 이미지와 구분
IMG_MAX_WIDTH_PX = 340  # 원본/Grad-CAM 박스 최대 폭 — 컬럼을 꽉 채우지 않고 적당히 작게


def _boxed_image(img, caption: str | None = None):
    """원본 사진과 Grad-CAM 오버레이를 나란히 놓아도 높이가 어긋나지 않게 한다.
    둘 다 실제로는 227x227 정사각형이라, 박스를 고정 픽셀 높이가 아니라
    '항상 정사각형(aspect-ratio 1:1)'으로 맞춘다 — 컬럼 폭이 같으니 높이도
    자동으로 같아지고, 정사각형 원본을 정사각형 박스에 넣으니 잘리지도 않는다.
    최대 폭(IMG_MAX_WIDTH_PX)을 둬서 컬럼을 꽉 채우지 않고 가운데 정렬로 작게 보이게 한다.
    <img> 태그는 Streamlit 기본 CSS(height:auto 등)에 덮어써지는 경우가 있어,
    그걸 피하려고 배경이미지(div + background-image)로 렌더링한다."""
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


def _thumbnail_bytes(raw_bytes: bytes, size: int = HISTORY_THUMB_PX) -> bytes:
    """이력 칸에 넣을 작은 썸네일로 축소. 원본은 227x227이라 축소해도 화질 문제 없음."""
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
    """검사자의 최종 확인 결과를 로컬 CSV에 기록 — 나중에 재학습용 라벨 후보로 쓸 수 있는
    최소 형태의 피드백 루프. 실시간 DB는 아니고 로컬 파일이라 이 컴퓨터에서만 쌓인다."""
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
                source,
                status,
                label or "",
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

        row1_col1, row1_col2 = st.columns(2)

        with row1_col1:
            with st.container(border=True):
                st.subheader("원본 사진")
                if pil_image is not None:
                    _boxed_image(pil_image, caption="현재 판정 대상")
                else:
                    st.caption("샘플을 클릭하거나 이미지를 업로드하면 판정 결과가 표시됩니다.")

        with row1_col2:
            with st.container(border=True):
                st.subheader("2. Grad-CAM 오버레이")
                overlay, gradcam_info = (None, None)
                if pil_image is not None:
                    overlay, gradcam_info = rt_model.gradcam_overlay(pil_image)

                if overlay is not None:
                    _boxed_image(overlay, caption=f"🔴 모델 주목 위치 · 예측: {gradcam_info}")
                else:
                    if pil_image is not None and gradcam_info:
                        st.warning("⚠ 모델 가중치를 찾을 수 없어 더미 히트맵으로 대체합니다.")
                    else:
                        st.caption("이미지 선택 전 — 더미 히트맵 표시 중")
                    _boxed_image(make_mock_gradcam_overlay())

        with st.container(border=True):
            st.subheader("3. 판정 결과")

            probs = None
            if pil_image is not None:
                probs = get_or_compute(
                    image_bytes, lambda: rt_model.predict_ensemble(pil_image)
                )

            if probs is None:
                if pil_image is not None:
                    st.warning("⚠ 모델 가중치가 없어 데모 고정값으로 대체합니다.")
                probs = demo_single_prediction()

            st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

            st.subheader("4. 라우팅 결과")
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
                    st.session_state["history"].append(
                        {
                            "name": current_name,
                            "thumb": _thumbnail_bytes(image_bytes),
                            "probs": probs,
                            "status": status,
                            "label": label,
                        }
                    )
                    st.session_state["history"] = st.session_state["history"][-HISTORY_MAX:]

        if pil_image is not None and status in ("attention", "attention_crack", "attention_margin"):
            with st.container(border=True):
                st.subheader("5. 검사자 최종 확인")
                st.caption("AI가 애매하다고 본 건만 — 검사자 결정을 기록합니다 (재학습 라벨 후보).")
                if st.session_state["demo_playing"]:
                    st.info("자동재생 중에는 기록하지 않습니다 — ⏸ 눌러서 멈춘 뒤 확정해 주세요.")
                b1, b2 = st.columns(2)
                if b1.button("✅ 승인 · 양품 확정", key="approve_btn", width="stretch",
                              disabled=st.session_state["demo_playing"]):
                    _log_decision(source, probs, status, label, "승인(양품)")
                    st.success("기록됨 — 양품 확정")
                if b2.button("⛔ 반려 · 불량 확정", key="reject_btn", width="stretch",
                              disabled=st.session_state["demo_playing"]):
                    _log_decision(source, probs, status, label, "반려(불량)")
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
                            + (f" ({rec['label']})" if rec.get("label") else "")
                        )

        if st.session_state["demo_playing"] and batch:
            st.session_state["demo_idx"] = (st.session_state["demo_idx"] + 1) % len(batch)

    _demo_panel()