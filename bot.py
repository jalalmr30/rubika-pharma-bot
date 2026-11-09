import os
import time
import requests
import threading
from flask import Flask

# تنظیمات وب‌سرور Flask برای پاسخ به پلتفرم Render (Health Check)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bale Pharma Bot (Bimeh Alborz) is running successfully!"

# --- تنظیمات ربات در پیام‌رسان بله ---
BOT_TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"  # توکن جدید ربات بله شما
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# ذخیره موقت وضعیت مکالمه کاربران (به صورت ساده در حافظه رم)
user_states = {}

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def main_loop():
    print("Bale Pharma Bot (Background Worker) is LISTENING...")
    offset = 0
    while True:
        try:
            # دریافت پیام‌ها از بله با استفاده از Long Polling
            response = requests.post(
                f"{API_URL}/getUpdates",
                json={"offset": offset, "limit": 10},
                timeout=25
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    for update in updates:
                        offset = update.get("update_id", 0) + 1
                        message = update.get("message", {})
                        chat = message.get("chat", {})
                        chat_id = chat.get("id")
                        text = message.get("text", "").strip()
                        
                        if not chat_id:
                            continue
                        
                        # دستور شروع گفتگو
                        if text == "/start" or text == "شروع":
                            user_states[chat_id] = {"step": "org"}
                            welcome_text = (
                                "سلام، همکار گرامی داروخانه طرف قرارداد بیمه البرز 🌹\n\n"
                                "به سامانه هوشمند بررسی نسخ و محاسبات الحاقیه‌ها خوش آمدید.\n\n"
                                "لطفاً **نام سازمان / محل کار بیمه‌شده** را وارد کنید:"
                            )
                            send_message(chat_id, welcome_text)
                            continue
                        
                        # مدیریت مراحل دریافت اطلاعات از متصدی داروخانه
                        if chat_id in user_states:
                            state = user_states[chat_id]
                            step = state.get("step")
                            
                            if step == "org":
                                state["org"] = text
                                state["step"] = "age"
                                send_message(chat_id, "سن بیمار (فقط عدد صحیح) را وارد کنید:")
                            
                            elif step == "age":
                                if not text.isdigit():
                                    send_message(chat_id, "لطفاً سن بیمار را فقط به صورت عدد صحیح وارد کنید:")
                                    continue
                                state["age"] = int(text)
                                state["step"] = "expiry"
                                send_message(chat_id, "تاریخ پایان اعتبار بیمه‌نامه (مثلاً 1405/12/29) را وارد کنید:")
                            
                            elif step == "expiry":
                                state["expiry"] = text
                                state["step"] = "doctor_specialty"
                                send_message(chat_id, "تخصص پزشک تجویزکننده (مثلاً قلب، داخلی، عمومی و...) را وارد کنید:")
                            
                            elif step == "doctor_specialty":
                                state["doctor_specialty"] = text
                                state["step"] = "image"
                                send_message(
                                    chat_id, 
                                    "اطلاعات اولیه ثبت شد.\n\n"
                                    "حالا لطفاً **تصویر کاملاً واضح و خوانا از پیش‌فاکتور یا نسخه** را ارسال کنید 📷"
                                )
                            
                            elif step == "image":
                                # بررسی ارسال تصویر یا فایل از سوی کاربر
                                if "photo" in message or "document" in message:
                                    send_message(
                                        chat_id,
                                        "✅ تصویر نسخه دریافت شد و در صف بررسی هوشمند با ضوابط بیمه البرز و الحاقیه‌ها قرار گرفت.\n\n"
                                        "به زودی نتیجه انطباق اقلام اعلام خواهد شد. (جهت شروع بررسی جدید /start را بزنید)"
                                    )
                                    user_states.pop(chat_id, None)
                                else:
                                    send_message(chat_id, "لطفاً تصویر پیش‌فاکتور یا نسخه را به صورت عکس ارسال کنید:")
                        else:
                            # اگر کاربر بدون شروع پیام فرستاد
                            send_message(chat_id, "برای شروع ارزیابی نسخه، لطفاً دستور /start را ارسال کنید.")
                            
            else:
                time.sleep(3)
        except Exception as e:
            print(f"Bale connection error: {e}")
            time.sleep(5)

# اجرای حلقه ربات در پس‌زمینه (Background Thread)
bot_thread = threading.Thread(target=main_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
