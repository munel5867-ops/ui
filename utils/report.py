"""주간 자동보고서 생성 — 조원이 만든 NCR 양식(utils/ncr_report.py)을 그대로 재사용한다.
케이스 전용 섹션(즉시조치/원인분석/시정조치계획/효과성검증/승인)은 주간 집계에는
해당 사항이 없어 빈칸으로 나가지만, 문서 구조·표 개수·섹션 순서는 NCR과 완전히 동일하다.
"""
from datetime import date

from utils.ncr_report import build_ncr_docx


def weekly_report_bytes(thresholds):
    """탭4·탭3(오늘의 현황) 양쪽에서 같은 로직으로 보고서를 만들기 위한 공용 함수."""
    from datetime import timedelta

    from utils.dummy_data import load_validation_predictions
    from utils.routing import compute_kpis

    df = load_validation_predictions()
    kpis = compute_kpis(df, thresholds)

    period_end = date.today()
    period_start = period_end - timedelta(days=6)
    total_count = 3214  # TODO: 실제 이번 주 검사 물량 집계로 교체
    human_review_count = round(total_count * kpis["human_review_rate"])
    margin_hold_count = round(total_count * kpis["margin_hold_rate"])
    d1_miss_count = round(total_count * kpis["d1_miss_rate"])
    d4_miss_count = round(total_count * kpis["d4_miss_rate"])

    # NCR 양식은 케이스 1건 기준 칸이라, 주간 집계 값을 최대한 그 칸 의미에 맞춰 채운다.
    # - 제품/로트/필름 번호 칸 → 이번 주 총 검사 물량
    # - 부적합 유형 칸 → 균열(D1)/용입불량(D4) 중 미검출 건수가 더 많은 쪽 (참고용 표시)
    # - AI 판정 확률 칸 → 이번 주 자동화율
    # - 검사원 최종 판정 칸 → "주간 집계 보고"
    dominant = "균열(D1)" if d1_miss_count >= d4_miss_count else "용입불량(D4)"

    docx_bytes = build_ncr_docx(
        image_id=f"이번 주 전체 검사 물량 {total_count:,}건 "
                  f"(사람확인 {human_review_count:,}건 · Margin보류 {margin_hold_count:,}건)",
        dominant_class=dominant,
        ai_prob=kpis["automation_rate"],
        decision="주간 집계 보고",
        report_no=f"WEEKLY-{period_end.strftime('%Y%m%d')}",
        found_date=period_end,
    )
    return docx_bytes, f"weekly_report_{period_end.isoformat()}.docx"
