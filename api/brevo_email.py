import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Load environment variables once
BREVO_API_KEY: Optional[str] = os.getenv("BREVO_API_KEY")
BREVO_FROM_EMAIL: str = os.getenv("BREVO_FROM_EMAIL", "noreply@opentalk.app")
BREVO_FROM_NAME: str = os.getenv("BREVO_FROM_NAME", "OpenTalk")


def send_otp_email(to_email: str, otp: str) -> bool:
    """
    Brevo API se OTP email bhejta hai.
    Returns True on success, False on failure.
    Bahut saare edge cases aur logging handle kiye gaye hain.
    """

    # ── 1. Basic Validation ──
    if not BREVO_API_KEY:
        logger.error("❌ BREVO_API_KEY environment variable is missing or empty!")
        logger.error("Render Dashboard → Environment mein BREVO_API_KEY add karo aur Redeploy karo.")
        return False

    if not to_email or "@" not in to_email:
        logger.error(f"❌ Invalid email address: {to_email}")
        return False

    if not otp or len(otp) != 6:
        logger.error(f"❌ Invalid OTP: {otp}")
        return False

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
          © 2026 OpenTalk • Made with ❤️ in India
        </div>
      </div>
    </body>
    </html>
    """

    text_body = f"Aapka OpenTalk OTP: {otp}\n\n10 minute mein expire hoga.\nKisi se share mat karo."

    url = "https://api.brevo.com/v3/smtp/email"

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    payload = {
        "sender": {
            "name": BREVO_FROM_NAME,
            "email": BREVO_FROM_EMAIL
        },
        "to": [
            {"email": to_email}
        ],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body
    }

    try:
        logger.info(f"📧 Sending OTP email to {to_email} via Brevo...")

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=15
        )

        if response.status_code == 201:
            logger.info(f"✅ OTP email successfully sent to {to_email}")
            return True

        else:
            # Common Brevo errors
            error_msg = response.text[:500]
            logger.error(f"❌ Brevo API Error: Status={response.status_code} | Response={error_msg}")

            if response.status_code == 401:
                logger.error("   → API Key galat hai ya 'not verified'. Brevo dashboard check karo.")
            elif response.status_code == 400:
                logger.error("   → Bad Request – payload mein kuch galat hai (sender email etc.)")
            elif response.status_code == 429:
                logger.error("   → Rate limit hit. Thoda wait karo.")

            return False

    except requests.exceptions.Timeout:
        logger.error(f"❌ Timeout while sending email to {to_email}")
        return False
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ Network connection error to Brevo API")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected exception in send_otp_email: {str(e)}", exc_info=True)
        return False