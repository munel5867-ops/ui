"""'메일로 전송' 팝오버 UI — 다운로드 버튼 옆에 붙여서 재사용한다."""
import streamlit as st

from utils.mailer import default_recipient, is_configured, send_email


def render_send_email_popover(docx_bytes, docx_name, subject, body, key_prefix, label="✉️ 메일로 전송"):
    if not is_configured():
        st.caption("메일 전송을 쓰려면 `.streamlit/secrets.toml`에 SMTP 설정이 필요합니다.")
        return

    # st.popover는 확장 아이콘을 구글 Material Symbols 웹폰트로 그리는데,
    # 이 폰트를 브라우저가 못 받아오면 아이콘 대신 "expand_more" 텍스트가
    # 그대로 노출되며 버튼 라벨과 겹쳐 보인다. 외부 폰트에 의존하지 않도록
    # 버튼 토글 + 조건부 표시 방식으로 대체한다.
    open_key = f"{key_prefix}_mail_open"
    if open_key not in st.session_state:
        st.session_state[open_key] = False

    if st.button(label, key=f"{key_prefix}_toggle", width="stretch"):
        st.session_state[open_key] = not st.session_state[open_key]

    if st.session_state[open_key]:
        with st.container(border=True):
            to = st.text_input("받는 사람 (쉼표로 여러 명 가능)", value=default_recipient(), key=f"{key_prefix}_to")
            if st.button("전송", key=f"{key_prefix}_send", type="primary"):
                try:
                    send_email(subject, body, to, attachment_bytes=docx_bytes, attachment_name=docx_name)
                    st.success(f"{to} 로 전송했습니다.")
                    st.session_state[open_key] = False
                except Exception as e:
                    st.error(f"전송 실패: {e}")
