import re

import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from utils.decisions import log_decision
from utils.mail_ui import render_send_email_popover
from utils.ncr_report import ncr_bytes_for_case
from utils.dummy_data import load_validation_predictions, make_mock_gradcam_overlay, spc_daily_defect_rate
from utils.priority import (
    BASELINE_BRIGHTNESS,
    sample_brightness_stats,
    build_priority_queue,
    score_real_samples,
)
from utils.report import today_status_report_bytes
from utils.routing import DEFAULT_THRESHOLDS
from utils.samples import image_for_id, load_samples
from utils.style import BRAND_BLUE, BRAND_NAVY, CLASS_COLORS, STATUS_COLORS, status_badge

# 전체 차트에서 공통으로 쓰는 폰트 — style.py의 페이지 CSS와 통일시키기 위함.
# Plotly는 브라우저 CSS를 안 따르고 SVG에 직접 폰트를 그리므로, 차트마다 이 값을 넣어줘야 함.
CHART_FONT = dict(family="Pretendard, Malgun Gothic, sans-serif", size=16)

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

# 특성요인도 원인(6M 기준) — "균열계열"은 D1(균열)·D4(용입불량)를 통합해서 다룬다
# (routing.py의 설계 의도: 둘은 모델이 헷갈리기 쉬운 클래스라 사람에게 함께 넘긴다는
# 원칙을 특성요인도에도 그대로 반영). "기공"은 D2 별도.
# 값은 실제 용접공학 문헌(TWI, AWS 계열 기술문헌, ScienceDirect·arXiv 논문 등)에서
# 반복적으로 확인되는 원인을 6M(사람/설비/재료/방법/측정/환경)로 분류한 것.
FISHBONE_CAUSES = {
    "crack": {
        "label": "균열(D1)·용입불량(D4)",
        "categories": [
            ("사람(Man)", [
                "WPS(용접절차서) 미준수 — 전류·속도·예열 임의 변경",
                "토치각도·운봉 조작 미숙",
                "용접봉 건조·보관 절차 소홀",
            ]),
            ("설비(Machine)", [
                "용접기 전류·전압 출력 불안정",
                "전극 건조로 미가동·고장",
                "와이어 송급장치·노즐 결함",
            ]),
            ("재료(Material)", [
                "모재 탄소당량(CE) 높음",
                "이음부 개선각도·루트간격 설계 부적절",
                "모재 표면 오염(녹·오일·밀스케일)",
            ]),
            ("방법(Method)", [
                "예열·층간온도 관리 절차 미비",
                "후열처리(PWHT)·루트패스 관리 절차 누락",
                "WPS 전류·속도 범위가 이음부 형상과 불일치",
            ]),
            ("측정(Measurement)", [
                "예열·층간온도 미측정",
                "용접 전류·전압 실시간 모니터링 부재",
                "루트간격·개선각도 시공 전 게이지 측정 누락",
            ]),
            ("환경(Environment)", [
                "저온 작업환경(냉각속도 가속)",
                "협소 작업공간(토치 접근각 제한)",
                "높은 구조적 구속도(두꺼운 판재·복잡 이음부)",
            ]),
        ],
    },
    "porosity": {
        "label": "기공(D2)",
        "categories": [
            ("사람(Man)", [
                "모재 청소(탈지) 소홀",
                "용접봉 보관·건조 절차 미준수",
                "실드가스 유량 설정 오조작",
            ]),
            ("설비(Machine)", [
                "가스라인 누설·노즐 막힘",
                "유량계 고장·미보정",
                "전극 건조로 미가동",
            ]),
            ("재료(Material)", [
                "실드가스 순도 불량",
                "모재/용접재료 수분 함유",
                "표면 오염(오일·녹·아연도금)",
            ]),
            ("방법(Method)", [
                "실드가스 유량 기준(35~45 CFH) 미준수",
                "용접속도 과다로 실드 노출시간 부족",
                "팁-워크 거리 과다",
            ]),
            ("측정(Measurement)", [
                "실드가스 유량 미점검",
                "이슬점(결로) 미확인",
                "기공 검출 검사주기 미준수",
            ]),
            ("환경(Environment)", [
                "강풍·기류(팬, 개방문)",
                "고습도·온도차로 인한 결로",
                "옥외 개방 작업환경",
            ]),
        ],
    },
}



