"""이메일 발송 유틸 — SPC 긴급 경보 및 주간 보고서 전송.

SMTP 접속 정보는 커밋하지 않는 .streamlit/secrets.toml 에 [smtp] 섹션으로 저장한다.
예시:

[smtp]
host = "smtp.gmail.com"
port = 465
user = "your_account@gmail.com"
password = "16자리 앱 비밀번호"
default_to = "quality_manager@example.com"
"""
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


def _get_config():
    try:
        return st.secrets["smtp"]
    except Exception:
        return None


def is_configured():
    return _get_config() is not None


def default_recipient():
    cfg = _get_config()
    return cfg.get("default_to", "") if cfg else ""


def send_email(subject, body, to_addrs, attachment_bytes=None, attachment_name=None):
    cfg = _get_config()
    if cfg is None:
        raise RuntimeError("SMTP 설정이 없습니다 — .streamlit/secrets.toml에 [smtp] 섹션을 추가해주세요.")

    to_list = [a.strip() for a in to_addrs.split(",") if a.strip()] if isinstance(to_addrs, str) else list(to_addrs)
    if not to_list:
        raise ValueError("받는 사람 주소가 비어 있습니다.")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = cfg["user"]
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_bytes is not None:
        part = MIMEApplication(attachment_bytes, Name=attachment_name or "attachment")
        part["Content-Disposition"] = f'attachment; filename="{attachment_name or "attachment"}"'
        msg.attach(part)

    with smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port", 465))) as server:
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["user"], to_list, msg.as_string())
