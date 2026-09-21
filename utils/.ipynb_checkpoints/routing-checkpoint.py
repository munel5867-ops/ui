"""
STAGE3 3단계 라우팅 로직 (팀이 합의한 실제 규칙, 순서대로 확인):
  1) prob(무결함) >= ND_CONFIDENT                        -> 자동 통과 (auto_pass)
  2) prob(D1) >= ATTENTION_T AND prob(D4) >= ATTENTION_T  -> 균열계열 의심, 사람 확인 (attention_crack)
  3) max(prob(D1), prob(D4)) >= CONFIDENT_T
       AND margin(D1, D4) >= MARGIN_THRESHOLD             -> 자동 배출/거부 (auto_reject, 세부유형 확정)
  3-b) max(...) >= CONFIDENT_T 이지만 margin 기준 미달        -> 사람 확인 (attention_margin)
  4) 그 외 (애매한 무결함)                                   -> 사람 확인 (attention)

D1(균열)·D4(용입불량)가 서로 헷갈리기 쉬운 클래스라는 STAGE2 발견 때문에, 둘 다 애매하게
높으면(2번 조건) 자동배출/자동통과 판정 전에 무조건 사람에게 넘기도록 만든 안전장치다.
이 순서(1→2→3→4)를 바꾸면 안전장치가 무력화되니 순서를 유지할 것.

[margin_threshold = 90, 최종 확정 (2026-09-21)]
STAGE3 margin 분석을 filmopt 모델과 finetune 모델 둘 다에서 반복 검증한 결과:
  - filmopt: margin>=80 기준 자동확정 73.5%, 정확도 90.2%
  - finetune: margin>=80 기준 자동확정 68.1%, 정확도 89.6%
              margin 80~90 구간에서 정확도가 오히려 78.2%로 떨어지는 비정상(비단조) 패턴 발견
  - finetune: margin>=90 기준 자동확정 34.1%, 정확도 99.5%
팀은 "정확도가 최소 기준선이고, 그 안에서 자동화율을 챙긴다"는 우선순위에 따라
margin_threshold=90을 최종 채택했다. 자동확정 비율은 34.1%로 낮아지지만, 세부유형
오분류로 인한 잘못된 보수 조치(그라인딩 재용접 vs 백가우징) 위험을 최소화하기 위함이다.
80~90 구간의 비단조 패턴은 D4(용입불량) 학습 데이터가 20개 필름 중 7개 필름에만
있다는 데이터 다양성 한계로 판단했고, 학습 방식 변경(재학습)으로는 해결되지 않는다고
보아 재학습은 진행하지 않았다.

[margin 계산 기준 확률 — 반드시 확인할 것]
margin 계산은 STAGE3에서 쓴 Isotonic+Saerens 보정 후 확률 기준으로 검증됐다. 실제
모델 연결 시 prob_d1/prob_d4가 보정된 값인지(utils/model.py의 calibration_bundle
적용 여부) 반드시 확인할 것 — 보정 안 된 원본 확률로는 margin_threshold=90이라는
기준이 검증된 정확도(99.5%)를 보장하지 못한다.

[세부유형 반환]
classify()는 (status, label) 튜플을 반환한다. status가 "auto_reject"일 때만
label에 "균열(D1)" 또는 "용입불량(D4)"가 채워지고, 그 외 status에서는 label=None.
검사원이 "결함이다/아니다"만 보는 게 아니라 "어떤 결함인지"까지 화면에서 바로 봐야
조치(그라인딩 재용접 vs 백가우징)를 구분할 수 있다는 게 이 기능의 목적이므로,
label을 빼먹으면 이 기능의 존재 의미가 없어진다. tab1_inference.py 등 classify()를
호출하는 모든 곳에서 반환값이 튜플로 바뀐 것을 반영해야 한다.
"""
import pandas as pd

DEFAULT_THRESHOLDS = {
    "nd_confident": 0.90,
    "attention_t": 0.15,
    "confident_t": 0.50,
    "margin_threshold": 90.0,  # 균열/용입불량 확정 판정의 margin 기준 (%, 0~100) — 최종 채택값
}


def compute_margin(prob_d1: float, prob_d4: float) -> float:
    """균열(D1)과 용입불량(D4) 확률의 격차를 0~100 사이로 정규화.
    두 확률이 같으면(가장 애매) 0, 한쪽이 압도적이면 100에 가까워짐."""
    denom = prob_d1 + prob_d4
    if denom == 0:
        return 0.0
    return abs(prob_d1 - prob_d4) / denom * 100


def classify(prob_no_defect: float, prob_d1: float, prob_d4: float, thresholds: dict):
    """반환값: (status: str, label: str | None)
    label은 status == "auto_reject"일 때만 "균열(D1)" 또는 "용입불량(D4)"로 채워짐."""
    if prob_no_defect >= thresholds["nd_confident"]:
        return "auto_pass", None
    if prob_d1 >= thresholds["attention_t"] and prob_d4 >= thresholds["attention_t"]:
        return "attention_crack", None
    if max(prob_d1, prob_d4) >= thresholds["confident_t"]:
        if compute_margin(prob_d1, prob_d4) >= thresholds["margin_threshold"]:
            label = "균열(D1)" if prob_d1 > prob_d4 else "용입불량(D4)"
            return "auto_reject", label
        return "attention_margin", None
    return "attention", None


ATTENTION_STATUSES = ("attention", "attention_crack", "attention_margin")


def route_dataframe(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    """status만 뽑아 쓰는 KPI 계산용. 세부유형(label)까지 필요하면 route_dataframe_with_label 사용."""
    return df.apply(
        lambda r: classify(r["prob_무결함"], r["prob_균열(D1)"], r["prob_용입불량(D4)"], thresholds)[0],
        axis=1,
    )


def route_dataframe_with_label(df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """status와 label을 둘 다 컬럼으로 반환. 판정 데모/보고서 탭에서 세부유형을 보여줄 때 사용."""
    results = df.apply(
        lambda r: classify(r["prob_무결함"], r["prob_균열(D1)"], r["prob_용입불량(D4)"], thresholds),
        axis=1,
    )
    return pd.DataFrame(results.tolist(), columns=["status", "label"], index=df.index)


def compute_kpis(df: pd.DataFrame, thresholds: dict) -> dict:
    routed = route_dataframe(df, thresholds)
    n = len(df)

    automation_rate = (~routed.isin(ATTENTION_STATUSES)).mean()
    human_review_rate = routed.isin(ATTENTION_STATUSES).mean()
    margin_hold_rate = (routed == "attention_margin").mean()

    def miss_rate(label: str) -> float:
        mask = df["true_label"] == label
        if mask.sum() == 0:
            return 0.0
        return (routed[mask] == "auto_pass").mean()

    return {
        "automation_rate": automation_rate,
        "human_review_rate": human_review_rate,
        "margin_hold_rate": margin_hold_rate,
        "d1_miss_rate": miss_rate("균열(D1)"),
        "d4_miss_rate": miss_rate("용입불량(D4)"),
        "n": n,
    }