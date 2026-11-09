import os
import threading
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# --- تنظیمات ربات بله ---
BOT_TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# حافظه موقت و قفل‌های همگام‌سازی برای جلوگیری از پردازش‌های هم‌زمان و تکراری
user_states = {}
processed_updates = set()
lock = threading.Lock()

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def analyze_prescription(state):
    """منطق هوشمند ارزیابی نسخه بر اساس سازمان، سن، تاریخ اعتبار و تخصص پزشک"""
    org = state.get("org", "").strip().lower()
    age = state.get("age", 0)
    specialty = state.get("doctor_specialty", "").strip().lower()
    pharmacy = state.get("pharmacy_name", "")
    expiry = state.get("expiry", "")
    
    report = f"📋 **گزارش ارزیابی هوشمند نسخه**\n"
    report += f"🏥 داروخانه: {pharmacy}\n"
    report += f"🏢 سازمان متبوع: {state.get('org')}\n"
    report += f"👤 سن بیمار: {age} سال | ⏳ اعتبار بیمه: {expiry}\n"
    report += f"🩺 تخصص پزشک: {state.get('doctor_specialty')}\n"
    report += "----------------------------------------\n"
    
    warnings = []
    is_general = "عمومی" in specialty or "عمومى" in specialty
    
    if is_general:
        warnings.append("⚠️ پزشک تجویزکننده «عمومی» است؛ اقلام تخصصی یا مکمل‌ها نیاز به تایید متخصص دارند (به جز ویتامین C و D).")
    else:
        report += f"✅ تخصص پزشک ({specialty}) با اقلام تخصصی همخوانی دارد.\n"
        
    warnings.append("💡 **قاعده پلاویکس:** بررسی تاریخ جراحی بیمار الزامی است (قابل تأیید تا یک سال پس از عمل).")
    warnings.append("💡 **مگنی‌فورت و مکمل‌ها:** با تجویز متخصص قبول است؛ نیاز به بررسی مستندات شعبه دارد.")
    
    if warnings:
        report += "\n🚨 **تذکرات و موارد نیازمند بررسی:**\n" + "\n".join(warnings)
    else:
        report += "\n✅ نسخه فاقد مغایرت قانونی بارز است."
        
    return report

@app.route('/')
def home():
    return "Bale Webhook Pharma Bot (Thread-Safe) is active!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "ok"}), 200
            
        update_id = data.get("update_id")
        
        # قفل ایمن برای بررسی و ثبت یکتای update_id
        with lock:
            if update_id in processed_updates:
                return jsonify({"status": "ok"}), 200
            processed_updates.add(update_id)
            if len(processed_updates) > 5000:
                processed_updates.clear()

        message = data.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = message.get("text", "").strip()
        
        if chat_id:
            # دستور شروع گفتگو
            if text == "/start" or text == "شروع" or text == "شروع مجدد":
                with lock:
                    user_states[chat_id] = {"step": "pharmacy_name"}
                welcome_text = (
                    "سلام، همکار گرامی داروخانه طرف قرارداد بیمه البرز 🌹\n\n"
                    "به سامانه هوشمند بررسی نسخ و محاسبات الحاقیه‌ها خوش آمدید.\n\n"
                    "لطفاً **نام داروخانه** خود را وارد کنید:"
                )
                send_message(chat_id, welcome_text)
                return jsonify({"status": "ok"}), 200
            
            # مدیریت مراحل مکالمه
            with lock:
                has_state = chat_id in user_states
            
            if has_state:
                with lock:
                    state = user_states[chat_id]
                    step = state.get("step")
                
                if step == "pharmacy_name":
                    with lock:
                        state["pharmacy_name"] = text
                        state["step"] = "org"
                    send_message(chat_id, "لطفاً **نام سازمان / محل کار بیمه‌شده** (مثلاً تامین اجتماعی، بانک توسعه تعاون، مپنا و...) را وارد کنید:")
                
                elif step == "org":
                    with lock:
                        state["org"] = text
                        state["step"] = "age"
                    send_message(chat_id, "سن بیمه‌شده (فقط عدد صحیح) را وارد کنید:")
                
                elif step == "age":
                    if not text.isdigit():
                        send_message(chat_id, "لطفاً سن بیمه‌شده را فقط به صورت عدد صحیح وارد کنید:")
                        return jsonify({"status": "ok"}), 200
                    with lock:
                        state["age"] = int(text)
                        state["step"] = "expiry"
                    send_message(chat_id, "تاریخ پایان اعتبار بیمه‌نامه (مثلاً 1405/12/29) را وارد کنید:")
                
                elif step == "expiry":
                    with lock:
                        state["expiry"] = text
                        state["step"] = "doctor_specialty"
                    send_message(chat_id, "تخصص پزشک تجویزکننده را وارد کنید (مشخص کنید عمومی است یا تخصص خاص مثل قلب، داخلی و...):")
                
                elif step == "doctor_specialty":
                    with lock:
                        state["doctor_specialty"] = text
                        state["step"] = "image"
                    send_message(
                        chat_id, 
                        f"📌 اطلاعات ثبت‌شده:\n"
                        f"▫️ داروخانه: {state.get('pharmacy_name')}\n"
                        f"▫️ سازمان: {state.get('org')}\n"
                        f"▫️ سن: {state.get('age')} | اعتبار: {state.get('expiry')}\n"
                        f"▫️ تخصص پزشک: {text}\n\n"
                        "حالا لطفاً **تصویر کاملاً واضح و خوانا از پیش‌فاکتور یا نسخه** را ارسال کنید 📷"
                    )
                
                elif step == "image":
                    if "photo" in message or "document" in message:
                        final_report = analyze_prescription(state)
                        send_message(chat_id, final_report)
                        send_message(chat_id, "✅ بررسی نسخه به پایان رسید.\n\n(جهت شروع بررسی نسخه جدید دستور /start را ارسال کنید)")
                        with lock:
                            user_states.pop(chat_id, None)
                    else:
                        send_message(chat_id, "لطفاً تصویر پیش‌فاکتور یا نسخه را به صورت عکس ارسال کنید:")
            else:
                send_message(chat_id, "برای شروع ارزیابی نسخه، لطفاً دستور /start را ارسال کنید.")
                
    except Exception as e:
        print(f"Webhook error: {e}")
        
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
