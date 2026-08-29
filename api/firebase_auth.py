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
import threading
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth_module
from dotenv import load_dotenv

load_dotenv()

_initialized  = False
_init_lock    = threading.Lock()
_project_id   = None  # ✅ ab hardcode nahi — service account JSON se hi nikalte hain


def _init_firebase():
    global _initialized, _project_id
    if _initialized:
        return

    # ✅ CRITICAL FIX: pehle koi lock nahi tha. Gunicorn threaded/gevent
    # workers mein agar do requests EK SAATH pehla /api/auth/firebase/
    # call karte the (jaisa deploy ke turant baad ya do devices se
    # parallel login), dono ek saath `if _initialized: return` cross
    # kar jaate the aur dono firebase_admin.initialize_app() call karte
    # the — dusra call "The default Firebase app already exists" (ValueError)
    # se crash hota tha, jo neeche generic except mein pakda jaata aur
    # verify_firebase_token() None return karta — client ko "Invalid or
    # expired Firebase token" dikhta, JABKI token bilkul sahi tha. Ab
    # lock ke andar hi poora init hota hai — sirf ek thread kaam karega,
    # baaki wait karke seedha return ho jaayenge.
    with _init_lock:
        if _initialized:
            return

        try:
            # 🔥 Primary Method: JSON as Environment Variable (Recommended for Render)
            service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

            if service_account_json:
                # JSON string ko Python dict mein convert karo
                service_account_info = json.loads(service_account_json.strip())

                # ✅ CRITICAL FIX: pehle project ID hardcoded constant
                # (PROJECT_ID = "open-talk-e0be1") se aata tha. Agar
                # kabhi Firebase project badla (ya service account
                # kisi doosre project ka daal diya) aur ye constant
                # update karna bhool gaye, toh Admin SDK Google se
                # verify toh karega lekin token ka "aud" (audience)
                # claim is project ID se match nahi karega — HAR SINGLE
                # request "Invalid ID token" (audience mismatch) fail
                # hogi, chahe OTP bilkul sahi ho. Ab project ID seedha
                # usi service-account JSON se li jaati hai jo actually
                # load ho rahi hai — ye do jagah hardcode/sync karne ki
                # zaroorat khatam kar deta hai.
                project_id = service_account_info.get("project_id")

                cred = credentials.Certificate(service_account_info)
                firebase_admin.initialize_app(cred, {
                    'projectId': project_id
                })

                _project_id = project_id
                print(f"[Firebase] ✅ Initialized using FIREBASE_SERVICE_ACCOUNT_JSON "
                      f"(project_id={project_id})")
                _initialized = True
                return

            # Secondary Method: Local development ke liye file se (optional)
            cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            if cred_path:
                if not os.path.isabs(cred_path):
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    cred_path = os.path.join(base_dir, cred_path)

                if os.path.exists(cred_path):
                    with open(cred_path) as f:
                        project_id = json.load(f).get("project_id")
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred, {'projectId': project_id})
                    _project_id = project_id
                    print(f"[Firebase] ✅ Initialized from local file: {cred_path} "
                          f"(project_id={project_id})")
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
        except ValueError as e:
            # ✅ "The default Firebase app already exists" — dusra thread/
            # request pehle hi init kar chuka, ye fatal error nahi hai.
            if "already exists" in str(e):
                print("[Firebase] ℹ️ App already initialized by another thread — reusing it")
                _initialized = True
                return
            print(f"[Firebase] ❌ Initialization failed: {e}")
            raise
        except Exception as e:
            print(f"[Firebase] ❌ Initialization failed: {e}")
            raise


def verify_firebase_token(id_token: str) -> dict | None:
    """
    Firebase ID token verify karta hai.
    Returns decoded token ya None.
    """
    try:
        _init_firebase()
        # ✅ clock_skew_seconds: server/device ka clock 1-2 second idhar-udhar
        # ho toh bhi token "used too early"/"expired" na maana jaaye —
        # chhota sa allowance, real security risk nahi badhata.
        decoded = firebase_auth_module.verify_id_token(id_token, clock_skew_seconds=10)
        return decoded

    except firebase_admin.auth.ExpiredIdTokenError:
        print("[Firebase] ❌ Token verify failed: token has EXPIRED "
              "(client ne purana/cached idToken bheja — dobara sign-in karke fresh token lo)")
        return None
    except firebase_admin.auth.InvalidIdTokenError as e:
        # ✅ Ye exception "invalid signature", "wrong audience/project",
        # "wrong issuer" — sabko cover karta hai. Pehle sirf generic
        # "Invalid ID token" print hota tha — asli wajah (jo yahan hai)
        # kabhi logs mein nahi dikhti thi. Ab poora exception message
        # print hota hai — agar ye "aud"/"audience"/"project" ka zikar
        # kare, toh iska matlab FIREBASE_SERVICE_ACCOUNT_JSON aur
        # Flutter app ka Firebase project ALAG-ALAG hai.
        print(f"[Firebase] ❌ Token verify failed — INVALID token: {e} "
              f"(current backend project_id={_project_id!r}; agar error mein "
              f"'audience'/'project' ka zikar hai toh backend service-account "
              f"aur Flutter app ka Firebase project match nahi kar rahe)")
        return None
    except Exception as e:
        print(f"[Firebase] ❌ Token verify failed — unexpected error ({type(e).__name__}): {e}")
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