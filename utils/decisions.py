"""
검사자 최종 확인 결과를 decision_log.csv에 기록하는 공용 모듈.
tabs/tab1_inference.py의 _log_decision()과 완전히 같은 스키마(헤더)를 쓴다 —
우선순위 큐(tab3)에서 승인/반려해도 tab1과 같은 파일에 같이 쌓인다.
"""
import csv
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_LOG = PROJECT_ROOT / "decision_log.csv"

FIELDS = ["시각", "이미지출처", "AI판정", "무결함", "균열·용입불량(D1+D4)", "기공(D2)", "검사자결정"]


def log_decision(source, probs, status, decision):
    is_new = not DECISION_LOG.exists()
    with open(DECISION_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(FIELDS)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source, status,
            f'{probs["무결함"]:.3f}',
            f'{probs["균열·용입불량(D1+D4)"]:.3f}',
            f'{probs["기공(D2)"]:.3f}',
            decision,
        ])