def _mini_donut():
    labels = [r["label"] for r in ROUTING_SUMMARY]
    values = [r["n"] for r in ROUTING_SUMMARY]
    colors = [STATUS_COLORS[r["status"]]["bg"] for r in ROUTING_SUMMARY]
    fig = go.Figure(go.Pie(labels=labels, values=values, marker_colors=colors, hole=0.55,
                            textinfo="percent", textfont=dict(size=16)))
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=10), showlegend=False, font=CHART_FONT,
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
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
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                       yaxis=dict(title=None, tickformat=".1%", gridcolor="#e1e0d9", tickfont=dict(size=16)),
                       xaxis=dict(gridcolor="#e1e0d9", tickfont=dict(size=16)),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                       font=CHART_FONT)
    return fig


def _spc_status(df, forced_spike=False):
    """_p_chart()와 똑같은 계산으로 SPC 상태 값만 뽑는다 — 오늘의 현황 보고서용.
    시연 버튼으로 차트에 이상점을 강제로 띄운 상태면 보고서도 화면과 같은 값으로 나간다."""
    df = df.copy()
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std
    if forced_spike:
        df.loc[df.index[-1], "defect_rate"] = ucl * 1.15
    latest = df.iloc[-1]
    return {
        "date": latest["date"],
        "value": float(latest["defect_rate"]),
        "cl": float(cl),
        "ucl": float(ucl),
        "breached": bool(latest["defect_rate"] > ucl),
        "n_outliers": int((df["defect_rate"] > ucl).sum()),
        "demo": forced_spike,
    }



# 특성요인도 색 — 새 색을 만들지 않고 style.py 팔레트에서만 고른다 (BRAND_NAVY/
# BRAND_BLUE는 이미 배너·사이드바에, "#eda100"은 STATUS_COLORS["attention_margin"]·
# CLASS_COLORS["기공(D2)"]에 이미 쓰이는 색).
FISHBONE_COLORS = [BRAND_NAVY, BRAND_BLUE, "#eda100"]
FISHBONE_FONT = "'IBM Plex Sans KR', 'Malgun Gothic', '맑은 고딕', sans-serif"  # 페이지 본문과 동일한 폰트 스택


def _wrap_cause(text, max_chars=13):
    """원인 문구가 길면 가운데 부근의 구분자(공백·가운뎃점·대시)에서 2줄로 접는다.
    칸 폭에 15px 글자가 그대로 들어가면 옆 칸 글자와 겹치므로 필요."""
    if len(text) <= max_chars:
        return [text]
    mid = len(text) / 2
    seps = [i for i, ch in enumerate(text) if ch in " ·—"]
    if seps:
        cut = min(seps, key=lambda i: abs(i - mid))
        if text[cut] == " ":
            return [text[:cut].rstrip(), text[cut:].lstrip()]
        return [text[:cut + 1], text[cut + 1:].lstrip()]
    return [text[:max_chars], text[max_chars:]]


# 헤더(화살표) 박스 — 크기 고정, 이전보다 더 크게. 안의 글자도 같이 키워서 빈 공간을 줄인다.
HEADER_W, HEADER_H, HEADER_TIP = 220, 46, 22
HEADER_FONT_SIZE = 18
ITEM_FONT_SIZE = 16
LINE_PITCH = 24  # 모든 줄(항목 내 줄바꿈이든, 항목과 항목 사이든) 동일한 간격
TOP_MARGIN = 18
GAP_HEADER_TO_ITEMS = 28
GAP_ITEMS_TO_SPINE = 32
SPINE_H, SPINE_TIP = 30, 34


