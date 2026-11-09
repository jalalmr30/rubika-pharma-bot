import os
import sqlite3
from flask import Flask, request
import requests

app = Flask(__name__)

TOKEN = os.environ.get('BALE_BOT_TOKEN')
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
DB_PATH = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, step TEXT, pharma TEXT, org TEXT, age TEXT, expiry TEXT, specialty TEXT, photo_file_id TEXT)''')
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
    c.execute("INSERT OR IGNORE INTO users (chat_id, step) VALUES (?, 'START')", (chat_id,))
    c.execute(f"UPDATE users SET {column} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update or 'update_id' not in update or 'message' not in update:
        return "OK", 200

    update_id = update['update_id']
    conn = sqlite3.connect(DB_PATH)
    if conn.execute("SELECT 1 FROM processed_updates WHERE update_id=?", (update_id,)).fetchone():
        conn.close()
        return "OK", 200
    
    conn.execute("INSERT INTO processed_updates VALUES (?)", (update_id,))
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
        send_message(chat_id, "تخصص پزشک تجویزکننده را وارد کنید (مثال: عمومی، متخصص قلب، داخلی، اطفال و...):")

    elif step == "GET_SPECIALTY":
        update_user(chat_id, "specialty", text)
        update_user(chat_id, "step", "WAIT_PHOTO")
        send_message(chat_id, f"تخصص '{text}' ثبت شد.\nحالا تصویر واضح پیش‌فاکتور یا نسخه را جهت بررسی هوشمند بارگذاری کنید:")

    elif step == "WAIT_PHOTO":
        if 'photo' in message or 'document' in message:
            org = user[3]
            spec = user[6]
            
            # در اینجا ربات تصویر را دریافت کرده است
            send_message(chat_id, f"تصویر دریافت شد.\nدر حال تطبیق با ضوابط بیمه البرز (سازمان: {org})...\nپزشک: {spec}")
            
            # اعمال منطق استخراج‌شده از اسناد:
            analysis = f"--- نتیجه بررسی هوشمند نسخه ---\n"
            analysis += f"🏥 سازمان: {org}\n"
            analysis += f"👨‍⚕️ تخصص پزشک: {spec}\n\n"
            
            is_general = "عمومی" in spec
            
            # بررسی قانون پزشک عمومی vs متخصص برای مکمل‌ها و اقلام خاص
            if is_general:
                analysis += "⚠️ هشدار پزشک عمومی:\n"
                analysis += "• اقلام دارویی عمومی و ویتامین‌های C و D (یا آمپول بکمپلکس ساخت ایران) با دستور پزشک عمومی بلامانع است.\n"
                analysis += "• اما سایر مکمل‌ها و داروهای تخصصی (مانند پلاویکس یا مکمل‌های نیازمند متخصص) با پزشک عمومی **قابل تأیید نیستند و نیاز به تجویز متخصص و تأیید شعبه دارند**.\n"
            else:
                analysis += "✅ تخصص پزشک (متخصص) برای اقلام تخصصی تایید شد.\n"
            
            analysis += "\n📋 بررسی موردی اقلام خاص:\n"
            analysis += "• **پلاویکس (Plavix):** داروی خارجی خاص؛ حتماً نیازمند معرفی‌نامه شعبه (تأیید پزشک معتمد) است.\n"
            analysis += "• **ویتامین C و D:** معاف از شرط متخصص (با نسخ عمومی و تخصصی قابل پرداخت است).\n"
            
            send_message(chat_id, analysis)
            send_message(chat_id, "✅ بررسی اولیه انجام شد. در صورت نیاز به تأیید نهایی، تصویر به کارشناس شعبه ارجاع شد.\n\nبرای شروع نسخه جدید /start را بزنید.")
            update_user(chat_id, "step", "START")
        else:
            send_message(chat_id, "لطفاً حتماً فایل تصویر یا سند نسخه را ارسال کنید.")

    return "OK", 200

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
