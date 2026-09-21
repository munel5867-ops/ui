"""모델 추론 결과를 디스크에 캐시 — 서버 재시작 후에도 재계산하지 않게 한다.
이미지 내용(바이트) 해시를 키로 써서, tab1_inference.py(판정 데모)와
tab3_spc.py(오늘의 현황) 양쪽에서 같은 사진이면 캐시를 공유해서 쓴다."""
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / ".cache" / "inference_cache.json"


def _load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _key_for(image_bytes):
    return hashlib.sha1(image_bytes).hexdigest()


def get_or_compute(image_bytes, compute_fn):
    """image_bytes에 대한 (probs, breakdown)을 캐시에서 찾거나, 없으면 compute_fn()으로
    계산해서 저장한다. compute_fn은 predict_ensemble과 같은 시그니처
    (probs, missing, breakdown)을 반환해야 한다. 가중치가 없어 probs가 None이면
    캐시하지 않는다(다음에 가중치가 생기면 다시 계산되도록)."""
    key = _key_for(image_bytes)
    cache = _load_cache()
    if key in cache:
        entry = cache[key]
        return entry["probs"], entry["breakdown"]

    probs, missing, breakdown = compute_fn()
    if probs is None:
        return None, None

    cache[key] = {"probs": probs, "breakdown": breakdown}
    _save_cache(cache)
    return probs, breakdown
