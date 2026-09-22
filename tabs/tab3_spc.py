import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.decisions import log_decision
from utils.mail_ui import render_send_email_popover
from utils.dummy_data import load_validation_predictions, make_mock_gradcam_overlay, spc_daily_defect_rate
from utils.priority import (
    BASELINE_BRIGHTNESS,
    avg_sample_brightness,
    build_priority_queue,
    score_real_samples,
)
from utils.report import weekly_report_bytes
from utils.routing import DEFAULT_THRESHOLDS
from utils.samples import image_for_id, load_samples
from utils.style import CLASS_COLORS, STATUS_COLORS, status_badge

# 전체 차트에서 공통으로 쓰는 폰트 — style.py의 페이지 CSS와 통일시키기 위함.
# Plotly는 브라우저 CSS를 안 따르고 SVG에 직접 폰트를 그리므로, 차트마다 이 값을 넣어줘야 함.
CHART_FONT = dict(family="Pretendard, Malgun Gothic, sans-serif")

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

# 특성요인도 원인 — "균열계열"은 조원이 이미 쓰던 용접 일반 원인을, "기공"은
# 별도 근거(실드가스·건조 등)를 사용한다. 두 세트 다 실제 STAGE 보고서에서 이미
# 쓰인 항목이라 지어낸 값이 아니다.
CRACK_CAUSES = [("용접 전류", 0.75, 0.9), ("이음부 간격", 0.55, 0.9),
                ("작업자 숙련도", 0.55, 0.1), ("모재 청결도", 0.75, 0.1)]
POROSITY_CAUSES = [("실드가스 유량 부족", 0.75, 0.9), ("모재 수분/유분", 0.55, 0.9),
                    ("용접봉 건조 불량", 0.55, 0.1), ("아크길이 과다", 0.75, 0.1)]


def _mini_donut():
    labels = [r["label"] for r in ROUTING_SUMMARY]
    values = [r["n"] for r in ROUTING_SUMMARY]
    colors = [STATUS_COLORS[r["status"]]["bg"] for r in ROUTING_SUMMARY]
    fig = go.Figure(go.Pie(labels=labels, values=values, marker_colors=colors, hole=0.55,
                            textinfo="percent", textfont=dict(size=13)))
    fig.update_layout(height=230, margin=dict(l=0, r=0, t=10, b=10), showlegend=False, font=CHART_FONT)
    return fig


def _p_chart(df, forced_spike=False):
    df = df.copy()
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std
    if forced_spike:
        df.loc[df.index[-1], "defect_rate"] = ucl * 1.15

    y_top = max(df["defect_rate"].max(), ucl) * 1.15
    fig = go.Figure()
    # 실측 관리한계선 기준 배경 구간 — CL~UCL은 주의(노랑), UCL 이상은 위험(빨강).
    # 근거 없는 임의 색이 아니라 이 차트 자체가 계산한 CL/UCL 값을 그대로 씀.
    fig.add_hrect(y0=cl, y1=ucl, fillcolor="#fab219", opacity=0.10, line_width=0)
    fig.add_hrect(y0=ucl, y1=y_top, fillcolor="#d03b3b", opacity=0.10, line_width=0)
    fig.add_trace(go.Scatter(x=df["date"], y=df["defect_rate"], mode="lines+markers",
                              line=dict(color="#2a78d6", width=2), marker=dict(size=5), name="불량률"))
    fig.add_hline(y=ucl, line_dash="dash", line_color="#fab219", annotation_text="UCL(+3σ)")
    fig.add_hline(y=cl, line_dash="dot", line_color="#898781", annotation_text="CL")
    outliers = df[df["defect_rate"] > ucl]
    if not outliers.empty:
        fig.add_trace(go.Scatter(x=outliers["date"], y=outliers["defect_rate"], mode="markers",
                                  marker=dict(color="#d03b3b", size=9), name="이상점"))
    fig.update_layout(height=190, margin=dict(l=10, r=10, t=10, b=10),
                       yaxis=dict(title=None, tickformat=".1%", gridcolor="#e1e0d9", tickfont=dict(size=10)),
                       xaxis=dict(gridcolor="#e1e0d9", tickfont=dict(size=10)),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                       font=CHART_FONT)
    return fig


