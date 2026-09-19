import plotly.graph_objects as go
import streamlit as st

from utils.dummy_data import inspector_queue, spc_daily_defect_rate
from utils.routing import DEFAULT_THRESHOLDS
from utils.style import STATUS_COLORS, status_tag

SEV_COLOR = {"high": "#d03b3b", "mid": "#fab219", "low": "#898781"}

# STAGE1~3 실제 검증 결과 확정치 (구글드라이브 `라우팅_결과_요약.txt` 기준, 2026-09-18).
# ②임계값 조절 탭의 더미 검증셋과 달리 이건 팀이 이미 낸 실제 결과라서, 슬라이더를
# 움직여도 여기 숫자는 안 바뀐다.
#
# ⚠ STAGE3 갱신: 이 숫자들은 균열(D1)·미용착(D4)을 "균열·용입불량(D1+D4)" 한 클래스로
# 통합하기 *이전*의 4갈래 라우팅 규칙(P(무결함) 자동통과 / D1·D4 동시 애매 / 최고 결함확률
# 자동배출 / 그 외 사람확인) 기준 실제 결과다. 통합 이후 새 규칙(② 탭의 CRACK_OR_LOP_T·
# POROSITY_T)으로 전체 데이터셋을 다시 라우팅한 새 집계는 아직 나오지 않았으므로, 없는
# 숫자를 만들어내는 대신 이 예전 결과를 그대로 두고 이렇게 표시한다. 팀이 새 규칙으로
# 재집계하면 이 블록과 CORE_KPIS를 교체할 것.
ROUTING_SUMMARY = [
    {"label": "자동통과", "n": 1194, "pct": 0.194, "status": "auto_pass"},
    {"label": "자동배출", "n": 4348, "pct": 0.708, "status": "auto_reject"},
    {"label": "사람확인", "n": 598, "pct": 0.097, "status": "attention"},
]
CRACK_SUSPECT_N = 204  # 사람확인 598건 중 균열계열 의심(우선 배정)
CORE_KPIS = [
    ("자동화율", 0.903, "자동통과 19.4% + 자동배출 70.8%"),
    ("D1(균열) 미검출", 0.0, "1,972장 중 0장 — 라우팅 효과"),
    ("D4(미용착) 미검출", 0.012, "1,161장 중 14장 자동통과"),
]


def _routing_pie() -> go.Figure:
    labels = [r["label"] for r in ROUTING_SUMMARY]
    values = [r["n"] for r in ROUTING_SUMMARY]
    colors = [STATUS_COLORS[r["status"]]["bg"] for r in ROUTING_SUMMARY]
    fig = go.Figure(
        go.Pie(labels=labels, values=values, marker_colors=colors, hole=0.55, textinfo="percent")
    )
    fig.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    return fig