def _fishbone_category_svg(cx, top, header_y0, header_color, name, wrapped, spine_y, font):
    """카테고리 하나(화살표 헤더 박스 + 원인 줄들 + 스파인으로 가는 점선)의 SVG 조각.
    HEADER_W/HEADER_H는 항목 길이와 무관하게 항상 고정값 — 이름은 이 박스 정중앙에 배치한다.
    header_y0(헤더 박스 top)은 호출부(_fishbone)가 전체 레이아웃을 보고 미리 계산해 넘긴다.
    줄 간격은 항목 내 줄바꿈이든 항목 사이든 항상 LINE_PITCH 하나로 동일하다."""
    lines_count = sum(len(w) for w in wrapped)
    block_h = lines_count * LINE_PITCH

    hx0 = cx - HEADER_W / 2
    hy0, hy1 = header_y0, header_y0 + HEADER_H
    if top:
        first_baseline = hy1 + GAP_HEADER_TO_ITEMS
    else:
        first_baseline = hy0 - GAP_HEADER_TO_ITEMS - block_h + LINE_PITCH
    points = (f"{hx0},{hy0} {hx0 + HEADER_W - HEADER_TIP},{hy0} {hx0 + HEADER_W},{(hy0 + hy1) / 2} "
              f"{hx0 + HEADER_W - HEADER_TIP},{hy1} {hx0},{hy1}")

    parts = [
        f'<polygon points="{points}" fill="{header_color}" />',
        f'<text x="{cx}" y="{(hy0 + hy1) / 2}" text-anchor="middle" dominant-baseline="central" '
        f'font-family="{font}" font-size="{HEADER_FONT_SIZE}" font-weight="700" fill="#fff">{name}</text>',
    ]

    text_x0 = hx0 + 6
    y_cursor = first_baseline
    for item_lines in wrapped:
        for j, line in enumerate(item_lines):
            arrow = '<tspan dx="6" fill="#b7b6ad">→</tspan>' if j == len(item_lines) - 1 else ""
            parts.append(
                f'<text x="{text_x0}" y="{y_cursor}" font-family="{font}" font-size="{ITEM_FONT_SIZE}" '
                f'fill="#3a3a36">{line}{arrow}</text>'
            )
            y_cursor += LINE_PITCH

    # 대표 리브(점선) — 헤더의 뾰족한 끝점에서 출발해서, 항목 글자 칸(hx0+HEADER_W-10까지)보다
    # 오른쪽 빈 공간만 지나 스파인까지 이어진다. 항목 칸과 같은 x를 지나가면 글자와 겹치므로
    # 시작점(헤더 끝점)도 도착점(스파인 접점)도 항목 칸의 오른쪽 경계보다 항상 바깥쪽에 둔다.
    tip_x = hx0 + HEADER_W
    attach_x = tip_x + 30
    parts.append(
        f'<line x1="{tip_x}" y1="{(hy0 + hy1) / 2}" x2="{attach_x}" y2="{spine_y}" '
        f'stroke="#cfcec6" stroke-width="1.2" stroke-dasharray="2.5,3" />'
    )
    return "".join(parts)