def _fishbone(kind):
    causes = CRACK_CAUSES if kind == "crack" else POROSITY_CAUSES
    label = "균열(D1)·용입불량(D4)" if kind == "crack" else "기공(D2)"
    fig = go.Figure()
    fig.add_shape(type="line", x0=0.05, y0=0.5, x1=0.95, y1=0.5, line=dict(color="#52514e", width=3))
    fig.add_annotation(x=0.98, y=0.5, text=label, showarrow=False, xanchor="left", font=dict(size=11))
    for lab, cx, cy in causes:
        fig.add_shape(type="line", x0=cx, y0=0.5, x1=cx - 0.15, y1=cy, line=dict(color="#c3c2b7"))
        fig.add_annotation(x=cx - 0.15, y=cy, text=lab, showarrow=False,
                            yshift=12 if cy > 0.5 else -12, font=dict(size=10))
    fig.update_xaxes(visible=False, range=[0, 1.2])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=190, margin=dict(l=10, r=10, t=10, b=10),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                       font=CHART_FONT)
    return fig


def _prob_bar_chart(probs):
    labels = list(probs.keys())
    values = list(probs.values())
    colors = [CLASS_COLORS.get(l, "#2a78d6") for l in labels]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=colors,
                            text=[f"{v:.2f}" for v in values], textposition="outside"))
    fig.update_layout(xaxis=dict(range=[0, 1], gridcolor="#e1e0d9"), yaxis=dict(autorange="reversed"),
                       margin=dict(l=10, r=30, t=10, b=10), height=160,
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                       font=CHART_FONT)
    return fig


