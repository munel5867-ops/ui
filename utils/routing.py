"""
STAGE3 3단계 라우팅 로직 (팀이 합의한 실제 규칙, 순서대로 확인):
  1) prob(무결함) >= ND_CONFIDENT                        -> 자동 통과 (auto_pass)
  2) prob(D1) >= ATTENTION_T AND prob(D4) >= ATTENTION_T  -> 균열계열 의심, 사람 확인 (attention_crack)
  3) max(prob(D1), prob(D4)) >= CONFIDENT_T               -> 자동 배출/거부 (auto_reject)
  4) 그 외 (애매한 무결함)                                   -> 사람 확인 (attention)

D1(균열)·D4(미용착)가 서로 헷갈리기 쉬운 클래스라는 STAGE2 발견 때문에, 둘 다 애매하게
높으면(2번 조건) 자동배출/자동통과 판정 전에 무조건 사람에게 넘기도록 만든 안전장치다.
이 순서(1→2→3→4)를 바꾸면 안전장치가 무력화되니 순서를 유지할 것.
"""
import pandas as pd

DEFAULT_THRESHOLDS = {"nd_confident": 0.90, "attention_t": 0.15, "confident_t": 0.50}


def classify(prob_no_defect: float, prob_d1: float, prob_d4: float, thresholds: dict) -> str:
    if prob_no_defect >= thresholds["nd_confident"]:
        return "auto_pass"
    if prob_d1 >= thresholds["attention_t"] and prob_d4 >= thresholds["attention_t"]:
        return "attention_crack"
    if max(prob_d1, prob_d4) >= thresholds["confident_t"]:
        return "auto_reject"
    return "attention"


ATTENTION_STATUSES = ("attention", "attention_crack")


def route_dataframe(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    return df.apply(
        lambda r: classify(r["prob_무결함"], r["prob_균열(D1)"], r["prob_미용착(D4)"], thresholds),
        axis=1,
    )


def compute_kpis(df: pd.DataFrame, thresholds: dict) -> dict:
    routed = route_dataframe(df, thresholds)
    n = len(df)

    automation_rate = (~routed.isin(ATTENTION_STATUSES)).mean()
    human_review_rate = routed.isin(ATTENTION_STATUSES).mean()

    def miss_rate(label: str) -> float:
        mask = df["true_label"] == label
        if mask.sum() == 0:
            return 0.0
        return (routed[mask] == "auto_pass").mean()

    return {
        "automation_rate": automation_rate,
        "human_review_rate": human_review_rate,
        "d1_miss_rate": miss_rate("균열(D1)"),
        "d4_miss_rate": miss_rate("미용착(D4)"),
        "n": n,
    }
