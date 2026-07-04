"""
email_utils.py
--------------
"Share via email" — sends a generated report file (PDF or Excel) as an
attachment using standard SMTP. Configure via .env (SMTP_HOST, SMTP_PORT,
SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM). Works with Gmail (use an "App
Password", not your normal password), Outlook/Office365, or any SMTP relay.

The Supervisor Dashboard (utils/db.py + pages/1_Supervisor_Dashboard.py) is
the recommended primary way to browse/share reports by date; this is the
"push a copy straight to someone's inbox" option — used automatically for the
daily PDF report, and available on demand for a re-send.
"""

import os
import smtplib
import mimetypes
from email.message import EmailMessage


def _send(to_email: str, subject: str, body: str, attachment_bytes: bytes, attachment_filename: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username)

    if not (host and username and password):
        raise RuntimeError(
            "Email isn't configured yet. Set SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD "
            "(and optionally SMTP_FROM) in your .env file."
        )
    if not to_email:
        raise RuntimeError("No recipient email address was provided.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)

    guessed_type, _ = mimetypes.guess_type(attachment_filename)
    if guessed_type:
        maintype, subtype = guessed_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    msg.add_attachment(attachment_bytes, maintype=maintype, subtype=subtype, filename=attachment_filename)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)


def send_report_email(to_email: str, subject: str, body: str, excel_bytes: bytes, excel_filename: str):
    """Sends the per-report Excel export as an attachment."""
    _send(to_email, subject, body, excel_bytes, excel_filename)


def send_pdf_report_email(to_email: str, subject: str, body: str, pdf_bytes: bytes, pdf_filename: str):
    """Sends the full visit-report PDF (narrative + photos) as an attachment.
    This is called automatically after every submission when AUTO_EMAIL_PDF=true
    and DEFAULT_SUPERVISOR_EMAIL is set — see app.py Step 3."""
    _send(to_email, subject, body, pdf_bytes, pdf_filename)
