"""
전 탭에서 공유하는 시각 디자인 시스템 (색상 팔레트 + CSS + 배지 헬퍼).

색상은 색약 접근성 기준(OKLab Delta E)을 통과한 검증된 팔레트에서 가져왔다.
새 색이 필요하면 여기 팔레트 슬롯 안에서 고르고, 임의의 색을 새로 만들지 말 것.
"""
import streamlit as st

BRAND_BLUE = "#0c92da"  # 메인테마(#032639)와 같은 색상군의 밝은 강조색
BRAND_NAVY = "#032639"  # 메인테마 색 (RGB 3,38,57)
PAGE_BG = "#f9f9f7"
INK_SECONDARY = "#52514e"

STATUS_COLORS = {
    "auto_pass": {"bg": "#0ca30c", "icon": "✅", "label": "자동 통과"},
    "attention": {"bg": "#fab219", "icon": "⚠", "label": "사람 확인 필요"},
    "attention_crack": {"bg": "#ec835a", "icon": "⚠", "label": "사람 확인 필요 · 균열계열 의심"},
    "attention_margin": {"bg": "#eda100", "icon": "⚠", "label": "사람 확인 필요 · 균열/용입불량 경계 모호"},
    "auto_reject": {"bg": "#d03b3b", "icon": "⛔", "label": "자동 배출"},
}

CLASS_COLORS = {
    "무결함": "#1baf7a",
    "균열(D1)": "#e34948",
    "기공(D2)": "#eda100",
    "용입불량(D4)": "#eb6834",
}


