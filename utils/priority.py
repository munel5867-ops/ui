"""
'심각도 기반 정렬 큐' — 사람 확인(attention) 케이스를 시간순이 아니라
심각도(= 클래스 위험 가중치 × 보정 확률) 내림차순으로 정렬한다.

라우팅 상태는 attention 하나뿐이라, 그 안에서 두 결함 클래스(균열·용입불량 vs
기공) 중 확률이 더 높은 쪽을 "지배 클래스"로 보고, 안전 직결도가 높은
균열·용입불량 쪽에 더 큰 가중치를 준다.
"""
import numpy as np
import pandas as pd

from utils.routing import ATTENTION_STATUSES, route_dataframe

CLASS_WEIGHT = {
    "균열·용입불량(D1+D4)": 2.0,  # 안전 직결 — 우선
    "기공(D2)": 1.0,
}


def _dominant(row):
    c, p = row["prob_균열·용입불량(D1+D4)"], row["prob_기공(D2)"]
    return ("균열·용입불량(D1+D4)", c) if c >= p else ("기공(D2)", p)


def build_priority_queue(df, thresholds, top_n=12):
    routed = route_dataframe(df, thresholds)
    mask = routed.isin(ATTENTION_STATUSES)
    sub = df[mask].copy()
    sub["status"] = routed[mask]

    dom = sub.apply(_dominant, axis=1, result_type="expand")
    sub["dominant_class"], sub["calibrated_prob"] = dom[0], dom[1]
    sub["severity_score"] = sub["dominant_class"].map(CLASS_WEIGHT) * sub["calibrated_prob"]

    return sub.sort_values("severity_score", ascending=False).head(top_n).reset_index(drop=True)


# ---- SPC 이상 신호 + 6M 원인 스크리닝 ----
SIX_M_FACTORS = ["사람(Man)", "설비(Machine)", "재료(Material)", "방법(Method)", "측정(Measurement)", "환경(Environment)"]


def spc_alert(df):
    cl = df["defect_rate"].mean()
    std = df["defect_rate"].std()
    ucl = cl + 3 * std
    latest = df.iloc[-1]
    return {
        "breached": bool(latest["defect_rate"] > ucl),
        "date": latest["date"], "value": float(latest["defect_rate"]),
        "ucl": float(ucl), "cl": float(cl),
    }


def six_m_ranking(seed=3):
    """실제 공정변수 로그 연동 전까지 쓰는 더미 순위 — 나중에 상관계수 계산으로 교체."""
    rng = np.random.default_rng(seed)
    scores = rng.uniform(0.2, 0.95, size=len(SIX_M_FACTORS))
    df = pd.DataFrame({"요인": SIX_M_FACTORS, "연관도": scores})
    return df.sort_values("연관도", ascending=False).reset_index(drop=True)
