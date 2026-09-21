"""
전 탭에서 공유하는 시각 디자인 시스템 (색상 팔레트 + CSS + 배지 헬퍼).

색상은 색약 접근성 기준(OKLab Delta E)을 통과한 검증된 팔레트에서 가져왔다.
새 색이 필요하면 여기 팔레트 슬롯 안에서 고르고, 임의의 색을 새로 만들지 말 것.
"""
import streamlit as st

BRAND_BLUE = "#2a78d6"
BRAND_NAVY = "#184f95"
PAGE_BG = "#f9f9f7"
INK_SECONDARY = "#52514e"

STATUS_COLORS = {
    "auto_pass": {"bg": "#0ca30c", "icon": "✅", "label": "자동 통과"},
    "attention": {"bg": "#fab219", "icon": "⚠", "label": "사람 확인 필요"},
    "attention_crack": {"bg": "#ec835a", "icon": "⚠", "label": "사람 확인 필요 · 균열계열 의심"},
    "auto_reject": {"bg": "#d03b3b", "icon": "⛔", "label": "자동 배출"},
}

CLASS_COLORS = {
    "무결함": "#1baf7a",
    "균열·용입불량(D1+D4)": "#e34948",
    "기공(D2)": "#eda100",
}


def inject_css():
    css = """
    <style>
    .stApp {
        background-color: """ + PAGE_BG + """;
    }
    .rt-header {
        background: linear-gradient(135deg, """ + BRAND_NAVY + """ 0%, """ + BRAND_BLUE + """ 100%);
        color: #fff;
        padding: 28px 32px;
        border-radius: 14px;
        margin-bottom: 18px;
    }
    .rt-header h1 {
        margin: 0;
        font-size: 34px;
        font-weight: 800;
        letter-spacing: -0.3px;
        line-height: 1.25;
    }
    .rt-header p {
        margin: 6px 0 0;
        font-size: 15px;
        opacity: 0.85;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #eef2f8;
        border-radius: 8px 8px 0 0;
        padding: 8px 18px;
        font-weight: 600;
        color: """ + INK_SECONDARY + """;
    }
    .stTabs [aria-selected="true"] {
        background-color: """ + BRAND_BLUE + """ !important;
        color: #fff !important;
    }
    .rt-badge {
        display: inline-block;
        padding: 7px 18px;
        border-radius: 20px;
        font-size: 14px;
        font-weight: 700;
        color: #fff;
    }
    .rt-alert-banner {
        background: #fdecea;
        border: 1px solid #d03b3b;
        color: #7a1f1f;
        padding: 12px 18px;
        border-radius: 10px;
        margin-bottom: 14px;
        font-size: 14px;
        font-weight: 600;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def status_badge(status: str) -> str:
    s = STATUS_COLORS[status]
    return '<span class="rt-badge" style="background:' + s["bg"] + ';">' + s["icon"] + " " + s["label"] + "</span>"


def status_tag(status: str) -> str:
    s = STATUS_COLORS[status]
    return (
        '<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        'font-size:11px;font-weight:600;background:' + s["bg"] + '22;color:' + s["bg"] + ';">' + s["label"] + "</span>"
    )
