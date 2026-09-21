import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.decisions import log_decision
from utils.mail_ui import render_send_email_popover
from utils.dummy_data import load_validation_predictions, make_mock_gradcam_overlay, spc_daily_defect_rate
from utils.priority import build_priority_queue, score_real_samples
from utils.report import weekly_report_bytes
from utils.routing import DEFAULT_THRESHOLDS, classify
from utils.samples import image_for_id, load_samples
from utils.style import CLASS_COLORS, STATUS_COLORS, status_badge, status_tag

ROUTING_SUMMARY = [
    {"label": "자동통과", "n": 1194, "pct": 0.194, "status": "auto_pass"},
    {"label": "자동배출(세부확정)", "n": 2100, "pct": 0.342, "status": "auto_reject"},
    {"label": "사람확인", "n": 2846, "pct": 0.464, "status": "attention"},
]
CRACK_SUSPECT_N = 204
CORE_KPIS = [
    ("자동화율", 0.341, "자동통과 + margin>=90 자동배출 기준 (TODO: 실측치로 교체)"),
    ("D1(균열) 미검출", 0.0, "TODO: 실측치로 교체"),
    ("D4(용입불량) 미검출", 0.012, "TODO: 실측치로 교체"),
]


def _routing_pie():
    labels = [r["label"] for r in ROUTING_SUMMARY]
    values = [r["n"] for r in ROUTING_SUMMARY]
    colors = [STATUS_COLORS[r["status"]]["bg"] for r in ROUTING_SUMMARY]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, marker_colors=colors, hole=0.5,
        textinfo="percent", textfont=dict(size=18),
    ))
    fig.update_layout(
        height=480, margin=dict(l=10, r=10, t=10, b=40), showlegend=True,
        legend=dict(orientation="h", y=-0.12, font=dict(size=14)),
    )
    return fig


def _p_chart(df):
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["defect_rate"], mode="lines+markers",
                              line=dict(color="#2a78d6", width=2), marker=dict(size=6), name="불량률"))
    fig.add_hline(y=ucl, line_dash="dash", line_color="#fab219", annotation_text="UCL(+3σ)")
    fig.add_hline(y=cl, line_dash="dot", line_color="#898781", annotation_text="CL")
    outliers = df[df["defect_rate"] > ucl]
    if not outliers.empty:
        fig.add_trace(go.Scatter(x=outliers["date"], y=outliers["defect_rate"], mode="markers+text",
                                  marker=dict(color="#d03b3b", size=10),
                                  text=["이상점"] * len(outliers), textposition="top center", name="이상점"))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10),
                       yaxis=dict(title="불량률", tickformat=".1%", gridcolor="#e1e0d9"),
                       xaxis=dict(gridcolor="#e1e0d9"),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
    return fig


