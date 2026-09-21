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


def _infer_all_samples():
    """samples/ 폴더의 모든 실제 이미지에 모델 추론을 1회씩 돌려 캐시해둔다.
    (임계값과 무관한 부분이라 여기서만 캐시하고, 임계값 적용은 score_real_samples에서
    매번 가볍게 다시 계산한다 — 슬라이더 바꿀 때마다 모델을 다시 돌리지 않기 위함.)
    반환: [{"image_id","path","probs","breakdown"}, ...] 또는 가중치가 없으면 None."""
    import streamlit as st
    from PIL import Image

    from utils.model import predict_ensemble
    from utils.samples import load_samples
    from utils.inference_cache import get_or_compute

    @st.cache_data(show_spinner="샘플 이미지 검사 중...")
    def _run():
        samples = load_samples()
        if not samples:
            return []
        rows = []
        for path in samples:
            try:
                img_bytes = path.read_bytes()
            except Exception:
                continue
            probs, breakdown = get_or_compute(
                img_bytes, lambda p=path: predict_ensemble(Image.open(p))
            )
            if probs is None:
                return None
            rows.append({"image_id": path.stem, "path": str(path), "probs": probs, "breakdown": breakdown})
        return rows

    return _run()


def score_real_samples(thresholds):
    """캐시된 실제 추론 결과에 현재 임계값을 적용해, 사람확인(attention) 케이스만
    심각도순으로 정렬해 돌려준다. 모델 가중치가 없으면 None(폴백 신호)을 반환한다."""
    from utils.routing import classify

    inferred = _infer_all_samples()
    if inferred is None:
        return None

    rows = []
    for item in inferred:
        probs = item["probs"]
        status = classify(probs["무결함"], probs["균열·용입불량(D1+D4)"], probs["기공(D2)"], thresholds)
        if status != "attention":
            continue
        c, p = probs["균열·용입불량(D1+D4)"], probs["기공(D2)"]
        dom_class, dom_prob = ("균열·용입불량(D1+D4)", c) if c >= p else ("기공(D2)", p)
        rows.append({
            **item,
            "status": status,
            "dominant_class": dom_class,
            "calibrated_prob": dom_prob,
            "severity_score": CLASS_WEIGHT[dom_class] * dom_prob,
        })
    rows.sort(key=lambda r: r["severity_score"], reverse=True)
    return rows
