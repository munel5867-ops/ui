"""
STAGE4/5 실제 모델·데이터가 붙기 전까지 UI를 시연하기 위한 더미 데이터 생성 모듈.
나중에 실제 모델 추론 결과 / DB 조회로 교체할 함수들의 경계를 여기로 맞춰뒀다.

[팀 결정 반영] 균열(D1)·용입불량(D4)을 통합하지 않고 개별 클래스로 유지한다
(margin 기반 세부유형 판정 방식으로 전환 — utils/routing.py 참고). 더미 데이터도
4클래스(무결함/균열(D1)/기공(D2)/용입불량(D4)) 개별 확률로 되돌린다.
"""
import numpy as np
import pandas as pd
import streamlit as st

LABELS = ["무결함", "균열(D1)", "기공(D2)", "용입불량(D4)"]


@st.cache_data
def load_validation_predictions(n: int = 2000, seed: int = 42) -> pd.DataFrame:
    """검증셋에 대한 (실제 라벨, 클래스별 예측확률) 더미 테이블.

    실제 연동 시: 학습된 모델로 검증셋을 1회 추론해 이 스키마(true_label, prob_*)로
    저장해두고 재사용한다. 슬라이더를 움직일 때마다 모델을 다시 돌리면 느리므로,
    임계값 비교만 실시간으로 하는 구조를 유지할 것.
    """
    rng = np.random.default_rng(seed)
    true_label = rng.choice(LABELS, size=n, p=[0.82, 0.05, 0.05, 0.08])

    probs = np.zeros((n, len(LABELS)))
    for i, label in enumerate(true_label):
        idx = LABELS.index(label)
        base = rng.dirichlet(alpha=np.ones(len(LABELS)) * 0.6)
        base[idx] += rng.uniform(0.3, 0.6)
        probs[i] = base / base.sum()

    df = pd.DataFrame(probs, columns=[f"prob_{l}" for l in LABELS])
    df.insert(0, "true_label", true_label)
    df.insert(0, "image_id", [f"RT_{i:04d}" for i in range(n)])
    return df


@st.cache_data
def demo_single_prediction() -> dict:
    """1탭 데모용 단일 이미지의 고정 예측값."""
    return {"무결함": 0.08, "균열(D1)": 0.22, "기공(D2)": 0.09, "용입불량(D4)": 0.61}


@st.cache_data
def spc_daily_defect_rate(days: int = 20, seed: int = 7) -> pd.DataFrame:
    """STAGE5 p-chart용 더미 일별 불량률."""
    rng = np.random.default_rng(seed)
    base_dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days)
    rate = rng.normal(loc=0.085, scale=0.012, size=days)
    rate[days // 2] = 0.16  # 이상점 하나 강제 삽입 (데모용)
    rate = np.clip(rate, 0.01, None)
    return pd.DataFrame({"date": base_dates, "defect_rate": rate})


@st.cache_data
def inspector_queue() -> pd.DataFrame:
    """검사자 확인 대기열 더미 데이터."""
    return pd.DataFrame(
        [
            {"severity": "high", "image_id": "RT_0342", "suspect": "균열의심", "prob": 0.71},
            {"severity": "high", "image_id": "RT_0198", "suspect": "균열의심", "prob": 0.64},
            {"severity": "mid", "image_id": "RT_0511", "suspect": "경계애매", "prob": 0.48},
            {"severity": "low", "image_id": "RT_0077", "suspect": "경계애매", "prob": 0.31},
        ]
    )


def make_mock_gradcam_overlay(size: int = 227) -> np.ndarray:
    """실제 모델 없이 Grad-CAM 느낌만 내는 더미 히트맵 오버레이 이미지(RGB)."""
    rng = np.random.default_rng(0)
    base = rng.normal(loc=40, scale=8, size=(size, size)).clip(0, 255).astype(np.uint8)
    img = np.stack([base, base, base], axis=-1).astype(np.float32)

    yy, xx = np.mgrid[0:size, 0:size]
    cy, cx = int(size * 0.6), int(size * 0.4)
    dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
    heat = np.exp(-dist2 / (2 * (size * 0.09) ** 2))

    overlay = img.copy()
    overlay[..., 0] += heat * 255 * 0.9
    overlay[..., 1] += heat * 255 * 0.1
    overlay = overlay.clip(0, 255).astype(np.uint8)
    return overlay