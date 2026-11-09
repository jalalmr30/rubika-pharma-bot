import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- راه‌اندازی دیتابیس SQLite برای ذخیره وضعیت کاربران در پیام‌رسان ---
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            user_id TEXT PRIMARY KEY,
            step TEXT,
            pharmacy_name TEXT,
            org_name TEXT,
            patient_age INTEGER,
            expiry_date TEXT,
            doctor_specialty TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_session(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT step, pharmacy_name, org_name, patient_age, expiry_date, doctor_specialty FROM sessions WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "step": row[0],
            "pharmacy_name": row[1],
            "org_name": row[2],
            "patient_age": row[3],
            "expiry_date": row[4],
            "doctor_specialty": row[5]
        }
    return {"step": "START", "pharmacy_name": None, "org_name": None, "patient_age": None, "expiry_date": None, "doctor_specialty": None}

def update_session(user_id, **kwargs):
    session = get_session(user_id)
    session.update(kwargs)
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO sessions (user_id, step, pharmacy_name, org_name, patient_age, expiry_date, doctor_specialty)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        session["step"],
        session["pharmacy_name"],
        session["org_name"],
        session["patient_age"],
        session["expiry_date"],
        session["doctor_specialty"]
    ))
    conn.commit()
    conn.close()

# --- اعتبارسنجی سخت‌گیرانه تخصص پزشک ---
def validate_doctor_specialty(specialty):
    invalid_terms = ["متخصص تنها", "قب", "متخصص", "عمومی", "ندارد", "ناشناس", "-"]
    specialty_clean = specialty.strip()
    if not specialty_clean or specialty_clean in invalid_terms or len(specialty_clean) < 3:
        return False, "❌ تخصص پزشک وارد شده نامعتبر یا بسیار مبهم است. لطفاً تخصص دقیق (مثلاً: قلب و عروق، داخلی، اطفال) را وارد کنید."
    return True, specialty_clean

# --- بررسی منطق بیمه‌ای و دارویی (قوانین رایگان و محلی) ---
def evaluate_prescription(session, prescription_text):
    warnings = []
    
    # بررسی تاریخ انقضای بیمه‌نامه
    if session["expiry_date"]:
        try:
            expiry = datetime.strptime(session["expiry_date"], "%Y-%m-%d")
            today = datetime.now()
            if expiry < today:
                warnings.append("❌ تاریخ اعتبار بیمه‌نامه منقضی شده است!")
        except:
            pass

    # بررسی تطابق تخصص پزشک با نوع دارو
    specialty = session["doctor_specialty"]
    if "پلاویکس" in prescription_text or "قلب" in prescription_text:
        if "قلب" not in specialty and "عروق" not in specialty and "داخلی" not in specialty:
            warnings.append("⚠️ هشدار: تجویز داروهای تخصصی قلب با تخصص پزشک (" + specialty + ") همخوانی ندارد. نیاز به بررسی توسط داروخانه.")

    # بررسی استثنای ویتامین C و D (معاف از متخصص)
    if "ویتامین d" in prescription_text.lower() or "ویتامین c" in prescription_text.lower():
        warnings.append("✅ اقلام شامل معافیت (ویتامین C/D) بدون نیاز به تخصص خاص تأیید می‌شوند.")

    return warnings

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        message = data.get("message", {})
        user_id = str(message.get("from", {}).get("id", "12345"))
        text = message.get("text", "").strip()
    except:
        return jsonify({"status": "error"}), 400

    session = get_session(user_id)
    step = session["step"]
    response_text = ""

    if text == "/start" or step == "START":
        update_session(user_id, step="GET_PHARMACY")
        response_text = "سلام متصدی محترم داروخانه؛\nلطفاً «نام داروخانه» خود را وارد کنید:"

    elif step == "GET_PHARMACY":
        update_session(user_id, pharmacy_name=text, step="GET_ORG")
        response_text = f"نام داروخانه ثبت شد: {text}\nلطفاً «نام سازمان / محل کار بیمه‌شده» را وارد کنید:"

    elif step == "GET_ORG":
        update_session(user_id, org_name=text, step="GET_AGE")
        response_text = "سازمان بیمه‌شده ثبت شد.\nلطفاً «سن بیمه‌شده» (فقط عدد صحیح) را وارد کنید:"

    elif step == "GET_AGE":
        if not text.isdigit():
            response_text = "❌ لطفاً سن بیمار را فقط به صورت عدد صحیح وارد کنید:"
        else:
            update_session(user_id, patient_age=int(text), step="GET_EXPIRY")
            response_text = "سن بیمار ثبت شد.\nلطفاً «تاریخ پایان اعتبار بیمه‌نامه» را با فرمت (YYYY-MM-DD) وارد کنید:"

    elif step == "GET_EXPIRY":
        update_session(user_id, expiry_date=text, step="GET_SPECIALTY")
        response_text = "تاریخ اعتبار ثبت شد.\nلطفاً «تخصص پزشک تجویزکننده» را با دقت وارد کنید (مثلاً قلب و عروق، اطفال):"

    elif step == "GET_SPECIALTY":
        is_valid, msg = validate_doctor_specialty(text)
        if not is_valid:
            response_text = msg
        else:
            update_session(user_id, doctor_specialty=msg, step="GET_IMAGE")
            response_text = "✅ تخصص پزشک تأیید شد.\nاکنون لطفاً نام اقلام دارویی نسخه یا تصویر پیش‌فاکتور را وارد کنید:"

    elif step == "GET_IMAGE":
        prescription_text = text
        warnings = evaluate_prescription(session, prescription_text)
        
        summary = (
            f"📋 **نتیجه ارزیابی هوشمند نسخه (بیمه البرز):**\n"
            f"🏥 داروخانه: {session['pharmacy_name']}\n"
            f"🏢 سازمان: {session['org_name']}\n"
            f"👤 سن بیمار: {session['patient_age']}\n"
            f"🩺 تخصص پزشک: {session['doctor_specialty']}\n"
            f"-------------------\n"
        )
        if warnings:
            summary += "\n".join(warnings)
        else:
            summary += "✅ نسخه فاقد مغایرت قانونی است و تایید می‌شود."

        response_text = summary
        update_session(user_id, step="START")

    return jsonify({"method": "sendMessage", "chat_id": user_id, "text": response_text})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