def _p_chart(df) -> go.Figure:
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"], y=df["defect_rate"], mode="lines+markers",
            line=dict(color="#2a78d6", width=2), marker=dict(size=6), name="불량률",
        )
    )
    fig.add_hline(y=ucl, line_dash="dash", line_color="#fab219", annotation_text="UCL")
    fig.add_hline(y=cl, line_dash="dot", line_color="#898781", annotation_text="CL")

    outliers = df[df["defect_rate"] > ucl]
    if not outliers.empty:
        fig.add_trace(
            go.Scatter(
                x=outliers["date"], y=outliers["defect_rate"], mode="markers+text",
                marker=dict(color="#d03b3b", size=10),
                text=["이상점"] * len(outliers), textposition="top center",
                name="이상점",
            )
        )

    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=20, b=10),
        yaxis=dict(title="불량률", tickformat=".1%", gridcolor="#e1e0d9"),
        xaxis=dict(gridcolor="#e1e0d9"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _fishbone() -> go.Figure:
    """미용착(D4) 원인분석 특성요인도 (더미 causes)."""
    causes = [
        ("용접 전류", 0.75, 0.9),
        ("이음부 간격", 0.55, 0.9),
        ("작업자 숙련도", 0.55, 0.1),
        ("모재 청결도", 0.75, 0.1),
    ]
    fig = go.Figure()
    fig.add_shape(type="line", x0=0.05, y0=0.5, x1=0.95, y1=0.5, line=dict(color="#52514e", width=3))
    fig.add_annotation(x=0.98, y=0.5, text="미용착(D4)", showarrow=False, xanchor="left")

    for label, cx, cy in causes:
        fig.add_shape(type="line", x0=cx, y0=0.5, x1=cx - 0.15, y1=cy, line=dict(color="#c3c2b7"))
        fig.add_annotation(x=cx - 0.15, y=cy, text=label, showarrow=False,
                            yshift=12 if cy > 0.5 else -12)

    fig.update_xaxes(visible=False, range=[0, 1.15])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(
        height=260, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render():
    st.subheader("오늘의 현황")

    auto_pass, auto_reject, human_review = ROUTING_SUMMARY

    col1, col2 = st.columns([1.1, 1])
    with col1:
        with st.container(border=True):
            st.markdown("**지금 처리할 작업**")
            st.markdown(
                f'사람확인 대기 (검사원 배정) '
                f'<span style="float:right;font-weight:700;color:{STATUS_COLORS["attention"]["bg"]}">'
                f'{human_review["n"]}건</span>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'└ 균열계열 의심 — 우선 배정 '
                f'<span style="float:right;font-weight:700;color:{STATUS_COLORS["attention_crack"]["bg"]}">'
                f'{CRACK_SUSPECT_N}건</span>',
                unsafe_allow_html=True,
            )

    with col2:
        with st.container(border=True):
            st.markdown("**자동배출**")
            st.markdown(
                f'<span style="font-size:30px;font-weight:800;color:{STATUS_COLORS["auto_reject"]["bg"]}">'
                f'{auto_reject["n"]:,}건</span> '
                f'<span style="font-size:15px;color:#898781">({auto_reject["pct"]:.1%})</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                f'자동통과 {auto_pass["n"]:,}건({auto_pass["pct"]:.1%}) · '
                f'사람확인 {human_review["n"]:,}건({human_review["pct"]:.1%})'
            )

    with st.container(border=True):
        st.markdown("**처리 현황 (3구간 라우팅)**")
        c1, c2 = st.columns([1, 2])
        with c1:
            st.plotly_chart(_routing_pie(), width="stretch", config={"displayModeBar": False})
        with c2:
            for r in ROUTING_SUMMARY:
                st.markdown(
                    f'{r["label"]} &nbsp;|&nbsp; {r["n"]:,}건 ({r["pct"]:.1%}) &nbsp; {status_tag(r["status"])}',
                    unsafe_allow_html=True,
                )
        th = DEFAULT_THRESHOLDS
        st.caption(
            f'현재 라우팅 규칙(기본 임계값 기준, STAGE3 통합 이후): '
            f'P(무결함)≥{th["nd_confident"]:.2f}→자동통과 · '
            f'P(균열·용입불량 D1+D4)≥{th["crack_or_lop_t"]:.2f}→자동배출 · '
            f'P(기공 D2)≥{th["porosity_t"]:.2f}→자동배출 · 그 외→사람확인'
        )
        st.caption(
            "⚠ 위 숫자(자동통과/자동배출/사람확인 건수, D1·D4 미검출률)는 통합 이전 규칙으로 낸 "
            "결과라 이 규칙과 정확히 일치하지 않음 — 재집계 전까지 참고용"
        )
        st.caption("5-fold 교차검증 예측치 합산 기준")

    m1, m2, m3 = st.columns(3)
    for col, (label, val, note) in zip((m1, m2, m3), CORE_KPIS):
        col.metric(label, f"{val:.1%}", help=note)

    st.divider()

    with st.container(border=True):
        st.subheader("SPC 관리도 (불량률 p-chart, 최근 20일)")
        st.caption("아래부터는 더미 데이터 — 실제 운영 로그 연동 전 레이아웃 확인용")
        st.plotly_chart(_p_chart(spc_daily_defect_rate()), width="stretch", config={"displayModeBar": False})

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("특성요인도 (미용착 원인분석)")
            st.plotly_chart(_fishbone(), width="stretch", config={"displayModeBar": False})

    with col2:
        with st.container(border=True):
            st.subheader("검사자 확인 대기열")
            queue = inspector_queue()
            for _, row in queue.iterrows():
                dot = (
                    f'<span style="display:inline-block;width:10px;height:10px;'
                    f'border-radius:50%;background:{SEV_COLOR[row.severity]};margin-right:6px;"></span>'
                )
                st.markdown(
                    f"{dot}**{row.image_id}** &nbsp;|&nbsp; {row.suspect} &nbsp;|&nbsp; 확률 {row.prob:.2f}",
                    unsafe_allow_html=True,
                )
