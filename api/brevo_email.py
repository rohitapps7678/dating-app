import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

BREVO_SMTP_HOST     = "smtp-relay.brevo.com"
BREVO_SMTP_PORT     = 587
BREVO_SMTP_LOGIN    = os.getenv("BREVO_SMTP_LOGIN",    "a7a63e001@smtp-brevo.com")
BREVO_SMTP_PASSWORD = os.getenv("BREVO_SMTP_PASSWORD", "")
BREVO_FROM_EMAIL    = os.getenv("BREVO_FROM_EMAIL",    "noreply@opentalk.app")
BREVO_FROM_NAME     = os.getenv("BREVO_FROM_NAME",     "OpenTalk")


def send_otp_email(to_email: str, otp: str) -> bool:
    """
    Brevo SMTP relay se OTP email bhejta hai.
    Returns True on success, False on failure.
    """
    subject = f"{otp} — Aapka OpenTalk Login OTP"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
        .container {{ max-width: 480px; margin: 40px auto; background: #fff;
                      border-radius: 16px; overflow: hidden;
                      box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
        .header {{ background: linear-gradient(135deg, #E84393, #FF6B9D);
                   padding: 32px 24px; text-align: center; }}
        .header h1 {{ color: white; margin: 0; font-size: 22px; font-weight: 700; }}
        .header p  {{ color: rgba(255,255,255,0.85); margin: 4px 0 0; font-size: 14px; }}
        .body {{ padding: 32px 24px; text-align: center; }}
        .otp-box {{ background: #FFF0F7; border: 2px dashed #E84393;
                    border-radius: 12px; padding: 20px; margin: 24px 0;
                    display: inline-block; width: 100%; box-sizing: border-box; }}
        .otp {{ font-size: 42px; font-weight: 900; letter-spacing: 16px;
                color: #E84393; font-family: monospace; }}
        .note {{ font-size: 13px; color: #888; margin-top: 8px; }}
        .expires {{ font-size: 13px; color: #E84393; font-weight: 600; margin-top: 4px; }}
        .footer {{ background: #f9f9f9; padding: 16px 24px; text-align: center;
                   font-size: 12px; color: #aaa; border-top: 1px solid #eee; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>❤️ OpenTalk</h1>
          <p>Your dating app</p>
        </div>
        <div class="body">
          <p style="font-size:16px;color:#333;margin:0;">Aapka login OTP hai:</p>
          <div class="otp-box">
            <div class="otp">{otp}</div>
            <div class="note">Ye OTP sirf aapke liye hai — kisi se share mat karo.</div>
            <div class="expires">⏰ 10 minute mein expire hoga</div>
          </div>
          <p style="font-size:13px;color:#999;margin-top:16px;">
            Agar aapne ye request nahi kiya toh is email ko ignore karo.
          </p>
        </div>
        <div class="footer">
          © 2025 OpenTalk &nbsp;•&nbsp; Made with ❤️ in India
        </div>
      </div>
    </body>
    </html>
    """

    text_body = f"Aapka OpenTalk OTP: {otp}\n\n10 minute mein expire hoga.\nKisi se share mat karo."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{BREVO_FROM_NAME} <{BREVO_FROM_EMAIL}>"
        msg["To"]      = to_email

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html",  "utf-8"))

        with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(BREVO_SMTP_LOGIN, BREVO_SMTP_PASSWORD)
            server.sendmail(BREVO_FROM_EMAIL, to_email, msg.as_string())

        logger.info(f"[Brevo] OTP email sent to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("[Brevo] SMTP auth failed — check BREVO_SMTP_LOGIN/PASSWORD in .env")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"[Brevo] SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"[Brevo] Unexpected error: {e}")
        return False