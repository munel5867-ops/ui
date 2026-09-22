import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 전체 차트에서 공통으로 쓰는 폰트 — style.py의 페이지 CSS와 통일시키기 위함.
# Plotly는 브라우저 CSS를 안 따르고 SVG에 직접 폰트를 그리므로, 차트마다 이 값을 넣어줘야 함.
CHART_FONT = dict(family="Pretendard, Malgun Gothic, sans-serif", size=24)

# 아래 수치는 STAGE1~2 단계에서 실제로 측정된 검증 결과다 (필름 단위
# StratifiedGroupKFold 5-fold 교차검증). 균열(D1)·용입불량(D4) 통합 결정은
# 바로 이 수치들(특히 fold1 혼동행렬, 특이도·Grad-CAM 최약체 결과)에서
# 나왔으므로, 통합 이전 4클래스 개별 분석 그대로 남겨둔다 — 이게 "왜
# 통합했는가"에 대한 근거 자체이기 때문이다.
CLASSES = ["D1 균열", "D2 기공", "D4 용입불량", "ND 무결함"]

SPECIFICITY = pd.DataFrame({
    "클래스": CLASSES,
    "MobileNetV2": [0.953, 0.948, 0.927, 0.929],
    "EfficientNetB0": [0.971, 0.979, 0.912, 0.959],
    "목표": [0.99, 0.99, 0.99, 0.99],
})

AUC = pd.DataFrame({
    "클래스": CLASSES,
    "PR-AUC(Mobile)": [0.825, 0.858, 0.770, 0.975],
    "PR-AUC(EffNet)": [0.912, 0.952, 0.849, 0.988],
    "ROC-AUC(EffNet)": [0.962, 0.990, 0.948, 0.996],
})

SEG_IOU = pd.DataFrame({"클래스": CLASSES, "IoU": [0.6173, 0.7857, 0.5674, 1.0000]})

GCAM = pd.DataFrame({
    "클래스": ["D1 균열", "D2 기공", "D4 용입불량", "ND 무결함"],
    "IoU": [0.345, 0.365, 0.156, 0.000],
    "커버리지": [0.795, 0.738, 0.562, 0.000],
    "표본": [29, 30, 30, 30],
})

DATA_STATS = [
    ("원본 이미지", "24,407장"),
    ("클래스", "4개 (ND·CR·PO·LP)"),
    ("타일 규격", "227×227"),
    ("독립 필름", "29개"),
]

LEAK_STATS = [
    ("필름 교차 비율", "96.6%", "29개 중 28개가 학습·테스트 양쪽에 걸침"),
    ("완전 중복 파일", "2,443건", "학습에서 이미 본 이미지가 테스트에 그대로 포함"),
    ("인접 타일 교차", "54.0%", "같은 필름의 인접 조각이 양쪽에 나뉘어 들어감"),
]

SPLIT = pd.DataFrame({
    "구분": ["필름 수", "이미지 장수(중복 제거 후)", "ND 무결함", "CR 균열(D1)", "PO 기공(D2)", "LP 용입불량(D4)"],
    "학습": ["20개", "15,348장", "3,646", "4,778", "3,998", "2,926"],
    "테스트": ["9개", "6,588장", "1,754", "2,092", "1,662", "1,080"],
})


def _color_scale(val, good, warn_lo):
    if val >= good:
        return "background-color:#E8F5EC;color:#1E7A46"
    if val >= warn_lo:
        return "background-color:#FBF3E2;color:#B8860B"
    return "background-color:#FBEAEA;color:#C0392B"