def _fishbone(kind):
    """특성요인도(6M) — 화살표 헤더 6개(위 3 · 아래 3) + 각 3개 원인 + 가운데 스파인.
    plotly가 아니라 순수 SVG로 그린다 — 헤더 박스 크기를 고정하고 글자를 정중앙에
    두기 쉽고, 폰트도 페이지 본문과 같은 스택을 그대로 쓸 수 있어서다.
    화면 폭에 맞춰 축소되지 않도록 실제 px 그대로 그리고(뷰박스=표시크기 1:1),
    폭이 좁으면 감싸는 div가 가로 스크롤된다 — 그래야 글자 크기가 항상 보장된다."""
    spec = FISHBONE_CAUSES[kind]
    font = FISHBONE_FONT
    xs = [200, 480, 760]

    wrapped_top = [[_wrap_cause(t) for t in items] for _, items in spec["categories"][:3]]
    wrapped_bottom = [[_wrap_cause(t) for t in items] for _, items in spec["categories"][3:]]
    max_lines_top = max(sum(len(w) for w in cat) for cat in wrapped_top)
    max_lines_bottom = max(sum(len(w) for w in cat) for cat in wrapped_bottom)
    block_h_top = max_lines_top * LINE_PITCH
    block_h_bottom = max_lines_bottom * LINE_PITCH

    top_header_y0 = TOP_MARGIN
    spine_y0 = top_header_y0 + HEADER_H + GAP_HEADER_TO_ITEMS + block_h_top + GAP_ITEMS_TO_SPINE
    spine_y1 = spine_y0 + SPINE_H
    spine_y_mid = (spine_y0 + spine_y1) / 2
    bottom_header_y0 = spine_y1 + GAP_ITEMS_TO_SPINE + block_h_bottom + GAP_HEADER_TO_ITEMS
    total_h = bottom_header_y0 + HEADER_H + TOP_MARGIN
    total_w = 960

    svg_parts = []
    spine_x0, spine_x1, spine_tip = 20, total_w - 20, SPINE_TIP
    svg_parts.append(
        f'<polygon points="{spine_x0},{spine_y0} {spine_x1 - spine_tip},{spine_y0} '
        f'{spine_x1},{spine_y_mid} {spine_x1 - spine_tip},{spine_y1} '
        f'{spine_x0},{spine_y1}" fill="#8f8d85" />'
    )
    svg_parts.append(
        f'<text x="{spine_x1 - spine_tip - 16}" y="{spine_y_mid}" text-anchor="end" '
        f'dominant-baseline="central" font-family="{font}" font-size="19" font-weight="700" '
        f'fill="#fff">{spec["label"]}</text>'
    )

    for i, (name, _) in enumerate(spec["categories"][:3]):
        svg_parts.append(_fishbone_category_svg(
            xs[i], True, top_header_y0, FISHBONE_COLORS[i], name, wrapped_top[i], spine_y1, font))
    for i, (name, _) in enumerate(spec["categories"][3:]):
        svg_parts.append(_fishbone_category_svg(
            xs[i], False, bottom_header_y0, FISHBONE_COLORS[i], name, wrapped_bottom[i], spine_y0, font))

    svg = (
        f'<svg viewBox="0 0 {total_w} {total_h}" width="{total_w}" height="{total_h}" '
        f'xmlns="http://www.w3.org/2000/svg">' + "".join(svg_parts) + "</svg>"
    )
    return f'<div style="overflow-x:auto">{svg}</div>'


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
        ncr_bytes, ncr_name = ncr_bytes_for_case(item, "반려(불량)")
        st.session_state.setdefault("ncr_reports", {})[image_id] = (ncr_bytes, ncr_name)
        st.success(f"{image_id} — 불량으로 확정 처리되었습니다. 부적합보고서(NCR)가 자동 발행되었습니다 "
                   f"— '🔎 위험도순 확인' 패널 아래 '📄 발행된 NCR'에서 다운로드하세요.")
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

    brightness_stats = sample_brightness_stats()

    # ------------------------------------------------------------
    # 1단: 왼쪽(밝기 드리프트) — 가운데(허브: 도넛+4개 KPI) — 오른쪽(사람확인 대기)
    # "오늘 처리 완료"는 상단 KPI 바("오늘 처리하기")와 중복되어 삭제함.
    # ------------------------------------------------------------
    # 오늘 처리현황 패널(도넛+표)이 스크롤바 없이 다 들어가도록 여유 있게 잡은 값
    # (제목+도넛420px+표 약 88px+컨테이너 패딩까지 실측상 580으로는 빠듯해서 늘림).
    PANEL_H = 640  # 도넛을 키우고 하단에 표를 넣어서 더 넉넉하게
    col_left, col_mid, col_right = st.columns([0.85, 1.3, 1])

    with col_left:
        with st.container(height=PANEL_H, border=True):
            st.markdown(
                '<p style="font-size:18px;font-weight:600;color:var(--text-secondary);margin:0 0 8px">'
                '☀ 입력 밝기 드리프트</p>',
                unsafe_allow_html=True,
            )
            if brightness_stats is not None:
                brightness = brightness_stats["mean"]
                diff_pct = (brightness - BASELINE_BRIGHTNESS) / BASELINE_BRIGHTNESS * 100
                arrow = "↓" if diff_pct < 0 else "↑"
                is_ok = abs(diff_pct) <= 10
                status_color = "#0ca30c" if is_ok else "#eda100"
                status_label = "정상 범위" if is_ok else "주의 — 촬영 조건 점검 권장"

                # 범위 게이지 — 기준±30% 스케일에서 ±10% 정상 구간을 초록으로 표시하고
                # 현재 값 위치에 막대 마커를 찍는다. (요청에 따라 더 크게)
                scale_min = BASELINE_BRIGHTNESS * 0.7
                scale_max = BASELINE_BRIGHTNESS * 1.3
                band_low = BASELINE_BRIGHTNESS * 0.9
                band_high = BASELINE_BRIGHTNESS * 1.1

                def _pct(v):
                    return max(0.0, min(100.0, (v - scale_min) / (scale_max - scale_min) * 100))

                band_left = _pct(band_low)
                band_width = _pct(band_high) - band_left
                marker_left = _pct(brightness)

                # 위젯이 없는 순수 HTML이라 하나의 div로 감싸 세로 중앙정렬.
                # 게이지 막대·숫자 자체를 키워서 칸이 커진 만큼 내용도 같이 커지게 한다
                # (여백만 넓히면 그대로 비어 보이므로, 실제 그림 요소 크기를 늘리는 쪽).
                st.markdown(
                    f'<div style="height:{PANEL_H - 70}px;display:flex;flex-direction:column;'
                    'justify-content:center;gap:14px">'
                    f'<p style="font-size:38px;font-weight:800;margin:0">{brightness:.0f}</p>'
                    f'<span style="display:inline-block;padding:4px 14px;border-radius:14px;'
                    f'background:{status_color};color:#fff;font-size:17px;font-weight:600;'
                    f'width:fit-content">{status_label}</span>'
                    f'<p style="font-size:16px;color:var(--text-muted);margin:4px 0 0">'
                    f'기준 {BASELINE_BRIGHTNESS} 대비 {arrow}{abs(diff_pct):.0f}% '
                    f'(samples/ 폴더 실측 평균 · ±10% 이내 정상)</p>'

                    f'<div style="position:relative;height:96px;background:#eef0f2;'
                    f'border-radius:16px;margin:26px 0 10px">'
                    f'<div style="position:absolute;left:{band_left:.1f}%;width:{band_width:.1f}%;'
                    f'height:100%;background:#d7f2d1;border-radius:16px"></div>'
                    f'<div style="position:absolute;left:{marker_left:.1f}%;top:-10px;width:8px;'
                    f'height:116px;background:{status_color};border-radius:4px;'
                    f'transform:translateX(-4px)"></div>'
                    f'</div>'
                    f'<div style="display:flex;justify-content:space-between;font-size:16px;'
                    f'color:var(--text-muted);margin-bottom:16px">'
                    f'<span>{scale_min:.0f}</span><span>기준 {BASELINE_BRIGHTNESS}</span>'
                    f'<span>{scale_max:.0f}</span></div>'

                    f'<p style="font-size:16px;color:var(--text-secondary);margin:0 0 4px">'
                    f'표본 {brightness_stats["n"]}장 · 범위 '
                    f'{brightness_stats["min"]:.0f}~{brightness_stats["max"]:.0f}</p>'
                    '<p style="font-size:16px;color:var(--text-muted);margin:0">'
                    '촬영 조건(노출·필름 상태)이 학습 데이터와 달라지면 모델 정확도가 '
                    '떨어질 수 있어, 이 지표로 조기에 감지합니다.</p>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption("samples/ 폴더에 사진이 없어 계산할 수 없습니다.")

    with col_mid:
        with st.container(height=PANEL_H, border=True):
            # 제목은 다른 칸들과 통일되게 왼쪽 위 그대로 두고, 빈 공간은 아래 도넛/차트를
            # 키우는 쪽으로 처리한다(제목 위에 여백을 넣으면 칸마다 제목 위치가 달라짐).
            st.markdown('<p style="font-size:18px;font-weight:600;margin:0 0 4px">📊 오늘 처리현황</p>',
                        unsafe_allow_html=True)
            st.plotly_chart(_mini_donut(), width="stretch", config={"displayModeBar": False})

            d1_color = "#0ca30c" if CORE_KPIS[1][1] == 0 else "#d03b3b"
            d4_color = "#0ca30c" if CORE_KPIS[2][1] == 0 else "#d03b3b"
            st.markdown(
                '<table style="width:100%;border-collapse:collapse;text-align:center;margin-top:8px">'
                '<tr>'
                '<th style="padding:6px 4px;font-size:16px;color:var(--text-secondary);font-weight:600;'
                'border-bottom:2px solid #e6e6e6">자동화율</th>'
                '<th style="padding:6px 4px;font-size:16px;color:var(--text-secondary);font-weight:600;'
                'border-bottom:2px solid #e6e6e6">사람확인 대기</th>'
                '<th style="padding:6px 4px;font-size:16px;color:var(--text-secondary);font-weight:600;'
                'border-bottom:2px solid #e6e6e6">D1 미검출</th>'
                '<th style="padding:6px 4px;font-size:16px;color:var(--text-secondary);font-weight:600;'
                'border-bottom:2px solid #e6e6e6">D4 미검출</th>'
                '</tr>'
                '<tr>'
                f'<td style="padding:8px 4px;font-size:22px;font-weight:700">{CORE_KPIS[0][1]:.1%}</td>'
                f'<td style="padding:8px 4px;font-size:22px;font-weight:700">{len(open_items)}건</td>'
                f'<td style="padding:8px 4px;font-size:22px;font-weight:700;color:{d1_color}">{CORE_KPIS[1][1]:.1%}</td>'
                f'<td style="padding:8px 4px;font-size:22px;font-weight:700;color:{d4_color}">{CORE_KPIS[2][1]:.1%}</td>'
                '</tr>'
                '</table>',
                unsafe_allow_html=True,
            )

    with col_right:
        with st.container(height=PANEL_H, border=True):
            h1, h2 = st.columns([2, 1])
            h1.markdown('<p style="font-size:18px;font-weight:600;margin:0">🔎 위험도순 확인</p>', unsafe_allow_html=True)
            h2.caption(f"{len(open_items)}건")
            if not using_real:
                st.caption("⚠ 가중치 미탑재 — 더미 예시 큐")

            # 이 패널의 보고서는 주간 NCR 양식이 아니라, 이 화면(오늘의 현황)에 떠 있는
            # 값만 담은 전용 양식이다 — utils/report.py의 today_status_report_bytes() 참고.
            docx_bytes, docx_name = today_status_report_bytes(
                routing_summary=ROUTING_SUMMARY,
                core_kpis=CORE_KPIS,
                open_items=open_items,
                approved_n=approved_n,
                rejected_n=rejected_n,
                ncr_list=[(img_id, v[1]) for img_id, v in st.session_state.get("ncr_reports", {}).items()],
                spc=_spc_status(spc_daily_defect_rate(),
                                forced_spike=st.session_state.get("spc_demo_type") is not None),
                thresholds=thresholds,
            )
            r1, r2 = st.columns(2)
            r1.download_button("📄 보고서", data=docx_bytes, file_name=docx_name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                width="stretch")
            with r2:
                render_send_email_popover(
                    docx_bytes, docx_name, subject="[RT 검사] 오늘의 현황 보고서",
                    body="첨부된 오늘의 현황 보고서를 확인해 주세요. (대시보드에서 자동 생성됨)",
                    key_prefix="today_status",
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
                    c2.markdown(f"<span style='font-size:17px'>{item['image_id']} · {item['dominant_class']} · "
                                f"{item['calibrated_prob']:.2f}</span>", unsafe_allow_html=True)
                    if c3.button("검토하기", key=f"select_{item['image_id']}", width="stretch"):
                        _review_dialog(item, samples)

    # 발행된 NCR(부적합보고서) — '⛔ 최종 불량 확정' 시 자동 생성되어 세션에 쌓인다.
    # 고정 높이 패널(PANEL_H) 안에 넣으면 비좁아지므로 expander로 별도 배치.
    ncr_reports = st.session_state.get("ncr_reports", {})
    if ncr_reports:
        with st.expander(f"📄 발행된 부적합보고서(NCR) — {len(ncr_reports)}건", expanded=False):
            for img_id, (ncr_bytes, ncr_name) in ncr_reports.items():
                nc1, nc2 = st.columns([3, 1])
                nc1.markdown(f"<span style='font-size:17px'>{img_id}</span>", unsafe_allow_html=True)
                nc2.download_button(
                    "다운로드", data=ncr_bytes, file_name=ncr_name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"ncr_dl_{img_id}", width="stretch",
                )

    # ------------------------------------------------------------
    # 2단: SPC 관리도 / 특성요인도 — 작게, 시연 버튼으로 이상 상황 토글
    # ------------------------------------------------------------
    demo_type = st.session_state.get("spc_demo_type")  # None | "crack" | "porosity"

    # 특성요인도(6M)가 커지면서 실제로 필요한 높이가 늘어, 스크롤바가 안 생기게 다시 계산한 값
    # (균열계열 다이어그램 실측 566px + 제목 30px + 정렬용 여백 40px + 컨테이너 패딩 약 40px + 여유 14px).
    PANEL2_H = 690
    col_spc, col_fish = st.columns([1.3, 1])

    with col_spc:
        with st.container(height=PANEL2_H, border=True):
            # 제목은 다른 칸들과 통일되게 왼쪽 위 그대로 두고, 빈 공간은 아래 차트를
            # 키우는 쪽으로 처리한다(제목 위에 여백을 넣으면 칸마다 제목 위치가 달라짐).
            sh1, sh2 = st.columns([1.6, 1])
            sh1.markdown('<p style="font-size:18px;font-weight:600;margin:0">📊 SPC 관리도</p>', unsafe_allow_html=True)
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
                fishbone_html = _fishbone(demo_type)
                # 실제로 그려질 높이를 SVG에서 그대로 읽어서, 제목 포함 전체가 박스 안에서
                # 위아래로 균형 있게(중앙에 가깝게) 오도록 위쪽 여백을 계산한다.
                fish_h_match = re.search(r'height="([0-9.]+)"', fishbone_html)
                fish_h = float(fish_h_match.group(1)) if fish_h_match else 500.0
                fish_top_gap = max(8, (PANEL2_H - 32 - 29 - fish_h) / 2)
                st.markdown(f'<p style="font-size:18px;font-weight:600;margin:0">🔧 {label}</p>', unsafe_allow_html=True)
                st.markdown(f'<div style="height:{fish_top_gap}px"></div>', unsafe_allow_html=True)
                st.markdown(fishbone_html, unsafe_allow_html=True)
            else:
                st.markdown('<p style="font-size:18px;font-weight:600;margin:0">🔧 특성요인도</p>', unsafe_allow_html=True)
                st.markdown(
                    f'<div style="height:{PANEL2_H - 80}px;display:flex;flex-direction:column;'
                    'align-items:center;justify-content:center;text-align:center;gap:10px">'
                    '<p style="font-size:16px;color:var(--text-muted);margin:0">현재 이상 신호 없음</p></div>',
                    unsafe_allow_html=True,
                )