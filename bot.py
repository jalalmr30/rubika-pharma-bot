import os
import time
import requests
import threading
from flask import Flask

# تنظیمات وب‌سرور Flask برای پاسخ به پلتفرم Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Rubika Pharma Bot is running successfully!"

# --- تنظیمات ربات ---
BOT_TOKEN = "توکن_اصلی_روبیکای_خود_را_اینجا_بگذارید"  # توکن ربات شما
API_URL = f"https://bot.rubika.ir/v0/{BOT_TOKEN}"
# اگر ربات برای پیام‌رسان بله است، خط بالا را به این صورت تغییر دهید:
# API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

def main_loop():
    print("Rubika Pharma Bot (Background Worker) is LISTENING...")
    offset = 0
    while True:
        try:
            response = requests.post(f"{API_URL}/getUpdates", json={"offset": offset}, timeout=30)
            if response.status_code == 200:
                data = response.json()
                updates = data.get("result", [])
                for update in updates:
                    offset = update.get("update_id", 0) + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    
                    if text == "/start":
                        # پاسخ اولیه به کاربر
                        requests.post(f"{API_URL}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": "سلام! به ربات بررسی نسخ دارویی بیمه البرز خوش آمدید.\nلطفاً محل کار / سازمان بیمه‌شده خود را وارد کنید:"
                        })
            else:
                time.sleep(3)
        except Exception as e:
            print(f"Error in bot loop: {e}")
            time.sleep(5)

# اجرای حلقه ربات در یک ترد جداگانه در پس‌زمینه (کاملاً ایمن برای Gunicorn)
bot_thread = threading.Thread(target=main_loop, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    # در صورت اجرا روی لوکال
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