def inject_css():
    # IBM Plex Sans KR 웹폰트 — Fontsource가 jsDelivr에 올려둔 정적 파일을 직접
    # @font-face로 선언한다(구글 폰트 CDN이 아니라서, 전에 겪은 fonts.gstatic.com
    # 차단 이슈와는 무관한 별도 경로). 한글(korean)·영문/숫자(latin) 서브셋을
    # 모두 선언해야 화면에 실제로 다 적용된다. 실패해도 다음 순번(맑은 고딕)으로
    # 자연스럽게 대체된다.
    _FONT_BASE = "https://cdn.jsdelivr.net/fontsource/fonts/ibm-plex-sans-kr@5.3.0"
    _weights = [400, 500, 600, 700]
    font_face_rules = "\n".join(
        f"""
    @font-face {{
        font-family: 'IBM Plex Sans KR';
        font-style: normal;
        font-display: swap;
        font-weight: {w};
        src: url('{_FONT_BASE}/korean-{w}-normal.woff2') format('woff2');
    }}
    @font-face {{
        font-family: 'IBM Plex Sans KR';
        font-style: normal;
        font-display: swap;
        font-weight: {w};
        src: url('{_FONT_BASE}/latin-{w}-normal.woff2') format('woff2');
    }}"""
        for w in _weights
    )

    css = """
    <style>
    """ + font_face_rules + """

    /* 폰트 종류 통일 + 기본 굵기를 살짝 두껍게(500) — "굵은 걸 많이 써줘" 요청 반영.
       Streamlit이 컴포넌트마다 다른 클래스를 자동 생성해서 붙이므로, 이를 다 잡아내려면
       html/body와 와일드카드까지 넓게 걸어야 한다. */
    html, body, [class*="css"], * {
        font-family: 'IBM Plex Sans KR', 'Malgun Gothic', '맑은 고딕', sans-serif !important;
    }
    html, body, p, span, div, label {
        font-weight: 500;
    }

    .stApp {
        background-color: """ + PAGE_BG + """;
    }
    /* 본문 좌우 여백은 고정값(2rem)으로 직접 관리한다. 배너는 이 여백만큼
       음수 마진을 줘서 화면 끝까지 채운다 — 뷰포트 폭(vw) 기준 트릭은
       사이드바가 있으면 계산이 어긋나 배너 왼쪽이 잘리는 문제가 있었는데,
       이 방식은 사이드바 유무·폭과 완전히 무관해서 안전하다. */
    .block-container, [data-testid="stMainBlockContainer"] {
        /* 배너를 position:fixed로 화면에 고정하면 배너가 문서 흐름에서
           빠지므로, 그 높이(약 132px)만큼 본문 위쪽 여백을 직접 확보해야
           본문이 배너 뒤에 가려지지 않는다. */
        padding-top: 132px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    /* Streamlit 자체 상단 헤더바(Deploy 버튼 등이 있는 얇은 띠) — 이 때문에
       배너/사이드바 위에 여백이 생겨서 숨긴다. 배포 후엔 이 버튼이 굳이
       필요 없다는 점을 감안한 선택. */
    .stAppHeader, [data-testid="stToolbar"], [data-testid="stStatusWidget"] {
        display: none !important;
    }
    /* 배너를 스크롤해도 화면 위에 고정 */
    .rt-header-sticky-wrap {
        /* sticky는 조상 요소의 overflow 설정에 따라 동작이 깨지는 경우가
           있어서(그걸 고치려다 스크롤 자체를 망가뜨린 적 있음), 조상 구조와
           완전히 무관하게 동작하는 fixed로 바꾼다 — 뷰포트 기준으로 그냥
           화면 맨 위에 못박아 놓는 방식이라 부작용이 없다.
           사이드바는 배너 높이(132px)만큼 아래에서 시작하도록 따로 밀어놨지만,
           혹시라도 겹치는 경우에 배너가 무조건 위에 그려지도록 z-index를
           사이드바보다 훨씬 높게 못박아 둔다. */
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 999999;
    }
    .rt-header {
        background: linear-gradient(135deg, """ + BRAND_NAVY + """ 0%, """ + BRAND_BLUE + """ 100%);
        color: #fff;
        padding: 28px 2rem;
        border-radius: 0;
        margin: 0;
        width: 100%;
        box-sizing: border-box;
    }
    .rt-header h1 {
        margin: 0;
        font-size: 32px;
        font-weight: 700 !important;
        letter-spacing: -0.3px;
        line-height: 1.25;
    }
    .rt-header p {
        margin: 6px 0 0;
        font-size: 16px;
        font-weight: 600;
        opacity: 0.9;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #eef2f8;
        border-radius: 8px 8px 0 0;
        padding: 8px 18px;
        font-weight: 700;
        font-size: 16px;
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
        font-size: 16px;
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
        font-size: 16px;
        font-weight: 700;
    }

    /* ------------------------------------------------------------------
       탭②③④⑤⑥ 최저 글자 크기 보장 — 지금까지 커스텀 크기를 지정한 적이
       없어서 Streamlit 기본값(작음) 그대로였던 위젯들. data-testid 기준으로
       걸어야 Streamlit 버전이 바뀌어도 비교적 안정적으로 유지된다.
       ⚠ 예외: st.dataframe 안의 셀 글자는 Streamlit이 별도 렌더링 엔진
       (그리드 컴포넌트)으로 그려서 이 CSS로 크기 조절이 안 된다.
       ------------------------------------------------------------------ */
    .stCaption, [data-testid="stCaptionContainer"] p {
        font-size: 16px !important;
        font-weight: 500 !important;
    }
    .stSlider label p, .stNumberInput label p, .stSelectbox label p,
    .stTextInput label p, .stRadio label p {
        font-size: 16px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 16px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 26px !important;
        font-weight: 800 !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 15px !important;
        font-weight: 600 !important;
    }
    [data-testid="stExpander"] summary p, .streamlit-expanderHeader {
        font-size: 17px !important;
        font-weight: 700 !important;
    }
    .stAlert p {
        font-size: 16px !important;
        font-weight: 600 !important;
    }
    h1, h2, h3 { font-weight: 800 !important; }
    h4, h5, h6 { font-weight: 700 !important; }
    [data-testid="stIconMaterial"] {
        font-size: 0 !important;
        width: 0 !important;
        overflow: hidden !important;
    }
    /* ------------------------------------------------------------------
       사이드바 메뉴 — 이제 iframe 없는 순수 Streamlit 버튼이라, 이 CSS로
       완전히 제어된다(이전의 streamlit-option-menu는 iframe 안에서 그려져서
       외부 CSS가 안 닿는 부분이 있었다).
       ------------------------------------------------------------------ */
    section[data-testid="stSidebar"] {
        background-color: """ + BRAND_NAVY + """ !important;
        padding: 0 !important;
        /* 배너(fixed, 높이 132px)랑 안 겹치게 그만큼 아래에서 시작하고,
           그만큼 높이도 줄인다 — z-index로 덮어서 가리는 방식은 배너 글자
           앞부분이 실제로 사이드바 뒤에 가려지는 문제가 있어서 이 방식으로 바꿈 */
        margin-top: 132px !important;
        min-height: calc(100vh - 132px) !important;
        height: calc(100vh - 132px) !important;
        overflow-y: auto !important;
        /* 스크롤해도 화면에 고정 (배너 바로 아래 지점에서 고정) */
        position: sticky !important;
        top: 132px !important;
        align-self: flex-start !important;
        z-index: 1 !important;
    }
    [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] {
        padding: 12px !important;
    }
    .rt-sidebar-title {
        color: #fff !important;
        font-size: 27px !important;
        font-weight: 700 !important;
        margin: 8px 4px 16px;
    }
    /* 메뉴 버튼들 — 아이콘+라벨, 왼쪽 정렬, 다크 테마 */
    section[data-testid="stSidebar"] .stButton button {
        width: 100%;
        display: flex !important;
        justify-content: flex-start !important;
        text-align: left;
        background-color: transparent;
        color: #c7ccd4;
        border: none;
        border-radius: 10px;
        padding: 12px 14px;
        font-size: 22px !important;
        font-weight: 700 !important;
        box-shadow: none;
    }
    /* Streamlit이 버튼 라벨을 감싸는 내부 div/span이 또 자체적으로 가운데
       정렬(justify-content:center)을 걸고 있어서, 바깥 button에만 걸면 안 먹힌다.
       버튼 안의 모든 자식에도 강제로 왼쪽 정렬을 건다. */
    section[data-testid="stSidebar"] .stButton button * {
        justify-content: flex-start !important;
        text-align: left !important;
        width: auto !important;
        font-size: 22px !important;
        font-weight: 700 !important;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        background-color: rgba(255, 255, 255, 0.08);
        color: #fff;
        border: none;
    }
    section[data-testid="stSidebar"] .stButton button:focus:not(:active) {
        border: none;
        box-shadow: none;
    }
    section[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
        background-color: """ + BRAND_BLUE + """ !important;
        color: #fff !important;
    }
    section[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover {
        background-color: """ + BRAND_BLUE + """ !important;
        color: #fff !important;
    }
    /* 버튼 하나하나가 각자 위젯이라 Streamlit 기본 세로 간격이 넓게 붙는다 —
       메뉴 항목 사이 간격을 좁혀서 촘촘한 메뉴처럼 보이게 함 */
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
        gap: 4px !important;
    }
    [data-testid="stAppViewContainer"] {
        align-items: flex-start !important;
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
        'font-size:16px;font-weight:700;background:' + s["bg"] + '22;color:' + s["bg"] + ';">' + s["label"] + "</span>"
    )
