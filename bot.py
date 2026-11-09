import os
import sqlite3
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# تنظیمات اصلی از متغیرهای محیطی Render
TOKEN = os.environ.get('BALE_BOT_TOKEN')
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
# آدرس سایت شما در رندر (مثلا https://app-name.onrender.com)
PUBLIC_URL = os.environ.get('PUBLIC_BASE_URL') 

# دیتابیس برای ذخیره وضعیت کاربران و جلوگیری از پیام تکراری
DB_PATH = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # جدول وضعیت کاربران
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, step TEXT, data TEXT)''')
    # جدول برای جلوگیری از پردازش تکراری پیام‌ها
    c.execute('''CREATE TABLE IF NOT EXISTS processed_updates 
                 (update_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def is_processed(update_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM processed_updates WHERE update_id = ?", (update_id,))
    result = c.fetchone()
    if not result:
        c.execute("INSERT INTO processed_updates (update_id) VALUES (?)", (update_id,))
        conn.commit()
    conn.close()
    return result is not None

def update_user_step(chat_id, step, data=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (chat_id, step, data) VALUES (?, ?, ?)", (chat_id, step, data))
    conn.commit()
    conn.close()

def get_user_step(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT step FROM users WHERE chat_id = ?", (chat_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else "START"

def send_message(chat_id, text):
    url = f"{API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

@app.route('/')
def home():
    return "Bot is Running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update or 'update_id' not in update:
        return "OK", 200

    update_id = update['update_id']
    # جلوگیری از پاسخ تکراری: اگر این ID قبلا پردازش شده، نادیده بگیر
    if is_processed(update_id):
        return "OK", 200

    if 'message' in update:
        message = update['message']
        chat_id = str(message['chat']['id'])
        text = message.get('text', "")

        step = get_user_step(chat_id)

        if text == "/start":
            update_user_step(chat_id, "GET_PHARMA_NAME")
            send_message(chat_id, "سلام همکار گرامی.\nلطفاً نام داروخانه را وارد کنید:")
        
        elif step == "GET_PHARMA_NAME":
            update_user_step(chat_id, "GET_ORG")
            send_message(chat_id, f"نام داروخانه '{text}' ثبت شد.\nحالا نام سازمان بیمه شده را وارد کنید:")

        elif step == "GET_ORG":
            update_user_step(chat_id, "GET_AGE")
            send_message(chat_id, "نام سازمان ثبت شد.\nلطفاً سن بیمه شده را به عدد وارد کنید:")

        elif step == "GET_AGE":
            if text.isdigit():
                update_user_step(chat_id, "GET_EXPIRY")
                send_message(chat_id, "سن ثبت شد.\nتاریخ پایان اعتبار بیمه‌نامه را وارد کنید (مثال: 1405/08/20):")
            else:
                send_message(chat_id, "لطفاً سن را فقط به صورت عدد وارد کنید:")

        elif step == "GET_EXPIRY":
            update_user_step(chat_id, "GET_SPECIALTY")
            send_message(chat_id, "تاریخ ثبت شد.\nتخصص پزشک تجویزکننده را وارد کنید:")

        elif step == "GET_SPECIALTY":
            update_user_step(chat_id, "WAIT_FOR_PHOTO")
            send_message(chat_id, "ممنون. حالا تصویر واضح پیش‌فاکتور یا نسخه را بارگذاری کنید:")

        elif step == "WAIT_FOR_PHOTO":
            if 'photo' in message or 'document' in message:
                send_message(chat_id, "تصویر دریافت شد. در حال بررسی ضوابط بیمه البرز...")
                # در اینجا منطق بررسی فایل‌ها را اضافه خواهید کرد
                send_message(chat_id, "بررسی انجام شد. نسخه جهت تایید نهایی به کارشناس ارجاع شد.")
                update_user_step(chat_id, "START")
            else:
                send_message(chat_id, "لطفاً فایل تصویری نسخه را ارسال کنید.")

    return "OK", 200

# تنظیم خودکار وب‌هوک هنگام شروع برنامه
if PUBLIC_URL:
    webhook_set_url = f"{API_URL}/setWebhook?url={PUBLIC_URL}/webhook"
    requests.get(webhook_set_url)
    print(f"Webhook set to {PUBLIC_URL}/webhook")

init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
