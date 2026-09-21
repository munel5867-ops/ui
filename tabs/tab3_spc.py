import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.decisions import log_decision
from utils.mail_ui import render_send_email_popover
from utils.dummy_data import load_validation_predictions, make_mock_gradcam_overlay, spc_daily_defect_rate
from utils.priority import build_priority_queue
from utils.report import weekly_report_bytes
from utils.routing import DEFAULT_THRESHOLDS
from utils.samples import image_for_id, load_samples
from utils.style import CLASS_COLORS, STATUS_COLORS, status_tag

ROUTING_SUMMARY = [
    {"label": "자동통과", "n": 1194, "pct": 0.194, "status": "auto_pass"},
    {"label": "자동배출", "n": 4348, "pct": 0.708, "status": "auto_reject"},
    {"label": "사람확인", "n": 598, "pct": 0.097, "status": "attention"},
]
CRACK_SUSPECT_N = 204
CORE_KPIS = [
    ("자동화율", 0.903, "자동통과 19.4% + 자동배출 70.8%"),
    ("D1(균열) 미검출", 0.0, "1,972장 중 0장 — 라우팅 효과"),
    ("D4(미용착) 미검출", 0.012, "1,161장 중 14장 자동통과"),
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
    fig.add_annotation(x=0.98, y=0.5, text="균열·용입불량(D1+D4)", showarrow=False, xanchor="left")
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
    st.caption(f'└ 균열계열 의심 — 우선 배정 {CRACK_SUSPECT_N}건 (통합 이전 규칙 기준)')

    st.markdown("<br>", unsafe_allow_html=True)
    for label, val, note in CORE_KPIS:
        st.metric(label, f"{val:.1%}", help=note)


def _render_review_panel(image_id, row, samples):
    from utils.model import gradcam_overlay

    probs = {
        "무결함": row["prob_무결함"],
        "균열·용입불량(D1+D4)": row["prob_균열·용입불량(D1+D4)"],
        "기공(D2)": row["prob_기공(D2)"],
    }
    st.markdown(f"#### 🔬 검토: `{image_id}` — 지배 클래스: {row['dominant_class']}")

    img_path = image_for_id(image_id, samples)
    pil_image = Image.open(img_path) if img_path else None

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
            overlay, _ = gradcam_overlay(pil_image)
        if overlay is None:
            st.caption("모델 가중치 미탑재 — 더미 히트맵으로 대체")
            st.image(make_mock_gradcam_overlay(), width="stretch")
        else:
            st.image(overlay, width="stretch")

    st.plotly_chart(_prob_bar_chart(probs), width="stretch", config={"displayModeBar": False})

    b1, b2 = st.columns(2)
    if b1.button("✅ 최종 양품 승인", key=f"approve_{image_id}", width="stretch"):
        log_decision(image_id, probs, "attention", "승인(양품)")
        st.session_state.setdefault("resolved_queue_items", {})[image_id] = "승인(양품)"
        st.session_state.pop("selected_queue_item", None)
        st.success(f"{image_id} — 양품으로 확정 처리되었습니다.")
        st.rerun()
    if b2.button("⛔ 최종 불량 확정", key=f"reject_{image_id}", width="stretch"):
        log_decision(image_id, probs, "attention", "반려(불량)")
        st.session_state.setdefault("resolved_queue_items", {})[image_id] = "반려(불량)"
        st.session_state.pop("selected_queue_item", None)
        st.success(f"{image_id} — 불량으로 확정 처리되었습니다.")
        st.rerun()


def render():
    thresholds = st.session_state.get("thresholds", DEFAULT_THRESHOLDS)
    val_df = load_validation_predictions()

    queue = build_priority_queue(val_df, thresholds, top_n=12)
    resolved_map = st.session_state.get("resolved_queue_items", {})
    open_queue = queue[~queue["image_id"].isin(resolved_map.keys())]
    samples = load_samples()
    selected_id = st.session_state.get("selected_queue_item")

    # ------------------------------------------------------------
    # 첫 화면: 왼쪽 = 오늘의 처리 현황, 오른쪽 = 사람 확인 대기 큐(목록만)
    # ------------------------------------------------------------
    col_left, col_right = st.columns([1, 1.3])

    with col_left:
        with st.container(border=True):
            _render_today_panel()

    with col_right:
        with st.container(border=True):
            st.header("🔎 사람 확인 대기 · 심각도순")
            st.caption("심각도(지배 클래스 위험도 × 보정 확률) 내림차순 — 위험한 것부터 확인하세요.")

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

            if open_queue.empty:
                st.success("대기 중인 사람 확인 케이스가 없습니다.")
            else:
                for _, row in open_queue.iterrows():
                    dom_color = (STATUS_COLORS["auto_reject"]["bg"] if row["dominant_class"] == "균열·용입불량(D1+D4)"
                                 else STATUS_COLORS["attention"]["bg"])
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([0.4, 2.2, 1.2])
                        c1.markdown(f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
                                    f'background:{dom_color};margin-top:8px;"></span>', unsafe_allow_html=True)
                        c2.markdown(
                            f"**{row['image_id']}** &nbsp;·&nbsp; {row['dominant_class']}  \n"
                            f"보정 확률 {row['calibrated_prob']:.2f} · 심각도 {row['severity_score']:.2f}",
                            unsafe_allow_html=True,
                        )
                        btn_label = "닫기 ▲" if row["image_id"] == selected_id else "검토하기"
                        if c3.button(btn_label, key=f"select_{row['image_id']}", width="stretch"):
                            if row["image_id"] == selected_id:
                                st.session_state.pop("selected_queue_item", None)
                            else:
                                st.session_state["selected_queue_item"] = row["image_id"]
                            st.rerun()

    # ------------------------------------------------------------
    # 검토 패널 — 선택 시 아래에 화면 전체 너비로 크게 표시
    # ------------------------------------------------------------
    if selected_id and selected_id in open_queue["image_id"].values:
        row = open_queue[open_queue["image_id"] == selected_id].iloc[0]
        st.divider()
        with st.container(border=True):
            _render_review_panel(selected_id, row, samples)

    st.divider()

    # ------------------------------------------------------------
    # SPC 관리도 + 특성요인도
    # ------------------------------------------------------------
    with st.container(border=True):
        st.subheader("SPC 관리도 (불량률 p-chart, 최근 20일)")
        st.caption("더미 데이터 — 실제 운영 로그 연동 전 레이아웃 확인용")
        st.plotly_chart(_p_chart(spc_daily_defect_rate()), width="stretch", config={"displayModeBar": False})

    with st.container(border=True):
        st.subheader("특성요인도 (균열·용입불량 원인분석)")
        st.plotly_chart(_fishbone(), width="stretch", config={"displayModeBar": False})
