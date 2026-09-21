"""
samples/ 폴더의 대표 이미지 로더 — 우선순위 큐 리뷰 패널에서 쓴다.
"""
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples"

_EXTS = {".png", ".jpg", ".jpeg"}


def load_samples():
    if not SAMPLES_DIR.exists():
        return []
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in _EXTS)


def image_for_id(image_id, samples=None):
    """더미 큐 항목(image_id)에 결정적으로 샘플 이미지를 매칭.

    실제 검사 이미지 저장소가 붙기 전까지의 임시 방편 — image_id별 진짜 사진은
    아직 없어서, 같은 id는 항상 같은 이미지가 나오도록 해시로 고정 배정만 해준다."""
    samples = samples if samples is not None else load_samples()
    if not samples:
        return None
    digest = hashlib.md5(image_id.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(samples)
    return samples[idx]
