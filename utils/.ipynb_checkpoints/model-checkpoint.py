"""
STAGE3에서 백본 마지막 20층을 미세조정+증강 학습한 EfficientNetB0 5-fold 모델을 불러와
실제 추론 + Grad-CAM을 수행하는 모듈.

2026-09-19 갱신 — 배포 가중치를 백본 동결(filmopt) 모델에서 미세조정+증강 모델로
교체했다. 파일명에 "finetune"이 붙은 것으로 구분한다 — filmopt(백본 동결)와 혼동하지 말 것.

[팀 결정 반영 — 균열(D1)/용입불량(D4) 개별 유지 + margin 라우팅]
routing.py가 D1+D4 통합(CrackOrLoP) 방식에서, D1/D4를 개별 확률로 유지하고
margin_threshold=90(확신도 격차 기준)일 때만 세부유형을 확정하는 방식으로 바뀌었다.
이에 맞춰 predict_ensemble()도 D1+D4를 합산하지 않고 개별 확률 그대로 반환한다.

[확률 보정 — Isotonic + Saerens]
STAGE3 margin 검증(margin>=90 → 정확도 99.5%)은 Isotonic 보정 + 사전확률(Saerens)
재조정을 거친 확률 기준으로 나온 결과다. models/calibration_bundle_finetune.pkl
파일이 있으면 이 보정을 적용하고, 없으면 원본(미보정) 확률을 쓰며 화면에 경고를
띄운다 — 미보정 상태에서는 margin_threshold=90이 검증된 정확도를 보장하지 못한다.

Colab 학습/검증 스크립트에서 쓰던 build_model() / make_gradcam_heatmap() 코드를
그대로 옮겨왔다. 모델 구조나 전처리 방식이 학습 때와 1픽셀이라도 다르면 예측이
어긋나므로, 임의로 바꾸지 말 것.

가중치 파일 5개(`efficientnetb0_finetune_fold0~4_last.weights.h5`, 각 ~27.7MB)와
보정 파일(`calibration_bundle_finetune.pkl`)은 용량 문제로 Claude가 대신 받아줄 수
없다 — 구글드라이브에서 직접 내려받아 이 프로젝트의 models/ 폴더에 넣어야 한다.
"""
import os
import pickle

import numpy as np
import streamlit as st
import tensorflow as tf
from PIL import Image
from tensorflow.keras.applications import EfficientNetB0, efficientnet

IMG_SIZE = 224  # 학습 스크립트의 IMG_SIZE와 동일 (원본 타일은 227x227이지만 학습 시 224로 리사이즈됨)
N_FOLDS = 5

WEIGHTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
WEIGHTS_TEMPLATE = "efficientnetb0_finetune_fold{fold}_last.weights.h5"
CALIBRATION_PATH = os.path.join(WEIGHTS_DIR, "calibration_bundle_finetune.pkl")

# 학습 시 sorted(os.listdir(train_dir))로 정해진 실제 클래스 순서.
# 모델 출력(softmax) 벡터의 인덱스 순서가 이 순서와 정확히 일치해야 함 — 절대 바꾸지 말 것.
CLASS_NAMES = ["Difetto1", "Difetto2", "Difetto4", "NoDifetto"]

# raw 클래스명(영문) -> 화면 표시용 한글 라벨. 이제는 통합하지 않고 개별 그대로 매핑한다.
LABEL_KR = {
    "Difetto1": "균열(D1)",
    "Difetto4": "용입불량(D4)",
    "Difetto2": "기공(D2)",
    "NoDifetto": "무결함",
}