def _dummy_queue_items(thresholds):
    """가중치 미탑재 시 폴백 — 더미 검증셋 기준 예시 큐."""
    val_df = load_validation_predictions()
    queue_df = build_priority_queue(val_df, thresholds, top_n=12)
    items = []
    for _, row in queue_df.iterrows():
        items.append({
            "image_id": row["image_id"], "path": None,
            "probs": {
                "무결함": row["prob_무결함"],
                "균열(D1)": row["prob_균열(D1)"],
                "기공(D2)": row["prob_기공(D2)"],
                "용입불량(D4)": row["prob_용입불량(D4)"],
            },
            "status": row["status"], "ai_label": row["ai_label"],
            "dominant_class": row["dominant_class"],
            "calibrated_prob": row["calibrated_prob"], "severity_score": row["severity_score"],
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

    queue_items = score_real_samples(thresholds)
    using_real = queue_items is not None
    if not using_real:
        queue_items = _dummy_queue_items(thresholds)

    resolved_map = st.session_state.get("resolved_queue_items", {})
    open_items = [it for it in queue_items if it["image_id"] not in resolved_map]

    approved_n = sum(1 for v in resolved_map.values() if "승인" in v)
    rejected_n = sum(1 for v in resolved_map.values() if "반려" in v)
    done_n = approved_n + rejected_n

    brightness = avg_sample_brightness()

    # ------------------------------------------------------------
    # 1단: 왼쪽(처리완료·밝기) — 가운데(허브: 도넛+4개 KPI) — 오른쪽(사람확인 대기)
    # ------------------------------------------------------------
    PANEL_H = 300
    col_left, col_mid, col_right = st.columns([0.85, 1.3, 1])

    with col_left:
        with st.container(height=PANEL_H, border=True):
            st.markdown(
                '<p style="font-size:12px;color:var(--text-secondary);margin:0 0 4px">'
                '📋 오늘 처리 완료</p>'
                f'<p style="font-size:20px;font-weight:600;margin:0 0 6px">{done_n}건</p>',
                unsafe_allow_html=True,
            )
            if done_n > 0:
                a_pct = approved_n / done_n * 100
                st.markdown(
                    f'<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:4px">'
                    f'<div style="width:{a_pct:.0f}%;background:#0ca30c"></div>'
                    f'<div style="width:{100 - a_pct:.0f}%;background:#d03b3b"></div></div>',
                    unsafe_allow_html=True,
                )
                st.caption(f"승인 {approved_n}건 · 반려 {rejected_n}건")
            else:
                st.caption("아직 처리한 건이 없습니다.")

            st.divider()

            st.markdown(
                '<p style="font-size:12px;color:var(--text-secondary);margin:0 0 4px">'
                '☀ 입력 밝기 드리프트</p>',
                unsafe_allow_html=True,
            )
            if brightness is not None:
                diff_pct = (brightness - BASELINE_BRIGHTNESS) / BASELINE_BRIGHTNESS * 100
                arrow = "↓" if diff_pct < 0 else "↑"
                st.markdown(f'<p style="font-size:20px;font-weight:600;margin:0 0 4px">{brightness:.0f}</p>',
                            unsafe_allow_html=True)
                st.caption(f"기준 {BASELINE_BRIGHTNESS} 대비 {arrow}{abs(diff_pct):.0f}% "
                           f"(samples/ 폴더 실측 평균 · 참고용)")
            else:
                st.caption("samples/ 폴더에 사진이 없어 계산할 수 없습니다.")

    with col_mid:
        with st.container(height=PANEL_H, border=True):
            hc1, hc2, hc3 = st.columns([1, 1.1, 1])
            with hc1:
                st.markdown(
                    '<div style="height:230px;display:flex;flex-direction:column;justify-content:center;'
                    'align-items:center;text-align:center;gap:16px">'
                    f'<div><p style="font-size:10px;color:var(--text-secondary);margin:0">자동화율</p>'
                    f'<p style="font-size:15px;font-weight:600;margin:0">{CORE_KPIS[0][1]:.1%}</p></div>'
                    '<div><p style="font-size:10px;color:var(--text-secondary);margin:0">사람확인 대기</p>'
                    f'<p style="font-size:15px;font-weight:600;margin:0">{len(open_items)}건</p></div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            with hc2:
                st.plotly_chart(_mini_donut(), width="stretch", config={"displayModeBar": False})
                st.markdown('<p style="font-size:10px;color:var(--text-secondary);text-align:center;margin:-8px 0 0">오늘 처리현황</p>',
                            unsafe_allow_html=True)
            with hc3:
                d1_color = "#0ca30c" if CORE_KPIS[1][1] == 0 else "#d03b3b"
                d4_color = "#0ca30c" if CORE_KPIS[2][1] == 0 else "#d03b3b"
                st.markdown(
                    '<div style="height:230px;display:flex;flex-direction:column;justify-content:center;'
                    'align-items:center;text-align:center;gap:16px">'
                    f'<div><p style="font-size:10px;color:var(--text-secondary);margin:0">D1 미검출</p>'
                    f'<p style="font-size:15px;font-weight:600;margin:0;color:{d1_color}">{CORE_KPIS[1][1]:.1%}</p></div>'
                    f'<div><p style="font-size:10px;color:var(--text-secondary);margin:0">D4 미검출</p>'
                    f'<p style="font-size:15px;font-weight:600;margin:0;color:{d4_color}">{CORE_KPIS[2][1]:.1%}</p></div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

    with col_right:
        with st.container(height=PANEL_H, border=True):
            h1, h2 = st.columns([2, 1])
            h1.markdown('<p style="font-size:14px;font-weight:600;margin:0">🔎 사람확인 대기</p>', unsafe_allow_html=True)
            h2.caption(f"{len(open_items)}건")
            if not using_real:
                st.caption("⚠ 가중치 미탑재 — 더미 예시 큐")

            docx_bytes, docx_name = weekly_report_bytes(thresholds)
            r1, r2 = st.columns(2)
            r1.download_button("📄 보고서", data=docx_bytes, file_name=docx_name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                width="stretch")
            with r2:
                render_send_email_popover(
                    docx_bytes, docx_name, subject="[RT 검사] 주간 자동보고서",
                    body="첨부된 주간 자동보고서를 확인해 주세요.", key_prefix="weekly_today",
                )

            if not open_items:
                st.success("대기 케이스 없음")
            else:
                for item in open_items:
                    dom_color = (STATUS_COLORS["attention_crack"]["bg"]
                                 if item["dominant_class"] in ("균열(D1)", "용입불량(D4)")
                                 else STATUS_COLORS["attention"]["bg"])
                    c1, c2, c3 = st.columns([0.3, 2, 1])
                    c1.markdown(f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                                f'background:{dom_color};margin-top:6px;"></span>', unsafe_allow_html=True)
                    c2.markdown(f"<span style='font-size:12px'>{item['image_id']} · {item['dominant_class']} · "
                                f"{item['calibrated_prob']:.2f}</span>", unsafe_allow_html=True)
                    if c3.button("검토하기", key=f"select_{item['image_id']}", width="stretch"):
                        _review_dialog(item, samples)

    # ------------------------------------------------------------
    # 2단: SPC 관리도 / 특성요인도 — 작게, 시연 버튼으로 이상 상황 토글
    # ------------------------------------------------------------
    demo_type = st.session_state.get("spc_demo_type")  # None | "crack" | "porosity"

    PANEL2_H = 340
    col_spc, col_fish = st.columns([1.3, 1])

    with col_spc:
        with st.container(height=PANEL2_H, border=True):
            sh1, sh2 = st.columns([1.6, 1])
            sh1.markdown('<p style="font-size:13px;font-weight:600;margin:0">📊 SPC 관리도</p>', unsafe_allow_html=True)
            with sh2:
                bb1, bb2 = st.columns(2)
                if bb1.button("균열계열 시연", key="demo_crack", width="stretch"):
                    st.session_state["spc_demo_type"] = None if demo_type == "crack" else "crack"
                    st.rerun()
                if bb2.button("기공 시연", key="demo_porosity", width="stretch"):
                    st.session_state["spc_demo_type"] = None if demo_type == "porosity" else "porosity"
                    st.rerun()

            fig = _p_chart(spc_daily_defect_rate(), forced_spike=(demo_type is not None))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            if demo_type is not None:
                st.warning("⚠ 관리한계 이탈 감지 (시연) — 오늘 불량률이 UCL을 초과했습니다.")
            else:
                st.caption("더미 데이터 — 실제 운영 로그 연동 전 레이아웃 확인용")

    with col_fish:
        with st.container(height=PANEL2_H, border=True):
            if demo_type is not None:
                label = "균열·용입불량 원인분석" if demo_type == "crack" else "기공 원인분석"
                st.markdown(f'<p style="font-size:13px;font-weight:600;margin:0 0 6px">🔧 {label}</p>', unsafe_allow_html=True)
                st.markdown('<div style="height:60px"></div>', unsafe_allow_html=True)
                st.plotly_chart(_fishbone(demo_type), width="stretch", config={"displayModeBar": False})
            else:
                st.markdown('<p style="font-size:13px;font-weight:600;margin:0 0 6px">🔧 특성요인도</p>', unsafe_allow_html=True)
                st.markdown(
                    '<div style="height:290px;display:flex;align-items:center;justify-content:center;text-align:center">'
                    '<p style="font-size:12px;color:var(--text-muted);margin:0">현재 이상 신호 없음<br>'
                    '(시연 버튼을 누르면 원인분석이 표시됩니다)</p></div>',
                    unsafe_allow_html=True,
                )