def render():
    st.subheader("모델 비교 — 베이스라인 대비 개선폭")
    c1, c2, c3 = st.columns(3)
    c1.metric("HOG + 로지스틱회귀", "43%", help="전통 기법 하한선 · 1회 평가")
    c2.metric("MobileNetV2", "81.7%", help="5-fold 평균")
    c3.metric("EfficientNetB0 (채택)", "87.2%", help="5-fold 평균 · 최종 채택")

    st.divider()

    st.subheader("클래스별 특이도 (5-fold 평균)")
    st.caption("이 표는 균열(D1)·용입불량(D4) 통합 이전, 4클래스 개별 모델 기준 결과입니다 — 통합 결정의 근거 자료입니다.")
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(
            SPECIFICITY.style.map(
                lambda v: _color_scale(v, 0.97, 0.93) if isinstance(v, float) else "",
                subset=["MobileNetV2", "EfficientNetB0"],
            ).format({"MobileNetV2": "{:.3f}", "EfficientNetB0": "{:.3f}", "목표": "{:.2f}"}),
            width="stretch", hide_index=True,
        )
    with col2:
        fig = px.bar(SPECIFICITY, x="클래스", y=["MobileNetV2", "EfficientNetB0"], barmode="group")
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), font=CHART_FONT)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.warning("두 모델 모두 특이도 목표치(0.99)에 미달했고, D4(용입불량)는 두 모델 다 최저치이자 fold 간 편차도 가장 큽니다 — 균열·용입불량 통합 결정의 핵심 근거입니다.")

    st.subheader("PR-AUC · ROC-AUC")
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(AUC, width="stretch", hide_index=True)
    with col2:
        fig = px.bar(AUC, x="클래스", y=["PR-AUC(EffNet)", "ROC-AUC(EffNet)"], barmode="group")
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), font=CHART_FONT)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("클래스 불균형 상황에서 ROC는 낙관적으로 보이는 경향이 있어, 실제 라인처럼 불량률이 낮을 때는 PR 지표를 우선 판단 근거로 삼습니다.")

    st.subheader("fold1 혼동행렬 — D1↔D4 오분류 확인")
    cm = pd.DataFrame(
        [[79, 22, 425, 0], [0, 301, 8, 2], [18, 1, 1025, 0], [0, 0, 0, 737]],
        index=["실제 D1", "실제 D2", "실제 D4", "실제 ND"],
        columns=["예측 D1", "예측 D2", "예측 D4", "예측 ND"],
    )
    fig = px.imshow(cm, text_auto=True, color_continuous_scale="Blues")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), font=CHART_FONT)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.error("D1 행만 대각선(79)보다 오분류 칸(425, D4로 오분류)이 훨씬 큽니다 — fold1 검증셋의 필름 쏠림이 원인으로 추정되며, 균열·용입불량 통합 판정의 직접적 계기입니다.")

    st.divider()

    st.subheader("판정 근거 검증")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**세그멘테이션 (U-Net)**")
        st.dataframe(SEG_IOU, width="stretch", hide_index=True)
        fig = px.bar(SEG_IOU, x="클래스", y="IoU", color="클래스")
        fig.update_layout(height=260, showlegend=False, margin=dict(l=10, r=10, t=10, b=10), font=CHART_FONT)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.success("전체 평균 IoU 0.7426으로 기준(0.5)을 상회 — Grad-CAM 검증용 정답 마스크로 채택.")
    with col2:
        st.markdown("**Grad-CAM 정량 검증 — IoU vs 커버리지**")
        st.dataframe(GCAM, width="stretch", hide_index=True)
        fig = px.bar(GCAM, x="클래스", y=["IoU", "커버리지"], barmode="group")
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), font=CHART_FONT)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.error("D4는 커버리지(0.562)도 세 클래스 중 가장 낮습니다 — 모델이 주목하는 위치 자체가 불안정하다는 뜻이며, 특이도·혼동행렬 결과와 같은 결론을 가리킵니다.")

    st.divider()

    st.subheader("데이터 이력 · 무결성 검증")
    cols = st.columns(4)
    for col, (label, val) in zip(cols, DATA_STATS):
        col.metric(label, val)

    st.markdown("**공식 분할에서 발견된 데이터 누수**")
    cols = st.columns(3)
    for col, (label, val, note) in zip(cols, LEAK_STATS):
        col.metric(label, val, help=note, delta_color="off")
    st.error("같은 필름의 조각을 학습에서 이미 본 상태로 테스트를 보게 되어 점수가 과대평가됩니다 — 필름 단위 재분할로 해결했습니다.")

    st.markdown("**필름 단위 재분할 결과**")
    st.dataframe(SPLIT, width="stretch", hide_index=True)
    st.success("학습·테스트에 동시에 들어간 필름 0개. 테스트셋 6,588장은 개발 전 과정에서 사용하지 않고 봉인 상태를 유지 중입니다.")