"""
STAGE3 갱신 (2026-09-19): Difetto1(균열)·Difetto4(미용착)가 서로 헷갈리기 쉬운
클래스라는 문제(STAGE1 fold1 상호 오분류 80.8%, STAGE2 Grad-CAM 공통 최약체,
STAGE3 임계값 스윕에서 확률이 두 클래스로 쪼개져 기본 임계값을 못 넘는 현상)를
임계값 조정만으로는 근본적으로 해결하지 못해, 팀은 두 클래스를 하나의 판정
범주(CrackOrLoP)로 통합하기로 했다. 자세한 근거는 STAGE3_최종보고서 참고.

이제 판정은 3범주다:
  - 무결함
  - 균열·용입불량(D1+D4 통합)
  - 기공(D2)  — 원형 결함으로 형태학적으로 명확히 구분돼 통합 대상에서 제외

라우팅 규칙(순서대로 확인):
  1) prob(무결함) >= ND_CONFIDENT           -> 자동 통과 (auto_pass)
  2) prob(균열·용입불량) >= CRACK_OR_LOP_T   -> 자동 배출 (auto_reject)
  3) prob(기공) >= POROSITY_T                -> 자동 배출 (auto_reject)
  4) 그 외 (애매한 경우)                      -> 사람 확인 (attention)

CRACK_OR_LOP_T 기본값(0.1982)은 STAGE3 보고서 5.3절 — "기저모델(현재 weights/
폴더에 배포된, 백본 동결 상태의 가중치) + D1·D4 통합" 기준 비용비 3:1 임계값이다.
보고서의 최종 채택 목표치는 0.2823(재현율 95.98%/정밀도 97.37%)이지만, 이는
백본 마지막 20층을 미세조정+증강한 새 모델 기준 수치라서, 새 가중치 파일이
weights/ 폴더에 들어오기 전까지 그 값을 쓰면 지금 배포된 모델과 안 맞는
임계값을 적용하게 된다. 새 가중치가 들어오면 CRACK_OR_LOP_T를 0.2823으로
갱신할 것.
"""
import pandas as pd

DEFAULT_THRESHOLDS = {
    "nd_confident": 0.90,
    "crack_or_lop_t": 0.1982,
    "porosity_t": 0.50,
}


def classify(prob_no_defect: float, prob_crack_or_lop: float, prob_porosity: float, thresholds: dict) -> str:
    if prob_no_defect >= thresholds["nd_confident"]:
        return "auto_pass"
    if prob_crack_or_lop >= thresholds["crack_or_lop_t"]:
        return "auto_reject"
    if prob_porosity >= thresholds["porosity_t"]:
        return "auto_reject"
    return "attention"


ATTENTION_STATUSES = ("attention",)


def route_dataframe(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    return df.apply(
        lambda r: classify(
            r["prob_무결함"], r["prob_균열·용입불량(D1+D4)"], r["prob_기공(D2)"], thresholds
        ),
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
        "crack_or_lop_miss_rate": miss_rate("균열·용입불량(D1+D4)"),
        "porosity_miss_rate": miss_rate("기공(D2)"),
        "n": n,
    }
