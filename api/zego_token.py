# zego_token.py
#
# ✅ ZegoCloud "Token04" generator — is file ke upar wala hissa (line ~20
# se generate_token04() tak) ZEGOCLOUD ka hi official, publicly published
# server-side sample hai:
#   https://github.com/ZEGOCLOUD/zego_server_assistant/tree/master/token/python/token04
#
# ISE HAATH MAT LAGAO (encoding/byte-layout) — ye bilkul waisa hi match
# karna chahiye jaisa ZegoCloud ke servers expect karte hain, warna token
# invalid ho jaayega. Neeche sirf `get_zego_token()` wrapper project-specific
# hai — wahi tum apne views.py se use karoge.
#
# Install (agar already nahi hai):
#   pip install pycryptodome
#
# settings.py mein ye env-driven settings add karo:
#   ZEGO_APP_ID              = int(os.environ.get("ZEGO_APP_ID", "0"))
#   ZEGO_SERVER_SECRET       = os.environ.get("ZEGO_SERVER_SECRET", "")   # 32-char string, ZegoCloud console se
#   ZEGO_TOKEN_EFFECTIVE_SECONDS = 60 * 60 * 24   # 24 hours — optional, default neeche hai

import json
import random
import time
import struct
import binascii
from Crypto.Cipher import AES
from django.conf import settings

ERROR_CODE_SUCCESS = 0
ERROR_CODE_APP_ID_INVALID = 1
ERROR_CODE_USER_ID_INVALID = 3
ERROR_CODE_SECRET_INVALID = 5
ERROR_CODE_EFFECTIVE_TIME_IN_SECONDS_INVALID = 6


class TokenInfo:
    def __init__(self, token, error_code, error_message):
        self.token = token
        self.error_code = error_code
        self.error_message = error_message


def __make_nonce():
    return random.getrandbits(31)


def __make_random_iv():
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    iv = ""
    for _ in range(16):
        index = int(random.random() * 16)
        iv += chars[index]
    return iv


def __aes_pkcs5_padding(cipher_text, block_size):
    padding_size = len(cipher_text) if (len(cipher_text) == len(
        cipher_text.encode('utf-8'))) else len(cipher_text.encode('utf-8'))
    padding = block_size - padding_size % block_size
    if padding < 0:
        return None
    padding_text = chr(padding) * padding
    return cipher_text + padding_text


def __aes_encrypy(plain_text, key, iv):
    cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv.encode('utf-8'))
    content_padding = __aes_pkcs5_padding(plain_text, 16)
    encrypt_bytes = cipher.encrypt(content_padding.encode('utf-8'))
    return encrypt_bytes


def generate_token04(app_id, user_id, secret, effective_time_in_seconds, payload):
    """
    ZegoCloud "Token04" — official algorithm, byte-for-byte.

    Args:
        app_id: ZegoCloud console se mila numeric App ID (int)
        user_id: Token kis user ke liye ban raha hai
        secret: ZegoCloud console ka "ServerSecret" — EXACTLY 32 characters
        effective_time_in_seconds: token kitni der valid rahega (seconds)
        payload: room-specific privilege JSON string, ya "" (basic token —
                 isi app ke andar kisi bhi room mein login/publish allow)

    Returns:
        TokenInfo(token, error_code, error_message)
    """
    if type(app_id) != int or app_id == 0:
        return TokenInfo("", ERROR_CODE_APP_ID_INVALID, "appID invalid")
    if type(user_id) != str or user_id == "":
        return TokenInfo("", ERROR_CODE_USER_ID_INVALID, "userID invalid")
    if type(secret) != str or len(secret) != 32:
        return TokenInfo("", ERROR_CODE_SECRET_INVALID, "secret must be a 32 byte string")
    if type(effective_time_in_seconds) != int or effective_time_in_seconds <= 0:
        return TokenInfo("", ERROR_CODE_EFFECTIVE_TIME_IN_SECONDS_INVALID, "effective_time_in_seconds invalid")

    create_time = int(time.time())
    expire_time = create_time + effective_time_in_seconds
    nonce = __make_nonce()

    _token = {"app_id": app_id, "user_id": user_id, "nonce": nonce,
              "ctime": create_time, "expire": expire_time, "payload": payload}
    plain_text = json.dumps(_token, separators=(',', ':'), ensure_ascii=False)

    iv = __make_random_iv()
    encrypt_buf = __aes_encrypy(plain_text, secret, iv)

    result_size = len(encrypt_buf) + 28
    result = bytearray(result_size)

    big_endian_expire_time = struct.pack("!q", expire_time)
    result[0: 0 + len(big_endian_expire_time)] = big_endian_expire_time[:]

    big_endian_iv_size = struct.pack("!h", len(iv))
    result[8: 8 + len(big_endian_iv_size)] = big_endian_iv_size[:]

    buffer = bytearray(iv.encode('utf-8'))
    result[10: 10 + len(buffer)] = buffer[:]

    big_endian_buf_size = struct.pack("!h", len(encrypt_buf))
    result[26: 26 + len(big_endian_buf_size)] = big_endian_buf_size[:]

    result[28: len(result)] = encrypt_buf[:]

    token = "04" + binascii.b2a_base64(result, newline=False).decode()

    return TokenInfo(token, ERROR_CODE_SUCCESS, "success")


# ─────────────────────────────────────────────────────────────
# PROJECT-SPECIFIC WRAPPER — isi ko views.py se import karo
# ─────────────────────────────────────────────────────────────

def get_zego_token(user_id: str, effective_seconds: int | None = None, payload: str = "") -> str:
    """
    Flutter app ke liye ek fresh, short-lived Zego RTC token banata hai.

    `payload=""` → "basic" token: is App ID ke andar kisi bhi room mein
    login/publish allow — voice/video call feature ke liye yahi sahi hai
    (room ID hum khud dynamically banate hain, per-conversation).
    """
    app_id = int(getattr(settings, "ZEGO_APP_ID", 0))
    secret = getattr(settings, "ZEGO_SERVER_SECRET", "")
    eff = effective_seconds or getattr(settings, "ZEGO_TOKEN_EFFECTIVE_SECONDS", 60 * 60 * 24)

    if not app_id:
        raise RuntimeError("ZEGO_APP_ID configured nahi hai (settings.py / env var check karo)")
    if not secret or len(secret) != 32:
        raise RuntimeError("ZEGO_SERVER_SECRET missing ya galat length ka hai (32 chars hona chahiye)")

    info = generate_token04(app_id, str(user_id), secret, eff, payload)
    if info.error_code != ERROR_CODE_SUCCESS:
        raise RuntimeError(f"Zego token generation failed: {info.error_message}")
    return info.token