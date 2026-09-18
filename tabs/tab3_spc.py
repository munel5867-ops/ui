import plotly.graph_objects as go
import streamlit as st

from utils.dummy_data import inspector_queue, spc_daily_defect_rate

SEV_COLOR = {"high": "#e03e3e", "mid": "#e8a33d", "low": "#9aa0ab"}


def _p_chart(df) -> go.Figure:
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"], y=df["defect_rate"], mode="lines+markers",
            line=dict(color="#ff4b4b", width=2), name="불량률",
        )
    )
    fig.add_hline(y=ucl, line_dash="dash", line_color="#e8a33d", annotation_text="UCL")
    fig.add_hline(y=cl, line_dash="dot", line_color="#9aa0ab", annotation_text="CL")

    outliers = df[df["defect_rate"] > ucl]
    if not outliers.empty:
        fig.add_trace(
            go.Scatter(
                x=outliers["date"], y=outliers["defect_rate"], mode="markers+text",
                marker=dict(color="#e03e3e", size=10),
                text=["이상점"] * len(outliers), textposition="top center",
                name="이상점",
            )
        )

    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=20, b=10),
        yaxis=dict(title="불량률", tickformat=".1%"),
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
    fig.add_shape(type="line", x0=0.05, y0=0.5, x1=0.95, y1=0.5, line=dict(color="#888", width=3))
    fig.add_annotation(x=0.98, y=0.5, text="미용착(D4)", showarrow=False, xanchor="left")

    for label, cx, cy in causes:
        fig.add_shape(type="line", x0=cx, y0=0.5, x1=cx - 0.15, y1=cy, line=dict(color="#aaa"))
        fig.add_annotation(x=cx - 0.15, y=cy, text=label, showarrow=False,
                            yshift=12 if cy > 0.5 else -12)

    fig.update_xaxes(visible=False, range=[0, 1.15])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
    return fig


def render():
    st.subheader("SPC 관리도 (불량률 p-chart, 최근 20일)")
    st.plotly_chart(_p_chart(spc_daily_defect_rate()), width="stretch", config={"displayModeBar": False})

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("특성요인도 (피쉬본 · 미용착 원인분석)")
        st.caption("⚠ 더미 원인 목록 — 실제 원인분석 결과로 교체 필요")
        st.plotly_chart(_fishbone(), width="stretch", config={"displayModeBar": False})

    with col2:
        st.subheader("검사자 확인 대기열 (심각도순)")
        queue = inspector_queue()
        for _, row in queue.iterrows():
            dot = f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{SEV_COLOR[row.severity]};margin-right:6px;"></span>'
            st.markdown(
                f"{dot}**{row.image_id}** &nbsp;|&nbsp; {row.suspect} &nbsp;|&nbsp; 확률 {row.prob:.2f}",
                unsafe_allow_html=True,
            )
