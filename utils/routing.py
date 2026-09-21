"""
Difetto1(균열)·Difetto4(용입불량)가 서로 헷갈리기 쉬운 클래스라는 문제(fold1 상호
오분류 80.8%, Grad-CAM 공통 최약체, 임계값 스윕에서 확률이 두 클래스로 쪼개져
기본 임계값을 못 넘는 현상)를 임계값 조정만으로는 근본적으로 해결하지 못해, 팀은
두 클래스를 하나의 판정 범주(CrackOrLoP)로 통합하기로 했다. 자세한 근거는
STAGE3 최종보고서 참고.

이제 판정은 3범주다:
  - 무결함
  - 균열·용입불량(D1+D4 통합)
  - 기공(D2)  — 원형 결함으로 형태학적으로 명확히 구분돼 통합 대상에서 제외

라우팅 규칙(순서대로 확인):
  1) prob(무결함) >= ND_CONFIDENT           -> 자동 통과 (auto_pass)
  2) prob(균열·용입불량) >= CRACK_OR_LOP_T   -> 자동 배출 (auto_reject)
  3) prob(기공) >= POROSITY_T                -> 자동 배출 (auto_reject)
  4) 그 외 (애매한 경우)                      -> 사람 확인 (attention)

CRACK_OR_LOP_T = 0.2823 (2026-09-19 갱신) — STAGE3 최종 보고서 종합결론의 최종
채택안. 백본 마지막 20층 미세조정 + 이미지 증강(회전·명암·이동) 반영 모델, 비용비
3:1 기준 재현율 95.98%, 정밀도 97.37%, 오경보율 2.62%. fold별 재현율 표준편차
0.0475(비용비 5:1 기준)로 안정성도 확인됨. 이 값은 utils/model.py가
efficientnetb0_finetune_fold0~4 가중치를 쓸 때만 유효하다 — 가중치를 다른
버전으로 교체하면 이 임계값도 그 모델의 비용기반 스윕 결과로 다시 맞출 것.
"""
import pandas as pd

DEFAULT_THRESHOLDS = {
    "nd_confident": 0.90,
    "crack_or_lop_t": 0.2823,
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
