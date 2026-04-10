"""
dating_backend/api/firebase_auth.py

Firebase Admin SDK se phone aur Google ID token verify karta hai.

Setup:
1. Firebase Console → Project Settings → Service Accounts
   → Generate New Private Key → download karo (firebase_key.json)
2. .env file mein add karo:
   FIREBASE_CREDENTIALS_PATH=full/path/to/firebase_key.json
"""

import os
import json
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth_module
from dotenv import load_dotenv

load_dotenv()

_initialized = False
PROJECT_ID = "opentalk-53d08"


def _init_firebase():
    global _initialized
    if _initialized:
        return

    try:
        # 🔥 Primary Method: JSON as Environment Variable (Recommended for Render)
        service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

        if service_account_json:
            # JSON string ko Python dict mein convert karo
            service_account_info = json.loads(service_account_json.strip())
            
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred, {
                'projectId': PROJECT_ID
            })
            
            print("[Firebase] ✅ Successfully initialized using FIREBASE_SERVICE_ACCOUNT_JSON")
            _initialized = True
            return

        # Secondary Method: Local development ke liye file se (optional)
        cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
        if cred_path:
            if not os.path.isabs(cred_path):
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                cred_path = os.path.join(base_dir, cred_path)

            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {'projectId': PROJECT_ID})
                print(f"[Firebase] ✅ Initialized from local file: {cred_path}")
                _initialized = True
                return
            else:
                print(f"[Firebase] ⚠️  File not found: {cred_path}")

        # Agar kuch bhi nahi mila
        print("[Firebase] ❌ No Firebase credentials found!")
        print("   → Set FIREBASE_SERVICE_ACCOUNT_JSON in Render Environment Variables")
        raise Exception("Firebase service account not configured. Check environment variables.")

    except json.JSONDecodeError as e:
        print(f"[Firebase] ❌ Invalid JSON format in FIREBASE_SERVICE_ACCOUNT_JSON: {e}")
        raise
    except Exception as e:
        print(f"[Firebase] ❌ Initialization failed: {e}")
        raise

    _initialized = True


def verify_firebase_token(id_token: str) -> dict | None:
    """
    Firebase ID token verify karta hai.
    Returns decoded token ya None.
    """
    try:
        _init_firebase()
        decoded = firebase_auth_module.verify_id_token(id_token)
        return decoded

    except firebase_admin.auth.ExpiredIdTokenError:
        print("[Firebase] Token has expired")
        return None
    except firebase_admin.auth.InvalidIdTokenError:
        print("[Firebase] Invalid ID token")
        return None
    except Exception as e:
        print(f"[Firebase] Token verify failed: {e}")
        return None


# Optional: Extra helper functions (future use ke liye)
def get_firebase_uid(decoded_token: dict) -> str:
    """Safely return Firebase UID"""
    return decoded_token.get("uid") if decoded_token else None


def get_phone_number(decoded_token: dict) -> str | None:
    """Phone auth ke liye phone number"""
    return decoded_token.get("phone_number") if decoded_token else None


def get_email(decoded_token: dict) -> str | None:
    """Google auth ke liye email"""
    return decoded_token.get("email") if decoded_token else None