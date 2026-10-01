"""
STAGE4 3구간 라우팅 로직 — 보고서 STAGE4 1-1 "균열·용입불량 1차 선별(방안 2)" 기준.

판정 흐름 (균열·용입불량 점수 · 기공 · 양품은 3클래스 보정 확률, margin은 4클래스 보정 확률):
  ① 균열·용입불량 점수(crack_score) >= CRACK_T (기본 0.3781)
       ├ margin(D1, D4) >= MARGIN_T (기본 98) -> 자동 배출 (auto_reject), 라벨 "균열(D1)" 또는 "용입불량(D4)" (확정)
       └ margin(D1, D4) <  MARGIN_T           -> 사람 확인 (attention_margin), 라벨 "균열(D1)" 또는 "용입불량(D4)" (추정)
  ② 균열·용입불량 점수 < CRACK_T
       ├ 기공 > 양품   -> 자동 배출 (auto_reject), 라벨 "기공(D2)"
       └ 양품 >= 기공  -> 자동 통과 (auto_pass)

사람이 확인하는 경우는 "균열·용입불량으로 선별됐지만 margin이 기준 미만" 하나뿐이다
(attention_margin). 이때도 AI가 추정한 유형(label)을 같이 돌려주므로, 화면에서는 반드시
"추정"이라고 표시해야 한다 — 확정(auto_reject)과 구분되지 않으면 오조치로 이어진다.

[margin_threshold = 98]
보고서 STAGE4 1-1 기준으로 margin 98을 채택했다. 검증 기준 자동 확정 정확도는 95.14%
(운영 기준 약 93.3%)이다.

[균열·용입불량 점수(crack_score) — 반드시 확인할 것]
D1+D4 원본 확률의 합을 3클래스(균열·용입불량 / 기공 / 양품)로 보정한 값이다.
utils/model.py의 predict_ensemble()이 models/calibration_bundle_3cls_finetune.pkl을
적용해서 probs에 crack_score, p3_D2, p3_ND 세 키를 추가해 돌려준다. 이 파일이 없으면
D1+D4 합 근사값으로 대신 계산하는데, 이 값에 0.3781을 그대로 쓰면 보고서 기준과 다른
결과가 나온다.

[margin 계산 기준 확률]
margin은 4클래스 Isotonic+Saerens 보정 후 확률(utils/model.py의 calibration_bundle)
기준이다: |D1-D4| / (D1+D4) x 100. 보정 안 된 원본 확률로는 검증된 정확도를 보장하지 못한다.

[반환값]
classify()는 (status, label) 튜플을 반환한다. auto_reject / attention_margin일 때 label에
"균열(D1)", "용입불량(D4)", "기공(D2)" 중 하나가 채워지고, auto_pass는 label=None.
"""
import pandas as pd

DEFAULT_THRESHOLDS = {
    "crack_t": 0.3781,         # 균열·용입불량 1차 선별 기준 (3클래스 보정 점수, 비용비 3:1)
    "margin_threshold": 98.0,  # 균열/용입불량 유형 확정 margin 기준 (%, 0~100)
}

# 화면(확률 막대·이력·NCR)에 보여주는 4개 클래스 키 — predict_ensemble()이 probs에
# 내부용 키(crack_score, p3_D2, p3_ND)도 같이 담아 돌려주므로, 화면에 쓸 때는 이 키만 골라 쓴다.
CLASS_KEYS = ["무결함", "균열(D1)", "기공(D2)", "용입불량(D4)"]


def compute_margin(prob_d1: float, prob_d4: float) -> float:
    """균열(D1)과 용입불량(D4) 확률의 격차를 0~100 사이로 정규화.
    두 확률이 같으면(가장 애매) 0, 한쪽이 압도적이면 100에 가까워짐."""
    denom = prob_d1 + prob_d4
    if denom == 0:
        return 0.0
    return abs(prob_d1 - prob_d4) / denom * 100


def classify(probs: dict, thresholds: dict):
    """반환값: (status: str, label: str | None)
    probs: 확률 딕셔너리 — 4개 클래스 키(무결함/균열(D1)/기공(D2)/용입불량(D4))는 필수,
           crack_score / p3_D2 / p3_ND(3클래스 보정 확률)는 있으면 쓰고 없으면 근사값으로 대체.
    보고서 STAGE4 1-1 균열·용입불량 1차 선별 라우팅."""
    d1, d4 = probs["균열(D1)"], probs["용입불량(D4)"]
    crack = probs.get("crack_score", d1 + d4)  # 3클래스 보정기가 없으면 근사값
    d2 = probs.get("p3_D2", probs["기공(D2)"])
    nd = probs.get("p3_ND", probs["무결함"])

    crack_t = thresholds.get("crack_t", DEFAULT_THRESHOLDS["crack_t"])
    margin_t = thresholds.get("margin_threshold", DEFAULT_THRESHOLDS["margin_threshold"])

    if crack >= crack_t:
        label = "균열(D1)" if d1 > d4 else "용입불량(D4)"
        if compute_margin(d1, d4) >= margin_t:
            return "auto_reject", label        # 확정
        return "attention_margin", label       # 추정 + 사람 확인
    if d2 > nd:
        return "auto_reject", "기공(D2)"
    return "auto_pass", None


ATTENTION_STATUSES = ("attention_margin",)


def _row_to_probs(r) -> dict:
    """검증 데이터프레임의 한 행(prob_* 열)을 classify()가 받는 확률 딕셔너리로 바꾼다."""
    p = {k: r[f"prob_{k}"] for k in CLASS_KEYS}
    for k in ["crack_score", "p3_D2", "p3_ND"]:
        if k in r and pd.notna(r[k]):
            p[k] = r[k]
    return p


def route_dataframe(df: pd.DataFrame, thresholds: dict) -> pd.Series:
    """status만 뽑아 쓰는 KPI 계산용. 세부유형(label)까지 필요하면 route_dataframe_with_label 사용."""
    return df.apply(lambda r: classify(_row_to_probs(r), thresholds)[0], axis=1)


def route_dataframe_with_label(df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """status와 label을 둘 다 컬럼으로 반환. 판정 데모/보고서 탭에서 세부유형을 보여줄 때 사용."""
    results = df.apply(lambda r: classify(_row_to_probs(r), thresholds), axis=1)
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