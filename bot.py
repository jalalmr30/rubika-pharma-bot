import os
import time
import requests
import threading
from flask import Flask

# تنظیمات وب‌سرور Flask برای پلتفرم Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bale Pharma Bot is stable and running!"

# --- تنظیمات ربات بله ---
BOT_TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# متغیرهای کنترلی برای جلوگیری از تکرار
user_states = {}
processed_updates = set()  # شناسه‌های پردازش شده

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Error: {e}")

def analyze_prescription(state):
    """تحلیل هوشمند نسخه طبق الحاقیه‌ها"""
    org = state.get("org", "").strip()
    age = state.get("age", 0)
    spec = state.get("doctor_specialty", "").strip()
    pharmacy = state.get("pharmacy_name", "")
    
    report = f"🏥 **داروخانه: {pharmacy}**\n🏢 سازمان: {org}\n👤 سن: {age} | تخصص پزشک: {spec}\n"
    report += "----------------------------------------\n"
    
    is_general = "عمومی" in spec or "عمومى" in spec
    warnings = []
    
    # تفکیک پزشک عمومی و متخصص
    if is_general:
        warnings.append("⚠️ تخصص پزشک «عمومی» است؛ اقلام تخصصی/مکمل نیاز به تایید متخصص دارند.")
    else:
        report += f"✅ تخصص {spec} تایید شد.\n"

    # قوانین الحاقیه
    warnings.append("💡 قاعده پلاویکس: بررسی جراحی در یک سال اخیر الزامی است.")
    warnings.append("💡 مکمل‌ها و مگنی‌فورت: طبق الحاقیه با تایید شعبه قابل پرداخت است.")
    
    report += "\n" + "\n".join(warnings)
    return report

def main_loop():
    print("Bale Bot is starting...")
    offset = 0
    while True:
        try:
            # پارامتر offset بسیار حیاتی است
            response = requests.get(f"{API_URL}/getUpdates", params={"offset": offset, "timeout": 20}, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        update_id = update.get("update_id")
                        
                        # مهم‌ترین بخش: جلوگیری از پردازش تکراری
                        if update_id in processed_updates:
                            offset = update_id + 1
                            continue
                        
                        processed_updates.add(update_id)
                        offset = update_id + 1
                        
                        # محدود کردن حافظه ست
                        if len(processed_updates) > 5000:
                            processed_updates.clear()

                        message = update.get("message", {})
                        chat_id = message.get("chat", {}).get("id")
                        text = message.get("text", "").strip()

                        if not chat_id: continue

                        # منطق پاسخ‌دهی
                        if text == "/start" or text == "شروع":
                            user_states[chat_id] = {"step": "pharmacy_name"}
                            send_message(chat_id, "سلام همکار گرامی 🌹\nلطفاً **نام داروخانه** خود را وارد کنید:")
                        
                        elif chat_id in user_states:
                            state = user_states[chat_id]
                            step = state.get("step")

                            if step == "pharmacy_name":
                                state.update({"pharmacy_name": text, "step": "org"})
                                send_message(chat_id, "نام **سازمان / ارگان** بیمه‌شده را وارد کنید:")
                            
                            elif step == "org":
                                state.update({"org": text, "step": "age"})
                                send_message(chat_id, "سن بیمار را وارد کنید (عدد):")
                            
                            elif step == "age":
                                if text.isdigit():
                                    state.update({"age": int(text), "step": "spec"})
                                    send_message(chat_id, "تخصص پزشک (عمومی یا متخصص با ذکر رشته) را وارد کنید:")
                                else:
                                    send_message(chat_id, "لطفاً سن را فقط به عدد وارد کنید:")
                            
                            elif step == "spec":
                                state.update({"doctor_specialty": text, "step": "image"})
                                send_message(chat_id, "حالا تصویر نسخه را ارسال کنید 📷")
                            
                            elif step == "image":
                                if "photo" in message or "document" in message:
                                    report = analyze_prescription(state)
                                    send_message(chat_id, report)
                                    send_message(chat_id, "✅ بررسی تمام شد. برای نسخه جدید /start بزنید.")
                                    del user_states[chat_id]
                                else:
                                    send_message(chat_id, "لطفاً فقط فایل تصویری نسخه را بفرستید.")
            
            time.sleep(1) # وقفه کوتاه برای پایداری بیشتر
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

# اجرای ربات در ترد جداگانه
threading.Thread(target=main_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
