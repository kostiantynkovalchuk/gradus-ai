"""
Email Service — Resend SDK
==========================
Thin wrapper around the Resend API for sending transactional emails.
from: "Alex Gradus | GradusMedia <alex@gradusmedia.org>"
reply_to: admin@gradusmedia.org

Usage:
    from services.email_service import send_email, base_template

    html = base_template(content_html="<p>Hello!</p>")
    send_email(to="user@example.com", subject="Hi", html=html)
"""

import logging
import os

import resend

logger = logging.getLogger(__name__)

ALEX_PHOTO = "https://gradusmedia.org/assets/alex_new_b.png"
FROM_ADDRESS = "Alex Gradus | GradusMedia <alex@gradusmedia.org>"
REPLY_TO = "admin@gradusmedia.org"


def _cta_button(text: str, href: str) -> str:
    return (
        f'<div style="text-align:center;margin:28px 0;">'
        f'<a href="{href}" style="display:inline-block;padding:14px 32px;'
        f'background-color:#c9a84c;color:#0f0f1a;text-decoration:none;'
        f'border-radius:6px;font-weight:bold;font-size:16px;">{text}</a></div>'
    )


def base_template(content_html: str) -> str:
    """
    Wraps content_html in the standard GradusMedia dark email shell.
    Includes Alex photo circle at top, gold accent, mobile-responsive layout.
    """
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GradusMedia</title>
</head>
<body style="margin:0;padding:0;background-color:#0f0f1a;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#0f0f1a;min-height:100vh;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;background:#1a1a2e;border-radius:12px;overflow:hidden;">

          <!-- Alex photo -->
          <tr>
            <td align="center" style="padding:40px 40px 0;">
              <img src="{ALEX_PHOTO}"
                   width="100" height="100"
                   alt="Alex Gradus"
                   style="width:100px;height:100px;border-radius:50%;
                          object-fit:cover;display:block;
                          border:3px solid #c9a84c;">
            </td>
          </tr>

          <!-- Content -->
          <tr>
            <td style="padding:28px 40px 40px;color:#e8e8e8;font-size:16px;
                       line-height:1.7;">
              {content_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px;border-top:1px solid #2a2a3e;
                       text-align:center;color:#666;font-size:12px;
                       line-height:1.8;">
              <p style="margin:0 0 6px;">
                GradusMedia &middot;
                <a href="https://gradusmedia.org" style="color:#c9a84c;text-decoration:none;">
                  gradusmedia.org
                </a>
              </p>
              <p style="margin:0;">
                <a href="https://gradusmedia.org/unsubscribe"
                   style="color:#444;font-size:11px;text-decoration:none;">
                  Відписатись
                </a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_email(to: str, subject: str, html: str) -> bool:
    """
    Send a transactional email via Resend.
    Returns True on success, False on any error (never raises).
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("[Email] RESEND_API_KEY not set — skipping email")
        return False

    resend.api_key = api_key
    try:
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [to],
            "subject": subject,
            "html": html,
            "reply_to": REPLY_TO,
        })
        logger.info(f"[Email] Sent '{subject}' → {to}")
        return True
    except Exception as e:
        logger.error(f"[Email] Failed to send '{subject}' → {to}: {e}")
        return False