def _fishbone():
    causes = [("용접 전류", 0.75, 0.9), ("이음부 간격", 0.55, 0.9),
              ("작업자 숙련도", 0.55, 0.1), ("모재 청결도", 0.75, 0.1)]
    fig = go.Figure()
    fig.add_shape(type="line", x0=0.05, y0=0.5, x1=0.95, y1=0.5, line=dict(color="#52514e", width=3))
    fig.add_annotation(x=0.98, y=0.5, text="균열(D1)·용입불량(D4)", showarrow=False, xanchor="left")
    for label, cx, cy in causes:
        fig.add_shape(type="line", x0=cx, y0=0.5, x1=cx - 0.15, y1=cy, line=dict(color="#c3c2b7"))
        fig.add_annotation(x=cx - 0.15, y=cy, text=label, showarrow=False, yshift=12 if cy > 0.5 else -12)
    fig.update_xaxes(visible=False, range=[0, 1.15])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _prob_bar_chart(probs):
    labels = list(probs.keys())
    values = list(probs.values())
    colors = [CLASS_COLORS.get(l, "#2a78d6") for l in labels]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=colors,
                            text=[f"{v:.2f}" for v in values], textposition="outside"))
    fig.update_layout(xaxis=dict(range=[0, 1], gridcolor="#e1e0d9"), yaxis=dict(autorange="reversed"),
                       margin=dict(l=10, r=30, t=10, b=10), height=160,
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _render_today_panel():
    """왼쪽 컬럼: 오늘의 처리 현황 (라우팅 파이차트 + 표 + 핵심 KPI)."""
    st.subheader("오늘의 처리 현황")
    st.plotly_chart(_routing_pie(), width="stretch", config={"displayModeBar": False})

    for r in ROUTING_SUMMARY:
        st.markdown(f'{r["label"]} &nbsp;|&nbsp; {r["n"]:,}건 ({r["pct"]:.1%}) &nbsp; {status_tag(r["status"])}',
                    unsafe_allow_html=True)
    st.caption(f'└ 균열계열 의심 — 우선 배정 {CRACK_SUSPECT_N}건')

    st.markdown("<br>", unsafe_allow_html=True)
    for label, val, note in CORE_KPIS:
        st.metric(label, f"{val:.1%}", help=note)


def _dummy_queue_items(thresholds):
    """가중치 미탑재 시 폴백 — 더미 검증셋 기준 예시 큐. 실제 사진과 무관한
    시연용 숫자임을 목록 헤더에서 명확히 경고한다."""
    val_df = load_validation_predictions()
    queue_df = build_priority_queue(val_df, thresholds, top_n=12)
    items = []
    for _, row in queue_df.iterrows():
        items.append({
            "image_id": row["image_id"],
            "path": None,
            "probs": {
                "무결함": row["prob_무결함"],
                "균열(D1)": row["prob_균열(D1)"],
                "기공(D2)": row["prob_기공(D2)"],
                "용입불량(D4)": row["prob_용입불량(D4)"],
            },
            "status": row["status"],
            "ai_label": row["ai_label"],
            "dominant_class": row["dominant_class"],
            "calibrated_prob": row["calibrated_prob"],
            "severity_score": row["severity_score"],
        })
    return items


@st.dialog("케이스 검토", width="large")
def _review_dialog(item, samples):
    _render_review_panel(item, samples)


def _render_review_panel(item, samples):
    from utils.model import gradcam_overlay

    image_id = item["image_id"]
    img_path = item["path"] if item["path"] is not None else image_for_id(image_id, samples)
    pil_image = Image.open(img_path) if img_path else None

    probs = item["probs"]
    status = item["status"]
    label = item.get("ai_label")
    used_dummy = item["path"] is None

    st.markdown(f"#### 🔬 검토: `{image_id}`")
    if used_dummy:
        st.warning("⚠ 모델 가중치 미탑재 — 큐의 예시 확률로 표시 중입니다 (실제 사진 내용과 다를 수 있음).")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**원본 사진**")
        if pil_image is not None:
            st.image(pil_image, width="stretch")
        else:
            st.caption("`samples/` 폴더에 대표 이미지가 없어 표시할 원본이 없습니다.")
    with col2:
        st.markdown("**Grad-CAM 히트맵**")
        overlay = None
        if pil_image is not None:
            with st.spinner("히트맵 생성 중..."):
                overlay, _ = gradcam_overlay(pil_image)
        if overlay is None:
            st.caption("모델 가중치 미탑재 — 더미 히트맵으로 대체")
            st.image(make_mock_gradcam_overlay(), width="stretch")
        else:
            st.image(overlay, width="stretch")

    st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})
    badge_html = status_badge(status)
    if label:
        badge_html += f' <span style="margin-left:8px;font-weight:700;">→ {label}</span>'
    st.markdown(badge_html, unsafe_allow_html=True)
    if not label:
        st.caption("AI가 세부유형(균열/용입불량)을 확신하지 못해 검사자가 직접 판단해야 합니다.")

    b1, b2 = st.columns(2)
    if b1.button("✅ 최종 양품 승인", key=f"approve_{image_id}", width="stretch"):
        log_decision(image_id, probs, status, label, "승인(양품)")
        st.session_state.setdefault("resolved_queue_items", {})[image_id] = "승인(양품)"
        st.success(f"{image_id} — 양품으로 확정 처리되었습니다.")
        st.rerun()
    if b2.button("⛔ 최종 불량 확정", key=f"reject_{image_id}", width="stretch"):
        log_decision(image_id, probs, status, label, "반려(불량)")
        st.session_state.setdefault("resolved_queue_items", {})[image_id] = "반려(불량)"
        st.success(f"{image_id} — 불량으로 확정 처리되었습니다.")
        st.rerun()


