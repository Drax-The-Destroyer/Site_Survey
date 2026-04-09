import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Mapping, Optional


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _streamlit_email_secrets() -> Dict[str, Any]:
    try:
        import streamlit as st

        secrets_obj = st.secrets.get("email", {})
        if hasattr(secrets_obj, "to_dict"):
            secrets_obj = secrets_obj.to_dict()
        if isinstance(secrets_obj, Mapping):
            return dict(secrets_obj)
    except Exception:
        pass
    return {}


def _resolve_smtp_config(smtp_config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    provided = dict(smtp_config or {})
    secrets = _streamlit_email_secrets()

    host = _first_value(
        provided.get("host"),
        os.getenv("SMTP_HOST"),
        secrets.get("SMTP_HOST"),
    )
    port = _first_value(
        provided.get("port"),
        os.getenv("SMTP_PORT"),
        secrets.get("SMTP_PORT"),
        587,
    )
    username = _first_value(
        provided.get("username"),
        provided.get("user"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_USERNAME"),
        secrets.get("SMTP_USER"),
        secrets.get("SMTP_USERNAME"),
    )
    password = _first_value(
        provided.get("password"),
        provided.get("pass"),
        os.getenv("SMTP_PASS"),
        os.getenv("SMTP_PASSWORD"),
        secrets.get("SMTP_PASS"),
        secrets.get("SMTP_PASSWORD"),
    )
    from_email = _first_value(
        provided.get("from_email"),
        provided.get("from"),
        os.getenv("FROM_EMAIL"),
        secrets.get("FROM_EMAIL"),
        username,
    )

    use_ssl = _as_bool(
        _first_value(
            provided.get("use_ssl"),
            os.getenv("SMTP_USE_SSL"),
            secrets.get("SMTP_USE_SSL"),
        ),
        False,
    )
    use_tls = _as_bool(
        _first_value(
            provided.get("use_tls"),
            os.getenv("SMTP_USE_TLS"),
            secrets.get("SMTP_USE_TLS"),
        ),
        not use_ssl,
    )

    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "from_email": from_email,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


def send_survey_email(
    pdf_bytes: bytes,
    filename: str,
    to_addresses: List[str],
    cc_addresses: List[str],
    subject: str,
    smtp_config: Optional[Mapping[str, Any]] = None,
) -> None:
    resolved = _resolve_smtp_config(smtp_config)
    smtp_host = resolved["host"]
    smtp_port = resolved["port"]
    smtp_user = resolved["username"]
    smtp_pass = resolved["password"]
    from_email = resolved["from_email"]
    use_tls = resolved["use_tls"]
    use_ssl = resolved["use_ssl"]

    if not smtp_host or not smtp_user or not smtp_pass:
        raise RuntimeError(
            "Missing SMTP configuration. Configure SMTP in Admin > Settings, "
            "set SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS, or add them to .streamlit/secrets.toml."
        )

    if not to_addresses:
        raise RuntimeError("No destination email addresses configured.")

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = ", ".join(to_addresses)
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)
    msg["Subject"] = subject
    msg.attach(MIMEText("Please find the attached site survey PDF.", "plain"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    recipients = list(to_addresses) + list(cc_addresses or [])

    smtp_client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_client(smtp_host, smtp_port, timeout=20) as server:
        if use_tls and not use_ssl:
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, recipients, msg.as_string())
