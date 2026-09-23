import numpy as np
import pandas as pd

from utils.routing import ATTENTION_STATUSES, route_dataframe_with_label

CLASS_WEIGHT = {
    "균열(D1)": 2.0,
    "용입불량(D4)": 2.0,
    "기공(D2)": 1.0,
}


def _dominant(row):
    candidates = {
        "균열(D1)": row["prob_균열(D1)"],
        "용입불량(D4)": row["prob_용입불량(D4)"],
        "기공(D2)": row["prob_기공(D2)"],
    }
    dom_class = max(candidates, key=candidates.get)
    return dom_class, candidates[dom_class]


def build_priority_queue(df, thresholds, top_n=12):
    routed = route_dataframe_with_label(df, thresholds)
    mask = routed["status"].isin(ATTENTION_STATUSES)
    sub = df[mask].copy()
    sub["status"] = routed.loc[mask, "status"]
    sub["ai_label"] = routed.loc[mask, "label"]

    dom = sub.apply(_dominant, axis=1, result_type="expand")
    sub["dominant_class"], sub["calibrated_prob"] = dom[0], dom[1]
    sub["severity_score"] = sub["dominant_class"].map(CLASS_WEIGHT) * sub["calibrated_prob"]

    return sub.sort_values("severity_score", ascending=False).head(top_n).reset_index(drop=True)


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
    rng = np.random.default_rng(seed)
    scores = rng.uniform(0.2, 0.95, size=len(SIX_M_FACTORS))
    df = pd.DataFrame({"요인": SIX_M_FACTORS, "연관도": scores})
    return df.sort_values("연관도", ascending=False).reset_index(drop=True)


def _infer_all_samples():
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
            probs = get_or_compute(img_bytes, lambda p=path: predict_ensemble(Image.open(p)))
            if probs is None:
                return None
            rows.append({"image_id": path.stem, "path": str(path), "probs": probs})
        return rows

    return _run()


def score_real_samples(thresholds):
    from utils.routing import classify

    inferred = _infer_all_samples()
    if inferred is None:
        return None

    rows = []
    for item in inferred:
        probs = item["probs"]
        status, label = classify(probs["무결함"], probs["균열(D1)"], probs["용입불량(D4)"], thresholds)
        if status not in ATTENTION_STATUSES:
            continue
        dom_class, dom_prob = _dominant({
            "prob_균열(D1)": probs["균열(D1)"],
            "prob_용입불량(D4)": probs["용입불량(D4)"],
            "prob_기공(D2)": probs["기공(D2)"],
        })
        rows.append({
            **item,
            "status": status,
            "ai_label": label,
            "dominant_class": dom_class,
            "calibrated_prob": dom_prob,
            "severity_score": CLASS_WEIGHT[dom_class] * dom_prob,
        })
    rows.sort(key=lambda r: r["severity_score"], reverse=True)
    return rows


# 초기 촬영조건 기준 평균 밝기 (참고값). 실제 운영 로그가 쌓이기 전까지는
# "오늘 대비 이 기준값"으로만 비교한다 — 진짜 추세 그래프가 아니라 참고용 단일
# 비교치임을 화면에도 명시할 것.
BASELINE_BRIGHTNESS = 142


def sample_brightness_stats():
    """samples/ 폴더 실제 사진들의 밝기 통계(평균/표본수/최소/최대)를 계산한다.
    사진이 없으면 None을 반환한다."""
    from PIL import Image

    from utils.samples import load_samples

    samples = load_samples()
    if not samples:
        return None
    values = []
    for path in samples:
        try:
            img = Image.open(path).convert("L")
            pixels = list(img.getdata())
            values.append(sum(pixels) / len(pixels))
        except Exception:
            continue
    if not values:
        return None
    return {
        "mean": sum(values) / len(values),
        "n": len(values),
        "min": min(values),
        "max": max(values),
    }


def avg_sample_brightness():
    """samples/ 폴더 실제 사진들의 평균 밝기(그레이스케일 픽셀 평균)를 계산한다.
    모델 추론과 무관한 가벼운 계산이라 별도 캐시 없이 매번 계산해도 부담 없다.
    사진이 없으면 None을 반환한다."""
    stats = sample_brightness_stats()
    return stats["mean"] if stats else None
