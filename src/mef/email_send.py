"""Send the rendered daily email via SMTP.

We deliberately do **not** call MDC's ``notify.py`` because that script
wraps the body in an alert template and forces its own subject. MEF wants
its rendered subject and body to land verbatim, so we send directly via
``smtplib`` using the SMTP credentials already configured for the AFT
environment.

SMTP credentials are read from ``~/repos/mdc/config/notifications.yaml``
(single source of truth across AFT tools). Recipients come from MEF's own
``config/mef.yaml`` under ``email.recipients``.

``send_daily_email`` never raises — failures are returned in ``SendResult``
so a broken SMTP path can never bring down a daily run.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import yaml

from mef.config import load_app_config


_DEFAULT_NOTIFICATIONS_PATH = Path.home() / "repos" / "mdc" / "config" / "notifications.yaml"


@dataclass
class SendResult:
    ok: bool
    recipients: list[str]
    sent_at: datetime | None
    error: str | None = None
    skipped_reason: str | None = None


def _load_smtp_config(path: Path | None = None) -> dict[str, Any] | None:
    p = path or _DEFAULT_NOTIFICATIONS_PATH
    if not p.exists():
        return None
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    email_cfg = cfg.get("email") or {}
    if not email_cfg.get("enabled", False):
        return None
    return email_cfg


def _build_message(
    *,
    subject: str,
    body: str,
    from_addr: str,
    to_addrs: list[str],
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def send_daily_email(*, subject: str, body: str) -> SendResult:
    """Send the rendered MEF daily email. Never raises."""
    app_cfg = load_app_config()
    recipients = (app_cfg.get("email") or {}).get("recipients") or []
    if not recipients:
        return SendResult(
            ok=False, recipients=[], sent_at=None,
            skipped_reason="no recipients in config/mef.yaml → email.recipients",
        )

    smtp_cfg = _load_smtp_config()
    if smtp_cfg is None:
        return SendResult(
            ok=False, recipients=recipients, sent_at=None,
            skipped_reason="SMTP config unavailable or email disabled "
                           f"({_DEFAULT_NOTIFICATIONS_PATH})",
        )

    host = smtp_cfg.get("smtp_host", "smtp.gmail.com")
    port = int(smtp_cfg.get("smtp_port", 587))
    username = smtp_cfg.get("username")
    password = smtp_cfg.get("password")
    from_addr = smtp_cfg.get("from", username)

    if not all([username, password, from_addr]):
        return SendResult(
            ok=False, recipients=recipients, sent_at=None,
            skipped_reason="SMTP credentials incomplete in notifications.yaml",
        )

    msg = _build_message(
        subject=subject, body=body, from_addr=from_addr, to_addrs=recipients,
    )

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(from_addr, recipients, msg.as_string())
    except Exception as exc:
        return SendResult(
            ok=False, recipients=recipients, sent_at=None,
            error=f"SMTP send failed: {exc}",
        )

    return SendResult(
        ok=True, recipients=recipients,
        sent_at=datetime.now(timezone.utc),
    )
