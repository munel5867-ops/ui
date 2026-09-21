"""'메일로 전송' 팝오버 UI — 다운로드 버튼 옆에 붙여서 재사용한다."""
import streamlit as st

from utils.mailer import default_recipient, is_configured, send_email


def render_send_email_popover(docx_bytes, docx_name, subject, body, key_prefix, label="✉️ 메일로 전송"):
    if not is_configured():
        st.caption("메일 전송을 쓰려면 `.streamlit/secrets.toml`에 SMTP 설정이 필요합니다.")
        return

    with st.popover(label):
        to = st.text_input("받는 사람 (쉼표로 여러 명 가능)", value=default_recipient(), key=f"{key_prefix}_to")
        if st.button("전송", key=f"{key_prefix}_send", type="primary"):
            try:
                send_email(subject, body, to, attachment_bytes=docx_bytes, attachment_name=docx_name)
                st.success(f"{to} 로 전송했습니다.")
            except Exception as e:
                st.error(f"전송 실패: {e}")
