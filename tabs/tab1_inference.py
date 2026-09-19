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

HISTORY_MAX = 30  # 세션 내내 무한정 쌓이지 않게 최근 것만 유지
HISTORY_SHOW = 10  # 화면에 한 번에 보여줄 개수 (스트림릿엔 진짜 드래그 스크롤이 없어서 최근 N장만 나란히)
HISTORY_THUMB_PX = 84  # 이력 칸의 썸네일은 작게 — 위쪽 '현재 판정 대상' 큰 이미지와 구분


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


def _log_decision(source: str, probs: dict, status: str, decision: str):
    """검사자의 최종 확인 결과를 로컬 CSV에 기록 — 나중에 재학습용 라벨 후보로 쓸 수 있는
    최소 형태의 피드백 루프. 실시간 DB는 아니고 로컬 파일이라 이 컴퓨터에서만 쌓인다."""
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

    # 실제 모델(TensorFlow/Keras) 연동 모듈. weights/ 폴더에 가중치 파일이 없으면
    # import 자체는 되지만 load_fold_models()가 빈 리스트를 돌려주고, 이 화면은
    # 자동으로 더미 데이터로 대체 표시한다 (앱이 죽지 않음).
    from utils import model as rt_model

    st.session_state.setdefault("demo_idx", 0)
    st.session_state.setdefault("demo_playing", False)
    st.session_state.setdefault("demo_speed", 3.0)

    # 자동재생 중일 때만 간격(초)을 넣어서 fragment가 그 주기로 스스로 다시 그려지게 한다.
    # 이 값 자체를 재생 여부에 따라 매번 새로 계산해서 데코레이터에 넘기는 방식 —
    # Streamlit 공식 패턴(자동재생 on/off 토글)과 동일. 꺼져 있으면 run_every=None이라
    # 그냥 보통 위젯처럼 사용자가 조작할 때만 다시 그려진다 (페이지 전체가 멈추지 않음).
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
                    # 업로드된 파일 목록 자체가 바뀌면(새로 여러 장 올리면) 처음(0번)부터
                    # 다시 보여주고 재생은 멈춰둔다. 같은 파일 그대로면(다른 위젯 조작으로
                    # 인한 재실행) 지금 보고 있던 위치를 유지.
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

                # 업로드/샘플 묶음이 통째로 바뀌면(다른 파일들로 교체) 이전 세트의 이력은
                # 더 이상 의미가 없으니 비운다. 같은 묶음 안에서 넘기는 동안은 유지.
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

                probs, missing = (None, None)
                if pil_image is not None:
                    probs, missing = rt_model.predict_ensemble(pil_image)

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

                # 방금 본 이미지를 이력에 기록 — 같은 이미지(같은 idx)에서 위젯만 건드려
                # 재실행된 경우엔 중복으로 쌓이지 않게 (batch_key, idx) 조합으로 구분.
                # 원본이 아니라 축소된 썸네일 + 확률/라우팅 결과까지 같이 저장해서, 이력 칸에서
                # 사진과 판정 결과를 한 번에 볼 수 있게 한다.
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

        # 자동재생 타이머로 인한 재실행이면, 화면을 다 그린 다음 다음 인덱스로 넘겨서
        # 다음 tick 때 새 이미지가 보이게 한다 (그려주는 시점과 넘기는 시점을 분리해서
        # '방금 본 이미지'가 잠깐이라도 먼저 눈에 들어오게 함).
        if st.session_state["demo_playing"] and batch:
            st.session_state["demo_idx"] = (st.session_state["demo_idx"] + 1) % len(batch)

    _demo_panel()
