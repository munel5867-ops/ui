import pandas as pd
import streamlit as st

from utils.style import BRAND_NAVY

LIMITS = pd.DataFrame({
    "한계": ["D4 유형 신뢰도", "특이도 목표 미달", "라우팅 측정 조건", "필름 다양성 부족", "테스트셋 미개봉", "외부 데이터 미검증"],
    "내용": [
        "PR-AUC 0.6272(±0.3031)로 4개 클래스 중 최저, 재현율 76.5%. 비용비 3:1 기준 미검출 207건(전체 미검출 330건의 62.7%)이며 "
        "Grad-CAM IoU도 0.156으로 가장 낮음. 근본 원인(D4가 7개 필름에만 존재)은 미해소",
        "목표 0.99 대비 실측 0.912~0.979. 비용기반 임계값으로 보정 중이나 목표 자체는 미달성",
        "검증은 원래 결함비율(76.2%)에서 측정. 실제 라인 불량률(0.5~10%)로 재조정한 확률에 적용 시 동일 안전성 유지 여부 재검증 필요",
        "독립 필름 29개(학습 20개). D4는 전체 7개 필름에만 있어 fold 간 편차가 크고(fold4 정확도 74.12%), 새로운 촬영조건에서의 일반화 미검증",
        "6,588장 봉인 유지 중 — 최종 성능은 아직 단 1회도 측정되지 않음",
        "다른 장비·다른 현장 데이터(GDXray 등)에서의 일반화 성능 미측정",
    ],
    "위험도": ["높음", "중간", "높음", "중간", "예정", "중간"],
})

ACTIONS = pd.DataFrame({
    "No": [1, 2, 3, 4, 5, 6],
    "조치 내용": [
        "라우팅 검증을 실제 라인 불량률(사전확률 재조정 확률) 기준으로 재실행해, 낮은 유병률에서도 놓침 최소화가 유지되는지 확인",
        "비용비 최종값과 라우팅 기준값을 품질·인증 담당자가 직접 입력·조정하는 임계값 결정 권한 이양 구조 문서화",
        "D1↔D4 혼동의 근본 원인(필름 쏠림)은 미해소 상태임을 최종 보고서 한계 항목에 명시. 추가 필름 데이터 확보 우선 검토",
        "세그멘테이션 정답 마스크 120장을 재학습·추가 검증용 자산으로 보존",
        "판정 로그 DB(타임스탬프·확신도·구간·평균밝기) 적재를 시작해 관리도·드리프트 지표를 실측 데이터로 전환",
        "결함 유형별 원인 공정 매핑표를 현장 용접 엔지니어와 함께 확정",
    ],
    "담당": ["개발팀", "품질팀", "공동", "개발팀", "개발팀", "품질팀"],
})

