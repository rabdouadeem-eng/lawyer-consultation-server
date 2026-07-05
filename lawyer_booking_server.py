import os
import re
import time
import logging
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from collections import defaultdict

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============ ENV VARS ============
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWNER_CHAT_ID  = os.environ.get("TELEGRAM_ID")

# ============ RATE LIMITING ============
last_request_time = defaultdict(float)
RATE_LIMIT_SECONDS = 60

def is_rate_limited(ip):
    now = time.time()
    if now - last_request_time[ip] < RATE_LIMIT_SECONDS:
        return True
    last_request_time[ip] = now
    return False

# ============ VALIDATION ============
PHONE_REGEX = re.compile(r"^[\d\s\+\-\(\)]{6,20}$")
NAME_REGEX  = re.compile(r"^[\w\s\u0600-\u06FF]{2,60}$")

def validate_consultation(data):
    """
    Server-side validation — the frontend JS 'required' attributes
    can be bypassed, so real validation must happen here.
    """
    errors = []

    name = (data.get("fullName") or "").strip()
    if not name or not NAME_REGEX.match(name):
        errors.append("الاسم غير صالح")

    phone = (data.get("phone") or "").strip()
    if not phone or not PHONE_REGEX.match(phone):
        errors.append("رقم الهاتف غير صالح")

    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        errors.append("البريد الإلكتروني غير صالح")

    case_type = (data.get("caseType") or "").strip()
    if not case_type:
        errors.append("نوع القضية مطلوب")

    date = (data.get("preferredDate") or "").strip()

    case_desc = (data.get("caseDesc") or "").strip()
    if len(case_desc) > 1500:
        errors.append("الوصف طويل جداً")

    return errors, {
        "name": name,
        "phone": phone,
        "email": email,
        "case_type": case_type,
        "date": date or "-",
        "case_desc": case_desc or "-"
    }

# ============ TELEGRAM NOTIFY ============
def send_telegram_notification(clean_data):
    text = (
        "⚖️ *طلب استشارة قانونية جديد*\n\n"
        f"👤 الاسم: {clean_data['name']}\n"
        f"📞 الهاتف: {clean_data['phone']}\n"
        f"✉️ البريد: {clean_data['email']}\n"
        f"📋 نوع القضية: {clean_data['case_type']}\n"
        f"📆 التاريخ المفضل: {clean_data['date']}\n"
        f"💬 وصف القضية: {clean_data['case_desc']}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": OWNER_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram notify failed: {e}")
        return False

# ============ ROUTES ============
@app.route("/")
def home():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "lawyer_index.html")

@app.route("/api/consultation", methods=["POST"])
def consultation():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if is_rate_limited(ip):
        return jsonify({"ok": False, "error": "الرجاء الانتظار قليلاً قبل إرسال طلب آخر"}), 429

    data = request.get_json(silent=True) or {}

    errors, clean_data = validate_consultation(data)
    if errors:
        return jsonify({"ok": False, "error": "؛ ".join(errors)}), 400

    sent = send_telegram_notification(clean_data)
    if not sent:
        return jsonify({"ok": False, "error": "تعذر إرسال الطلب، حاول مرة أخرى"}), 500

    logger.info(f"Consultation request received: {clean_data['name']} - {clean_data['phone']}")
    return jsonify({"ok": True, "message": "تم استلام طلبك بنجاح"}), 200

@app.route("/health")
def health():
    return {"status": "ok"}, 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
