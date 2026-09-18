import streamlit as st
import numpy as np
from PIL import Image

st.set_page_config(page_title="용접부 RT 자동화 — 실시간 판정", page_icon="🔍", layout="centered")

# ---------------------------------------------------------
# 스타일 (기존 HTML 대시보드와 같은 남색·하늘색 톤)
# ---------------------------------------------------------
st.markdown("""
<style>
:root{
  --navy:#032639; --navy-m:#3B4A8C; --sky:#5BC2E7; --sky-l:#EAF6FC;
  --ok:#1E7A46; --ok-bg:#E8F5EC; --warn:#B8860B; --warn-bg:#FBF3E2; --bad:#C0392B; --bad-bg:#FBEAEA;
}
.stApp { background:#F7F9FC; }
.header-band{
  background:var(--navy); color:#fff; padding:22px 26px; border-radius:12px; margin-bottom:20px;
}
.header-band h1{ font-size:20px; margin:0 0 4px; }
.header-band p{ font-size:13px; color:#B9C6E8; margin:0; }
.verdict-card{
  border-radius:12px; padding:22px; margin:16px 0; border-left:8px solid var(--navy-m);
}
.verdict-card.ok{ background:var(--ok-bg); border-left-color:var(--ok); }
.verdict-card.warn{ background:var(--warn-bg); border-left-color:var(--warn); }
.verdict-card.bad{ background:var(--bad-bg); border-left-color:var(--bad); }
.verdict-title{ font-size:24px; font-weight:700; margin:0 0 6px; }
.verdict-sub{ font-size:14px; color:#5A6178; margin:0; }
.tag{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:500; margin-top:8px; }
.tag.ok{ background:var(--ok); color:#fff; }
.tag.warn{ background:var(--warn); color:#fff; }
.tag.bad{ background:var(--navy-m); color:#fff; }
.caution-box{
  background:#FBEAEA; border:1px solid var(--bad); border-radius:8px; padding:12px 14px;
  font-size:13px; margin-top:10px; color:#7A2318;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header-band">
  <h1>AI 용접부 RT 자동화 — 실시간 판정 데모</h1>
  <p>EfficientNetB0 5-fold 앙상블 · 이 화면은 발표용 라이브 데모이며, 실제 확률 보정(Isotonic)·비용기반 임계값은 반영되지 않은 원본 모델 출력 기준입니다.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 모델 로드 (캐시 — 최초 1회만 로드)
# ---------------------------------------------------------
IMG_SIZE = 224
CLASS_NAMES = ["Difetto1", "Difetto2", "Difetto4", "NoDifetto"]
CLASS_LABELS_KR = {"Difetto1": "균열 (CR)", "Difetto2": "기공 (PO)", "Difetto4": "용입불량 (LP)", "NoDifetto": "무결함 (ND)"}
MODEL_DIR = "models"  # C:\work\pbl\models 안에 efficientnetb0_fold0~4_last.weights.h5 필요

@st.cache_resource
def load_models():
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras.applications import EfficientNetB0

    def build_model():
        base = EfficientNetB0(input_shape=(IMG_SIZE, IMG_SIZE, 3), include_top=False, weights="imagenet")
        base.trainable = False
        inputs = keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
        x = base(inputs, training=False)
        x = keras.layers.GlobalAveragePooling2D()(x)
        x = keras.layers.Dropout(0.3)(x)
        outputs = keras.layers.Dense(len(CLASS_NAMES), activation="softmax")(x)
        return keras.Model(inputs, outputs)

    models = []
    missing = []
    for i in range(5):
        path = f"{MODEL_DIR}/efficientnetb0_fold{i}_last.weights.h5"
        try:
            m = build_model()
            m.load_weights(path)
            models.append(m)
        except Exception:
            missing.append(path)
    return models, missing


def preprocess(img: Image.Image):
    from tensorflow.keras.applications import efficientnet
    img = img.convert("RGB").resize((IMG_SIZE, IMG_SIZE))
    arr = np.array(img).astype(np.float32)
    arr = efficientnet.preprocess_input(arr)
    return arr[np.newaxis, ...]


def route_decision(probs):
    """STAGE3에서 만든 3구간 라우팅 로직 (임시 기준값 — 현업 확정 전 초안)"""
    p = dict(zip(CLASS_NAMES, probs))
    p_nd, p_d1, p_d2, p_d4 = p["NoDifetto"], p["Difetto1"], p["Difetto2"], p["Difetto4"]

    ND_CONFIDENT, CONFIDENT_T, ATTENTION_T = 0.90, 0.50, 0.15

    if p_nd >= ND_CONFIDENT:
        return "자동통과", "NoDifetto", None

    d1_signal, d4_signal = p_d1 >= ATTENTION_T, p_d4 >= ATTENTION_T
    if d1_signal and d4_signal:
        gap = abs(p_d1 - p_d4)
        if gap < 0.3 or max(p_d1, p_d4) < CONFIDENT_T:
            return "사람확인", "균열계열 의심(D1/D4 구분 필요)", None

    best = max(CLASS_NAMES[:3], key=lambda c: p[c])
    caution = None
    if best == "Difetto1" and p_d4 < ATTENTION_T:
        caution = ("이 판정은 D1(균열)로 확신되었지만, 자체 검증 결과 실제 D4(용입불량)를 D1로 "
                   "확신에 차서 오판하는 사례가 놓친 D4의 절반 이상을 차지했습니다. 애매하면 재검토를 권장합니다.")
    if p[best] >= CONFIDENT_T:
        return "자동배출", best, caution
    return "사람확인", "일반 애매구간", caution


# ---------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------
models, missing = load_models()

if missing:
    st.error(
        "모델 파일을 찾을 수 없습니다. 아래 경로에 체크포인트를 넣어주세요:\n\n"
        + "\n".join(f"- {p}" for p in missing)
    )
    st.stop()

st.success(f"모델 {len(models)}개 로드 완료 (fold0~fold4 앙상블)")

uploaded = st.file_uploader("용접부 X-ray 이미지 업로드", type=["png", "jpg", "jpeg"])

if uploaded is not None:
    img = Image.open(uploaded)
    col1, col2 = st.columns([1, 1.3])
    with col1:
        st.image(img, caption="업로드된 이미지", use_container_width=True)

    with st.spinner("판정 중..."):
        x = preprocess(img)
        preds = [m.predict(x, verbose=0)[0] for m in models]
        probs = np.mean(preds, axis=0)

    zone, label, caution = route_decision(probs)
    zone_cls = {"자동통과": "ok", "자동배출": "bad", "사람확인": "warn"}[zone]
    display_label = CLASS_LABELS_KR.get(label, label)

    with col2:
        st.markdown(f"""
        <div class="verdict-card {zone_cls}">
          <p class="verdict-sub">판정 결과</p>
          <p class="verdict-title">{display_label}</p>
          <span class="tag {zone_cls}">{zone}</span>
        </div>
        """, unsafe_allow_html=True)

        if caution:
            st.markdown(f'<div class="caution-box">⚠ {caution}</div>', unsafe_allow_html=True)

        st.subheader("클래스별 확률")
        for c in CLASS_NAMES:
            p = float(probs[CLASS_NAMES.index(c)])
            st.write(f"{CLASS_LABELS_KR[c]}")
            st.progress(min(max(p, 0.0), 1.0), text=f"{p*100:.1f}%")

    st.caption(
        "※ 이 데모는 원본(보정 전) softmax 확률과 임시 라우팅 기준값을 사용합니다. "
        "실제 배포 시 STAGE3 Isotonic 보정과 현업이 확정한 임계값이 적용되어야 합니다."
    )
else:
    st.info("위에서 이미지를 업로드하면 판정 결과가 표시됩니다.")