# 대시보드에서 실제로 뜨는 알림/신호별 대응 가이드 — "오늘의 현황" 탭의 SPC 경보,
# 위험도순 확인(빨강/주황), margin 보류 판정, 모델 가중치 미탑재 경고를 그대로 반영한다.
ALERT_GUIDE = pd.DataFrame({
    "상황(알림)": [
        "⚠ SPC 관리한계 이탈 경보 (화면 최상단)",
        "🔴 위험도순 확인 — 긴급(빨강, 깜빡임)",
        "🟠 위험도순 확인 — 주의(주황)",
        "⚠ 사람 확인 필요 · 균열/용입불량 경계 모호 (AI확신도 보류)",
        "⚠ 모델 가중치 미탑재 경고",
        "🟡 입력 밝기 드리프트 — 주의",
    ],
    "언제 뜨나": [
        "금일 불량률이 관리상한(UCL, CL+3σ)을 초과했을 때",
        "위험도순 확인 항목의 severity_score(결함 가중치 × AI 확률)가 1.6 이상일 때 "
        "— 예: 균열(D1)·용입불량(D4) 확률 0.8 이상",
        "severity_score가 1.0 이상 1.6 미만일 때",
        "균열·용입불량으로 선별됐지만 AI확신도가 98 미만이라 AI가 유형을 확정하지 못했을 때 "
        "(추정 유형 표시)",
        "models/ 폴더에 5-fold 가중치 파일이 없어 판정 데모·오늘의 현황이 더미 값으로 "
        "대체됐을 때",
        "samples/ 폴더 실측 이미지의 평균 밝기가 기준(142) 대비 ±10%를 벗어났을 때",
    ],
    "확인할 것": [
        "'6M 원인 스크리닝 요약' 펼쳐서 연관도 상위 요인 확인, 최근 불량률 추이(SPC 관리도) 확인",
        "'검토하기'로 원본 사진·Grad-CAM 히트맵·AI 확률 확인",
        "긴급 항목 처리 후 순서대로 검토",
        "AI 추정 유형과 D1 확률·D4 확률 중 어느 쪽이 실제로 더 근접한지를 Grad-CAM 근거와 함께 직접 판단",
        "'🚨 담당자에게 긴급 보고' 팝오버로 바로 긴급 메일 전송 가능(SMTP 설정 시)",
        "'오늘의 현황' 좌측 상단 게이지에서 기준(142) 대비 편차(%)·표본 수·범위 확인",
    ],
    "조치": [
        "공정 파라미터(용접전류·이음부간격 등) 즉시 점검. 필요시 라인 정지 후 담당자에게 긴급 메일 전송",
        "'⛔ 최종 불량 확정' 또는 '✅ 최종 양품 승인'으로 즉시 확정. 반려 시 NCR이 자동 발행되므로 "
        "즉시조치·원인분석 항목을 이어서 작성",
        "당일 업무 시간 내 순차적으로 확정 처리",
        "확정 후 승인/반려 처리. 균열(D1)이면 재용접, 용입불량(D4)이면 백가우징 등 조치 방법이 달라지므로 "
        "세부유형을 반드시 기록",
        "구글드라이브에서 가중치 파일(각 ~27.7MB) 5개와 보정 파일을 내려받아 models/ 폴더에 추가",
        "촬영 장비·조명(노출) 점검. 필요시 재촬영하거나, 지속되면 개발팀에 임계값 재검증 요청",
    ],
    "담당": ["현장 반장 · 품질팀", "검사자", "검사자", "검사자", "개발팀", "현장 촬영 담당 · 개발팀"],
})


# 위험도순 확인의 "📄 메일로 전송"과 담당자 알림의 "🚨 담당자에게 긴급 메일 전송"은
# 서로 다른 목적의 버튼이라 헷갈리기 쉬워 표로 정리해둔다.
MAIL_GUIDE = pd.DataFrame({
    "버튼": ["📄 메일로 전송 (위험도순 확인)", "🚨 담당자에게 긴급 메일 전송 (담당자 알림)"],
    "내용": [
        "오늘의 현황 보고서(.docx) 전체를 첨부 — 처리현황·핵심지표·검사자 처리 결과·"
        "위험도순 전체 목록·SPC 상태까지 포함",
        "첨부파일 없이, 긴급(빨강) 항목만 이미지ID·유형·확률·severity_score로 텍스트 나열",
    ],
    "대상": ["위험도순 확인 목록 전체(건수 무관)", "severity_score 1.6 이상인 긴급 항목만"],
    "나오는 조건": ["항상 표시됨", "긴급 항목이 1건 이상 있을 때만 표시됨"],
    "용도": ["하루 전체 현황을 정리해서 보고할 때", "지금 당장 위험한 몇 건만 담당자에게 빠르게 알릴 때"],
})


def _risk_style(v):
    m = {
        "높음": "background-color:#FBEAEA;color:#C0392B",
        "중간": "background-color:#FBF3E2;color:#B8860B",
        "예정": "background-color:#EAF6FC;color:#184f95",
    }
    return m.get(v, "")