def _build_model():
    """학습 스크립트의 build_model()과 동일한 구조 (구조/가중치 로직은 그대로).
    weights=None으로 두는 이유: 어차피 곧바로 fold별 학습 완료 가중치를 통째로
    load_weights()로 덮어씌우기 때문에, 여기서 imagenet 가중치를 인터넷에서
    새로 받을 필요가 없다 (실행 속도 + 오프라인 시연 안정성).

    Grad-CAM용 feature map 텐서를 모델 생성 시점에 바로 함께 반환한다. Keras 3부터는
    `model.get_layer(name).output`으로 중첩 서브모델의 중간 출력을 나중에 다시 조회하면
    그래프 연결이 깨져 ValueError가 나기 때문에(Keras 2 시절엔 되던 방식), 처음 그래프를
    만들 때 잡아둔 텐서를 그대로 재사용하는 쪽으로 바꿨다. 예측값/가중치는 동일하다."""
    base = EfficientNetB0(input_shape=(IMG_SIZE, IMG_SIZE, 3), include_top=False, weights=None)
    base.trainable = False
    inputs = tf.keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
    features = base(inputs, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(features)
    x = tf.keras.layers.Dropout(0.3)(x)
    outputs = tf.keras.layers.Dense(len(CLASS_NAMES), activation="softmax")(x)
    model = tf.keras.Model(inputs, outputs)
    return model, features


@st.cache_resource(show_spinner="5-fold 모델 불러오는 중...")
def load_fold_models():
    """5개 fold 모델 + Grad-CAM용 서브모델을 딱 1번만 만들어서 캐시해둔다.
    반환: (models, missing_paths) — weights 파일이 없으면 그 fold는 건너뛰고
    missing_paths에 어떤 파일이 없었는지 기록한다."""
    models = []
    missing = []
    for fold in range(N_FOLDS):
        path = os.path.join(WEIGHTS_DIR, WEIGHTS_TEMPLATE.format(fold=fold))
        if not os.path.exists(path):
            missing.append(path)
            continue
        m, features = _build_model()
        m.load_weights(path)
        grad_model = tf.keras.Model(inputs=m.inputs, outputs=[features, m.output])
        models.append((m, grad_model))
    return models, missing


@st.cache_resource(show_spinner="보정기 불러오는 중...")
def load_calibration():
    """models/calibration_bundle_finetune.pkl을 불러온다. 없으면 None 반환 —
    이 경우 predict_ensemble()은 보정 없이 원본 확률을 그대로 쓴다."""
    if not os.path.exists(CALIBRATION_PATH):
        return None
    with open(CALIBRATION_PATH, "rb") as f:
        return pickle.load(f)


def _apply_calibration(raw_avg_preds: np.ndarray, bundle: dict) -> np.ndarray:
    """raw_avg_preds: CLASS_NAMES 순서의 4클래스 확률 (앙상블 평균 직후, 보정 전).
    Isotonic 보정 -> Saerens 사전확률 재조정까지 적용한 확률을 같은 순서로 반환."""
    class_names = bundle["class_names"]
    isotonic_models = bundle["isotonic_models"]
    train_prior = bundle["train_prior"]
    target_prior = bundle["target_prior"]

    calibrated = np.zeros(len(class_names))
    for ci, cname in enumerate(class_names):
        raw_idx = CLASS_NAMES.index(cname)
        calibrated[ci] = isotonic_models[cname].transform([raw_avg_preds[raw_idx]])[0]

    ratio = target_prior / train_prior
    adjusted = calibrated * ratio
    adjusted = adjusted / (adjusted.sum() + 1e-12)

    out = np.zeros(len(CLASS_NAMES))
    for ci, cname in enumerate(class_names):
        raw_idx = CLASS_NAMES.index(cname)
        out[raw_idx] = adjusted[ci]
    return out


def _preprocess(pil_image: Image.Image):
    """원본(0~255 uint8 RGB, 224x224)과 모델 입력용 배치(전처리+배치차원)를 함께 반환."""
    img = pil_image.convert("RGB").resize((IMG_SIZE, IMG_SIZE), Image.BILINEAR)
    arr = np.array(img).astype(np.float32)
    batch = efficientnet.preprocess_input(np.expand_dims(arr, axis=0))
    return arr.astype(np.uint8), batch


def predict_ensemble(pil_image: Image.Image):
    """5-fold 모델의 softmax 확률을 평균 앙상블한 뒤, 보정기가 있으면 Isotonic+Saerens
    보정을 적용한다. D1/D4를 합치지 않고 개별 확률 그대로 반환한다.
    반환: probs 딕셔너리 (무결함/균열(D1)/기공(D2)/용입불량(D4)) 또는 가중치가 없으면 None."""
    models, missing = load_fold_models()
    if not models:
        return None

    _, batch = _preprocess(pil_image)
    all_preds = [m.predict(batch, verbose=0)[0] for m, _ in models]
    avg_preds = np.mean(all_preds, axis=0)

    bundle = load_calibration()
    if bundle is not None:
        avg_preds = _apply_calibration(avg_preds, bundle)
    else:
        st.warning("⚠ 보정기(calibration_bundle_finetune.pkl)가 없어 원본(미보정) 확률을 사용 중입니다. "
                    "margin_threshold=90의 검증된 정확도가 보장되지 않습니다.")

    raw = dict(zip(CLASS_NAMES, avg_preds))
    probs = {
        "무결함": float(raw["NoDifetto"]),
        "균열(D1)": float(raw["Difetto1"]),
        "기공(D2)": float(raw["Difetto2"]),
        "용입불량(D4)": float(raw["Difetto4"]),
    }
    return probs


def _gradcam_heatmap(grad_model: tf.keras.Model, img_batch: np.ndarray, pred_index: int) -> np.ndarray:
    with tf.GradientTape() as tape:
        conv_outputs, predictions = grad_model(img_batch)
        loss = predictions[:, pred_index]
    grads = tape.gradient(loss, conv_outputs)
    pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2))
    conv_outputs = conv_outputs[0]
    heatmap = conv_outputs @ pooled_grads[..., tf.newaxis]
    heatmap = tf.squeeze(heatmap)
    heatmap = tf.maximum(heatmap, 0) / (tf.math.reduce_max(heatmap) + 1e-8)
    return heatmap.numpy()


def gradcam_overlay(pil_image: Image.Image):
    """5개 fold의 Grad-CAM 히트맵을 평균(앙상블)해서 원본 위에 합성한 오버레이 이미지를 만든다.
    표시용 라벨도 이제 개별 클래스명(LABEL_KR)으로 그대로 보여준다 — 더 이상
    Difetto1·Difetto4를 하나로 합쳐 표시하지 않는다.
    반환: (오버레이 RGB 배열 또는 None, 예측 클래스명(한글) 또는 없는 가중치 파일 목록)"""
    models, missing = load_fold_models()
    if not models:
        return None, missing

    raw, batch = _preprocess(pil_image)

    avg_preds = np.mean([m.predict(batch, verbose=0)[0] for m, _ in models], axis=0)
    pred_index = int(np.argmax(avg_preds))

    heatmaps = [_gradcam_heatmap(gm, batch, pred_index) for _, gm in models]
    heatmap = np.mean(heatmaps, axis=0)

    heatmap_resized = (
        tf.image.resize(heatmap[..., np.newaxis], (IMG_SIZE, IMG_SIZE)).numpy().squeeze()
    )

    import matplotlib

    heatmap_colored = matplotlib.colormaps["jet"](heatmap_resized)[:, :, :3] * 255
    overlay = (raw * 0.5 + heatmap_colored * 0.5).astype(np.uint8)

    pred_label = LABEL_KR[CLASS_NAMES[pred_index]]
    return overlay, pred_label