"""
STAGE1에서 학습한 EfficientNetB0 5-fold 모델을 불러와 실제 추론 + Grad-CAM을 수행하는 모듈.

Colab 학습/검증 스크립트(구글드라이브의
`colab_전이학습_MobileNetV2_EfficientNetB0.py`, `colab_STAGE2_GradCAM_validation기반.py`)에서
쓰던 build_model() / make_gradcam_heatmap() 코드를 그대로 옮겨왔다. 모델 구조나 전처리 방식이
학습 때와 1픽셀이라도 다르면 예측이 어긋나므로, 임의로 바꾸지 말 것.

가중치 파일 5개(`efficientnetb0_filmopt_fold0~4_last.weights.h5`)는 용량이 커서(각 ~16MB)
Claude가 대신 받아줄 수 없다 — 구글드라이브에서 직접 내려받아 이 프로젝트의 weights/ 폴더에
넣어야 한다. (자세한 안내는 채팅 답변 참고)

STAGE3 갱신 — 이 가중치들은 여전히 원래 학습된 "4클래스 개별(Difetto1/2/4/NoDifetto)"
백본 동결 모델이다 (미세조정된 새 가중치가 아직 없음). 다만 STAGE3 보고서에서 균열(D1)·
미용착(D4)을 하나의 판정 범주로 통합하기로 했으므로, 모델 자체는 그대로 4클래스 raw
확률을 뽑되 이 파일에서 D1+D4를 더해 최종적으로 3클래스(무결함/균열·용입불량/기공)로
합쳐서 반환한다. utils/routing.py의 CRACK_OR_LOP_T 기본값(0.1982)도 이 "기저모델 통합"
기준으로 맞춰져 있다 — 나중에 미세조정된 새 가중치가 들어오면 그 가중치는 원래부터
3클래스로 나올 가능성이 높으니, 그때 이 병합 로직을 다시 확인할 것.
"""
import os

import numpy as np
import streamlit as st
import tensorflow as tf
from PIL import Image
from tensorflow.keras.applications import EfficientNetB0, efficientnet

IMG_SIZE = 224  # 학습 스크립트의 IMG_SIZE와 동일 (원본 타일은 227x227이지만 학습 시 224로 리사이즈됨)
N_FOLDS = 5

WEIGHTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "weights")
WEIGHTS_TEMPLATE = "efficientnetb0_filmopt_fold{fold}_last.weights.h5"

# 학습 시 sorted(os.listdir(train_dir))로 정해진 실제 클래스 순서.
# 모델 출력(softmax) 벡터의 인덱스 순서가 이 순서와 정확히 일치해야 함 — 절대 바꾸지 말 것.
CLASS_NAMES = ["Difetto1", "Difetto2", "Difetto4", "NoDifetto"]

# raw 4클래스 -> 최종 표시용 3클래스 매핑. Difetto1·Difetto4가 같은 값으로 매핑되므로
# predict_ensemble()에서 두 확률을 명시적으로 더해야 한다 (dict 컴프리헨션으로 덮어쓰면
# 하나가 사라지니 주의).
LABEL_KR = {
    "Difetto1": "균열·용입불량(D1+D4)",
    "Difetto4": "균열·용입불량(D1+D4)",
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
        # Grad-CAM은 EfficientNetB0의 마지막 feature map(7x7)을 기준으로 만든다
        # (학습 스크립트와 동일). features는 _build_model()에서 그래프 생성 시점에
        # 바로 잡아둔 텐서라 별도 get_layer().output 조회 없이 안전하게 연결된다.
        grad_model = tf.keras.Model(inputs=m.inputs, outputs=[features, m.output])
        models.append((m, grad_model))
    return models, missing


def _preprocess(pil_image: Image.Image):
    """원본(0~255 uint8 RGB, 224x224)과 모델 입력용 배치(전처리+배치차원)를 함께 반환."""
    img = pil_image.convert("RGB").resize((IMG_SIZE, IMG_SIZE), Image.BILINEAR)
    arr = np.array(img).astype(np.float32)
    batch = efficientnet.preprocess_input(np.expand_dims(arr, axis=0))
    return arr.astype(np.uint8), batch


def predict_ensemble(pil_image: Image.Image):
    """5-fold 모델의 softmax 확률을 평균 앙상블 (STAGE2 Track A와 동일한 방식 — 엄격한
    OOF 대신 5개 fold를 전부 평균해서 쓰는 간소화된 방법).
    STAGE3 통합: raw 4클래스(Difetto1/2/4/NoDifetto) 확률을 낸 다음, Difetto1+Difetto4를
    더해 최종적으로 3클래스(무결함/균열·용입불량(D1+D4)/기공(D2))로 합쳐서 반환한다.
    반환: (probs 딕셔너리 또는 None, 없는 가중치 파일 목록)"""
    models, missing = load_fold_models()
    if not models:
        return None, missing

    _, batch = _preprocess(pil_image)
    all_preds = [m.predict(batch, verbose=0)[0] for m, _ in models]
    avg_preds = np.mean(all_preds, axis=0)
    raw = dict(zip(CLASS_NAMES, avg_preds))

    probs = {
        "무결함": float(raw["NoDifetto"]),
        "균열·용입불량(D1+D4)": float(raw["Difetto1"] + raw["Difetto4"]),
        "기공(D2)": float(raw["Difetto2"]),
    }
    return probs, missing


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
    argmax는 raw 4클래스 기준으로 구하되(Grad-CAM은 특정 클래스 로짓을 기준으로 계산해야
    하므로), 표시용 라벨은 LABEL_KR로 통합 클래스명으로 바뀐다(Difetto1·Difetto4 둘 다
    "균열·용입불량(D1+D4)"로 표시됨).
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
