import os
import time
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Rubika Pharma Bot is running successfully!"

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# اجرای وب‌سرور برای پاسخ به پورت رندر
Thread(target=run_web).start()

# توکن و آدرس ربات روبیکا
BOT_TOKEN = "توکن_اصلی_بله_خود_را_اینجا_بگذارید"
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
print("Rubika Pharma Bot (Web Service mode) is LISTENING...")

def main_loop():
    offset = 0
    while True:
        try:
            response = requests.post(f"{API_URL}/getUpdates", json={"offset": offset}, timeout=30)
            if response.status_code == 200:
                data = response.json()
                updates = data.get("result", [])
                for update in updates:
                    offset = update.get("update_id", 0) + 1
                    # منطق و دستورات ربات برای پردازش پیام‌های پرسنل داروخانه
            else:
                time.sleep(5)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