def render():
    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)
    samples = load_samples()

    # 가중치가 있으면 samples/ 폴더의 실제 사진을 실제 모델로 채점해서 진짜
    # 애매한(사람 확인 필요) 사진만 심각도순으로 보여준다. 가중치가 없을 때만
    # 더미 검증셋 기준 예시 큐로 폴백한다.
    queue_items = score_real_samples(thresholds)
    using_real = queue_items is not None
    if not using_real:
        queue_items = _dummy_queue_items(thresholds)

    resolved_map = st.session_state.get("resolved_queue_items", {})
    open_items = [it for it in queue_items if it["image_id"] not in resolved_map]

    col_left, col_right = st.columns([1, 1.3])

    with col_left:
        with st.container(border=True):
            _render_today_panel()

    with col_right:
        with st.container(border=True):
            st.header("🔎 사람 확인 대기 · 심각도순")
            if using_real:
                st.caption(
                    "samples/ 폴더 실제 사진을 실제 모델로 채점한 결과입니다 — "
                    "심각도(지배 클래스 위험도 × 확률) 내림차순."
                )
            else:
                st.warning(
                    "⚠ 모델 가중치 미탑재 — 아래는 더미 검증셋 기준 예시 큐입니다 "
                    "(실제 사진과 무관한 시연용 숫자)."
                )

            docx_bytes, docx_name = weekly_report_bytes(thresholds)
            r1, r2, r3 = st.columns([2.4, 1.3, 1.3])
            if resolved_map:
                r1.caption(f"오늘 처리 완료: {len(resolved_map)}건")
            r2.download_button("📄 다운로드", data=docx_bytes, file_name=docx_name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                width="stretch")
            with r3:
                render_send_email_popover(
                    docx_bytes, docx_name,
                    subject="[RT 검사] 주간 자동보고서",
                    body="첨부된 주간 자동보고서를 확인해 주세요. (대시보드에서 자동 생성됨)",
                    key_prefix="weekly_today",
                )

            if not open_items:
                st.success("대기 중인 사람 확인 케이스가 없습니다.")
            else:
                for item in open_items:
                    dom_color = (STATUS_COLORS["attention_crack"]["bg"]
                                 if item["dominant_class"] in ("균열(D1)", "용입불량(D4)")
                                 else STATUS_COLORS["attention"]["bg"])
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([0.4, 2.2, 1.2])
                        c1.markdown(f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
                                    f'background:{dom_color};margin-top:8px;"></span>', unsafe_allow_html=True)
                        c2.markdown(
                            f"**{item['image_id']}** &nbsp;·&nbsp; {item['dominant_class']}  \n"
                            f"확률 {item['calibrated_prob']:.2f} · 심각도 {item['severity_score']:.2f}",
                            unsafe_allow_html=True,
                        )
                        if c3.button("검토하기", key=f"select_{item['image_id']}", width="stretch"):
                            _review_dialog(item, samples)

    st.divider()

    with st.container(border=True):
        st.subheader("SPC 관리도 (불량률 p-chart, 최근 20일)")
        st.caption("더미 데이터 — 실제 운영 로그 연동 전 레이아웃 확인용")
        st.plotly_chart(_p_chart(spc_daily_defect_rate()), width="stretch", config={"displayModeBar": False})

    with st.container(border=True):
        st.subheader("특성요인도 (균열·용입불량 원인분석)")
        st.plotly_chart(_fishbone(), width="stretch", config={"displayModeBar": False})