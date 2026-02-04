"""Email notification: summary of decisions (dry-run or apply)."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from autofpl.decisions import GameweekDecisions

logger = logging.getLogger(__name__)


def _element_id_to_name(elements: list[dict[str, Any]] | None) -> dict[int, str]:
    if not elements:
        return {}
    return {int(e["id"]): e.get("web_name", str(e["id"])) for e in elements if e.get("id") is not None}


def build_email_body(
    decisions: GameweekDecisions,
    gameweek: int,
    bank: int | None,
    elements: list[dict[str, Any]] | None,
    mode: str,
) -> str:
    """Build plain-text email body. mode is 'dry_run' or 'apply'."""
    id_to_name = _element_id_to_name(elements)

    def name(eid: int | None) -> str:
        if eid is None:
            return "—"
        return id_to_name.get(eid, str(eid))

    mode_label = "Dry-Run (No Changes Made)" if mode == "dry_run" else "Applied to FPL"
    lines = [
        f"AutoFPL Summary – Gameweek {gameweek}",
        f"Mode: {mode_label}",
        "",
        "--- Chips ---",
        f"Chip used: {decisions.chip.value}",
        "",
        "--- Transfers ---",
    ]
    if not decisions.transfers:
        lines.append("No transfers.")
    else:
        for t in decisions.transfers:
            lines.append(f"  Out: {name(t.element_out)} ({t.element_out})  →  In: {name(t.element_in)} ({t.element_in})")
    lines.extend(["", "--- Starting XI ---"])
    if decisions.lineup_order and len(decisions.lineup_order) >= 11:
        for i, eid in enumerate(decisions.lineup_order[:11], 1):
            lines.append(f"  {i}. {name(eid)}")
    else:
        lines.append("  (current order kept)")
    lines.extend(["", "--- Bench ---"])
    if decisions.lineup_order and len(decisions.lineup_order) == 15:
        for i, eid in enumerate(decisions.lineup_order[11:15], 1):
            lines.append(f"  {i}. {name(eid)}")
    else:
        lines.append("  (current order kept)")
    lines.extend([
        "",
        "--- Captain & Vice ---",
        f"Captain: {name(decisions.captain_id)}",
        f"Vice-captain: {name(decisions.vice_captain_id)}",
        "",
        "--- Rationale ---",
        decisions.reasoning or "(none)",
        "",
    ])
    if bank is not None:
        lines.append(f"--- Bank ---\nRemaining: £{bank / 10:.1f}m\n")
    return "\n".join(lines)


def send_notification_email(to_email: str, subject: str, body: str) -> None:
    """Send email via SMTP. Uses env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, optional NOTIFICATION_EMAIL_FROM."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_header = os.getenv("NOTIFICATION_EMAIL_FROM", user or "").strip() or user
    # If NOTIFICATION_EMAIL_FROM has no @, treat as display name: "Display Name" <user@gmail.com>
    if from_header and "@" not in from_header:
        from_header = f'"{from_header}" <{user}>'

    if not user or not password:
        logger.warning("SMTP_USER or SMTP_PASSWORD not set; skipping email notification.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_email], msg.as_string())
        logger.info("Notification email sent to %s", to_email)
    except Exception as e:
        err = str(e).lower()
        if "535" in err or "username and password" in err or "badcredentials" in err:
            logger.warning(
                "Failed to send notification email (SMTP login rejected): %s. "
                "For Gmail use an App Password: https://support.google.com/accounts/answer/185833",
                e,
            )
        else:
            logger.warning("Failed to send notification email: %s", e)
