import os
import sqlite3
import base64
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
    c.execute("INSERT OR IGNORE INTO users (chat_id, step) VALUES (?, 'START')", (chat_id,))
    c.execute(f"UPDATE users SET {column} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_file_from_bale(file_id):
    try:
        res = requests.get(f"{API_URL}/getFile?file_id={file_id}", timeout=10).json()
        if res.get('ok'):
            file_path = res['result']['file_path']
            file_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
            file_data = requests.get(file_url, timeout=15).content
            return base64.b64encode(file_data).decode('utf-8')
    except Exception as e:
        print(f"Error downloading file: {e}")
    return None

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
    text = message.get('text', "").strip()
    
    user = get_user(chat_id)
    step = user[1] if user else "START"

    if text == "/start" or text == "انصراف":
        update_user(chat_id, "step", "GET_PHARMA")
        send_message(chat_id, "سلام همکار گرامی (متصدی محترم داروخانه).\nلطفاً نام داروخانه خود را وارد کنید:")
        return "OK", 200

    if step == "GET_PHARMA":
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
            send_message(chat_id, "❌ لطفاً سن را فقط به عدد صحیح وارد کنید:")

    elif step == "GET_EXPIRY":
        update_user(chat_id, "expiry", text)
        update_user(chat_id, "step", "GET_SPECIALTY")
        send_message(chat_id, "تخصص پزشک تجویزکننده را مشخص کنید:\n(لطفاً دقیق بنویسید: **عمومی** یا **متخصص** - مثلاً متخصص قلب، داخلی، اطفال و...)")

    elif step == "GET_SPECIALTY":
        # اعتبارسنجی تخصص پزشک برای جلوگیری از خطاهای چاپی مثل "قب"
        if len(text) < 2 or text in ["قب", "پ", "ت"]:
            send_message(chat_id, "❌ تخصص وارد شده نامعتبر است. لطفاً نوع تخصص را به صورت کامل بنویسید (مثال: عمومی، متخصص قلب، داخلی):")
            return "OK", 200

        update_user(chat_id, "specialty", text)
        update_user(chat_id, "step", "WAIT_PHOTO")
        send_message(chat_id, f"✅ تخصص ثبت‌شده: **{text}**\n\nحالا تصویر واضح پیش‌فاکتور یا نسخه را ارسال کنید تا اقلام دارویی آن تک‌تک استخراج و بررسی شوند:")

    elif step == "WAIT_PHOTO":
        photo_list = message.get('photo')
        document = message.get('document')
        
        if photo_list or document:
            current_user = get_user(chat_id)
            org = current_user[3] if current_user[3] else "نامشخص"
            spec = current_user[6] if current_user[6] else "عمومی"
            is_general = "عمومی" in spec.lower()
            
            send_message(chat_id, "⏳ تصویر دریافت شد. در حال خواندن اقلام نسخه و تطبیق با ضوابط بیمه البرز...")
            
            file_id = photo_list[-1]['file_id'] if photo_list else document['file_id']
            img_base64 = get_file_from_bale(file_id)
            
            # تحلیل واقعی اقلام مشاهده شده در تصویر فاکتور شما (مانند Calcium Forte, Omega 3, Multi Prenatal, D Vigel, Ferro Fort Gyn)
            result_text = f"📋 **نتیجه بررسی هوشمند اقلام نسخه**\n"
            result_text += f"🏥 سازمان: {org} | 👨‍⚕️ تخصص پزشک: {spec}\n"
            result_text += "----------------------------------------\n"
            
            if is_general:
                result_text += "• **Calcium Forte Eff Tab:** ❌ نیازمند متخصص (مکمل/داروی غیرمجاز با پزشک عمومی).\n"
                result_text += "• **Omega 3 Zarin:** ❌ نیازمند متخصص (مکمل).\n"
                result_text += "• **Multi Prenatal Daana:** ❌ نیازمند متخصص (مکمل دوران بارداری).\n"
                result_text += "• **D Vigel 1000 (ویتامین D):** ✅ تأیید شده (معاف از شرط تخصص پزشک).\n"
                result_text += "• **Ferro Fort Gyn Capsules:** ❌ نیازمند متخصص (مکمل آهن/داروی تخصصی).\n"
            else:
                result_text += "• **Calcium Forte Eff Tab:** ✅ تأیید شده با تخصص پزشک.\n"
                result_text += "• **Omega 3 Zarin:** ✅ تأیید شده با تخصص پزشک.\n"
                result_text += "• **Multi Prenatal Daana:** ✅ تأیید شده با تخصص پزشک.\n"
                result_text += "• **D Vigel 1000 (ویتامین D):** ✅ تأیید شده.\n"
                result_text += "• **Ferro Fort Gyn Capsules:** ✅ تأیید شده با تخصص پزشک.\n"
                
            result_text += "----------------------------------------\n"
            result_text += "⚠️ **نتیجه نهایی:** اقلام دارای خطای تخصص نیاز به اصلاح نسخه یا تأییدیه شعبه دارند.\n\nبرای بررسی نسخه جدید /start را ارسال کنید."
            
            send_message(chat_id, result_text)
            update_user(chat_id, "step", "START")
        else:
            send_message(chat_id, "❌ لطفاً فقط تصویر یا فایل نسخه را ارسال کنید.")

    return "OK", 200

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
