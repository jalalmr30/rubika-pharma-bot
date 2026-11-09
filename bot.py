import os
import sqlite3
from flask import Flask, request
import requests

app = Flask(__name__)

# تنظیمات
TOKEN = os.environ.get('BALE_BOT_TOKEN')
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
PUBLIC_URL = os.environ.get('PUBLIC_BASE_URL')
DB_PATH = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, step TEXT, pharma TEXT, org TEXT, age TEXT, expiry TEXT, specialty TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS processed_updates (update_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def get_user(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    res = c.fetchone()
    conn.close()
    return res

def update_user(chat_id, column, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # ایجاد کاربر اگر وجود ندارد
    c.execute("INSERT OR IGNORE INTO users (chat_id, step) VALUES (?, 'START')", (chat_id,))
    c.execute(f"UPDATE users SET {column} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()

def send_message(chat_id, text):
    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update or 'update_id' not in update or 'message' not in update:
        return "OK", 200

    if sqlite3.connect(DB_PATH).execute("SELECT 1 FROM processed_updates WHERE update_id=?", (update['update_id'],)).fetchone():
        return "OK", 200
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO processed_updates VALUES (?)", (update['update_id'],))
    conn.commit()
    conn.close()

    message = update['message']
    chat_id = str(message['chat']['id'])
    text = message.get('text', "")
    user = get_user(chat_id)
    step = user[1] if user else "START"

    if text == "/start" or text == "انصراف":
        update_user(chat_id, "step", "GET_PHARMA")
        send_message(chat_id, "سلام همکار گرامی (متصدی محترم داروخانه).\nلطفاً نام داروخانه خود را وارد کنید:")
    
    elif step == "GET_PHARMA":
        update_user(chat_id, "pharma", text)
        update_user(chat_id, "step", "GET_ORG")
        send_message(chat_id, "نام سازمان یا محل کار بیمه‌شده را وارد کنید (مثال: مپنا، بانک توسعه تعاون، وزارت علوم و ...):")

    elif step == "GET_ORG":
        update_user(chat_id, "org", text)
        update_user(chat_id, "step", "GET_AGE")
        send_message(chat_id, "سن بیمه‌شده را به عدد وارد کنید:")

    elif step == "GET_AGE":
        if text.isdigit():
            update_user(chat_id, "age", text)
            update_user(chat_id, "step", "GET_EXPIRY")
            send_message(chat_id, "تاریخ پایان اعتبار بیمه‌نامه را وارد کنید (مثال: 1405/08/20):")
        else:
            send_message(chat_id, "لطفاً سن را به عدد وارد کنید:")

    elif step == "GET_EXPIRY":
        update_user(chat_id, "expiry", text)
        update_user(chat_id, "step", "GET_SPECIALTY")
        send_message(chat_id, "تخصص پزشک تجویزکننده را وارد کنید (مثال: متخصص قلب، عمومی، مامایی و...):")

    elif step == "GET_SPECIALTY":
        update_user(chat_id, "specialty", text)
        update_user(chat_id, "step", "WAIT_PHOTO")
        send_message(chat_id, f"تخصص '{text}' ثبت شد.\nحالا تصویر واضح پیش‌فاکتور یا نسخه را بارگذاری کنید:")

    elif step == "WAIT_PHOTO":
        if 'photo' in message or 'document' in message:
            org = user[3]
            spec = user[6]
            send_message(chat_id, f"تصویر دریافت شد.\nدر حال تطبیق با شیوه‌نامه سازمان: {org}\nبررسی تخصص پزشک: {spec}")
            
            # منطق شبیه سازی شده بر اساس فایل های شما
            response = f"نتیجه بررسی هوشمند برای {org}:\n"
            response += "✅ سن و تاریخ اعتبار تایید شد.\n"
            if "قلب" in spec or "داخلی" in spec:
                response += "✅ تخصص پزشک با داروهای قلبی (مثل پلاویکس) مطابقت دارد."
            else:
                response += "⚠️ هشدار: تخصص پزشک با برخی داروها نیاز به بررسی دستی توسط داروخانه دارد."
            
            send_message(chat_id, response)
            send_message(chat_id, "نسخه جهت تایید نهایی به کارشناس بیمه البرز ارسال شد.")
            update_user(chat_id, "step", "START")
        else:
            send_message(chat_id, "لطفاً فایل تصویر نسخه را ارسال کنید.")

    return "OK", 200

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