# st.dataframe은 셀 글자를 별도 렌더링 엔진(그리드 컴포넌트)으로 그려서, 브라우저 확대(Zoom)
# 시 칸 너비에 안 맞는 글자가 줄바꿈되지 않고 그대로 잘려서 보이는 문제가 있다(이 값으로는
# 고칠 수 없음 — 조원 인계 문서에도 이미 기록돼 있던 한계). 순수 HTML 표는 셀이 기본적으로
# 줄바꿈되므로, 이 탭의 표 네 개를 전부 HTML로 바꿔서 어떤 확대 배율에서도 잘리지 않게 한다.
def _html_table(df, col_widths=None, risk_col=None):
    cols = list(df.columns)
    widths = col_widths or [None] * len(cols)
    head_style = (f'padding:10px 12px;background:{BRAND_NAVY};color:#fff;font-size:16px;'
                  'font-weight:700;text-align:left;white-space:normal')
    cell_style = 'padding:10px 12px;font-size:16px;line-height:1.5;vertical-align:top;white-space:normal'

    head_cells = "".join(
        f'<th style="{head_style}{f";width:{w}" if w else ""}">{c}</th>' for c, w in zip(cols, widths)
    )
    body_rows = []
    for i, row in enumerate(df.itertuples(index=False)):
        bg = "#f5f6f8" if i % 2 == 1 else "#ffffff"
        cells = []
        for c, v in zip(cols, row):
            if c == risk_col:
                pill_style = _risk_style(v)
                cells.append(
                    f'<td style="{cell_style}"><span style="display:inline-block;padding:3px 12px;'
                    f'border-radius:12px;font-weight:700;{pill_style}">{v}</span></td>'
                )
            else:
                cells.append(f'<td style="{cell_style}">{v}</td>')
        body_rows.append(f'<tr style="background:{bg}">' + "".join(cells) + '</tr>')

    return (
        '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
        'border:1px solid #e1e4e8">'
        f'<tr>{head_cells}</tr>' + "".join(body_rows) + '</table></div>'
    )


def render():
    st.info(
        "📋 이 화면은 감사·인증 심사 대응용 소명 자료이자, 대시보드에서 알림이 떴을 때 참고하는 "
        "대응 매뉴얼입니다. 아래 다섯 구역으로 나뉩니다 — ① **현재 시스템의 한계**: 이 시스템이 "
        "보장하지 못하는 범위, ② **운영 전환 체크리스트**: 정식 운영 전환 전 해야 할 일, "
        "③ **알림별 대응 가이드**: 대시보드에서 특정 알림·신호가 떴을 때 무엇을 확인하고 "
        "어떻게 조치해야 하는지, ④ **메일 전송 버튼 안내**: 위험도순 확인·담당자 알림 두 메일 "
        "버튼의 차이, ⑤ **입력 밝기 드리프트란?**: 그 지표가 무엇을 보여주는지 설명. 평소 업무에는 "
        "③~⑤번만 참고해도 됩니다."
    )
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("현재 시스템의 한계")
        st.markdown(_html_table(LIMITS, col_widths=["18%", "62%", "20%"], risk_col="위험도"),
                    unsafe_allow_html=True)
    with col2:
        st.subheader("운영 전환 체크리스트")
        st.markdown(_html_table(ACTIONS, col_widths=["8%", "72%", "20%"]), unsafe_allow_html=True)

    st.divider()
    st.subheader("🚨 알림별 대응 가이드")
    st.caption("대시보드에서 이런 알림·신호를 보면, 이렇게 확인하고 조치하세요.")
    st.markdown(_html_table(ALERT_GUIDE), unsafe_allow_html=True)

    st.divider()
    st.subheader("📧 메일 전송 버튼 안내")
    st.caption("위험도순 확인과 담당자 알림, 두 곳에 메일 버튼이 있어 헷갈릴 수 있어 정리했습니다.")
    st.markdown(_html_table(MAIL_GUIDE), unsafe_allow_html=True)

    st.divider()
    st.subheader("☀ 입력 밝기 드리프트란?")
    st.markdown(
        "'오늘의 현황' 탭 좌측 칸에 있는 지표입니다. `samples/` 폴더 실측 이미지들의 "
        "평균 밝기(그레이스케일 픽셀 평균)를, 학습 데이터 촬영 조건 기준값인 **142**와 "
        "비교해서 보여줍니다.\n\n"
        "- **왜 보는가**: RT 촬영 조건(노출·필름 상태 등)이 학습 당시와 달라지면, 모델이 "
        "한 번도 본 적 없는 밝기 분포의 이미지를 판정하게 되어 정확도가 떨어질 수 있습니다. "
        "이 지표는 그런 촬영 조건 변화를 실측 기준으로 조기에 감지하기 위한 것입니다.\n"
        "- **정상**: 기준(142) 대비 ±10% 이내\n"
        "- **주의**: ±10%를 벗어난 경우 — 화면에 주황색 '주의 — 촬영 조건 점검 권장' 배지가 뜹니다\n"
        "- **참고**: 지금은 `samples/` 폴더의 대표 이미지 20장을 기준으로 계산하는 실측 참고용 "
        "지표이며, 실제 운영 로그가 쌓이기 전까지는 추세 그래프가 아니라 '오늘 대비 기준값' "
        "단일 비교치로만 사용합니다."
    )
