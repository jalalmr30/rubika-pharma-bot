import os
import sqlite3
import base64
from flask import Flask, request
import requests

app = Flask(__name__)

TOKEN = os.environ.get('BALE_BOT_TOKEN')
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') 
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
            return file_data
    except Exception as e:
        print(f"Error downloading file: {e}")
    return None

def analyze_prescription_with_vision(image_bytes, specialty, org, age):
    if not OPENAI_API_KEY:
        return "❌ خطای سیستمی: کلید تنظیمات موتور بینایی (OPENAI_API_KEY) در سرور Render تنظیم نشده است."

    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        prompt_text = (
            f"تو یک داروساز و کارشناس ارشد بیمه درمان البرز هستی. این تصویر یک پیش‌فاکتور یا نسخه دارویی است. "
            f"تخصص پزشک تجویزکننده '{specialty}' است و سن بیمار {age} سال و سازمان بیمه‌شده '{org}' است. "
            f"1. متن و اقلام دارویی، مکمل‌ها و ویتامین‌های موجود در تصویر را با دقت کامل و واقعی استخراج کن (مراقب خوانش کلمات پزشکی باش). "
            f"2. بر اساس ضوابط بیمه البرز بررسی کن آیا تجویز هر قلم با تخصص پزشک ('{specialty}') همخوانی دارد یا خیر؟ "
            f"(مثلاً اگر تخصص عمومی است، مکمل‌ها و داروهای تخصصی نیاز به متخصص دارند و رد می‌شوند، اما ویتامین C و D معاف از تخصص هستند). "
            f"3. نتیجه را به صورت خوانا، تفکیک‌شده با علامت‌های تایید (✅) و خطا (❌) همراه با دلیل به زبان فارسی برای متصدی داروخانه بنویس."
        )

        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        res_json = response.json()
        
        if "choices" in res_json:
            return res_json["choices"][0]["message"]["content"]
        else:
            return "❌ خطا در پاسخ‌دهی موتور هوش مصنوعی."
    except Exception as e:
        return f"❌ خطا در اتصال به موتور بینایی: {str(e)}"

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

    if text == "/start" or text.lower() == "انصراف":
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (chat_id, step) VALUES (?, 'GET_PHARMA')", (chat_id,))
        conn.commit()
        conn.close()
        send_message(chat_id, "سلام همکار گرامی (متصدی محترم داروخانه).\nلطفاً نام داروخانه خود را وارد کنید:")
        return "OK", 200

    if step == "GET_PHARMA" or not step or step == "START":
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
        send_message(chat_id, "تخصص پزشک تجویزکننده را به صورت کامل بنویسید:\n(مثلاً: **عمومی**، **متخصص قلب و عروق**، **متخصص داخلی** و...)")

    elif step == "GET_SPECIALTY":
        # اعتبارسنجی سخت‌گیرانه برای جلوگیری از عبور با کلمات ناقص مثل "متخصص تنها" یا "قب"
        clean_text = text.lower().strip()
        invalid_words = ["متخصص تنها", "متخصص", "تخصص", "ندارد", "پ", "قب", "الف", "ب"]
        
        if len(text) < 3 or clean_text in invalid_words:
            send_message(chat_id, "❌ تخصص وارد شده نامعتبر، ناقص یا مبهم است!\nلطفاً نوع تخصص را کامل و دقیق بنویسید (مثلاً: **پزشک عمومی** یا **متخصص اطفال**):")
            return "OK", 200

        update_user(chat_id, "specialty", text)
        update_user(chat_id, "step", "WAIT_PHOTO")
        send_message(chat_id, f"✅ تخصص ثبت‌شده: **{text}**\n\nحالا تصویر کاملاً واضح و خوانا از پیش‌فاکتور یا نسخه را ارسال کنید:")

    elif step == "WAIT_PHOTO":
        photo_list = message.get('photo')
        document = message.get('document')
        
        if photo_list or document:
            current_user = get_user(chat_id)
            org = current_user[3] if current_user[3] else "نامشخص"
            age = current_user[4] if current_user[4] else "نامشخص"
            spec = current_user[6] if current_user[6] else "عمومی"
            
            send_message(chat_id, "⏳ تصویر دریافت شد. در حال تحلیل دقیق اقلام توسط موتور بینایی هوش مصنوعی...")
            
            file_id = photo_list[-1]['file_id'] if photo_list else document['file_id']
            image_bytes = get_file_from_bale(file_id)
            
            if image_bytes:
                analysis_result = analyze_prescription_with_vision(image_bytes, spec, org, age)
                
                final_output = f"📋 **نتیجه بررسی هوشمند نسخه**\n"
                final_output += f"🏥 سازمان: {org} | 👨‍⚕️ تخصص: {spec}\n"
                final_output += "----------------------------------------\n"
                final_output += analysis_result
                final_output += "\n----------------------------------------\n"
                final_output += "🔄 برای بررسی نسخه جدید، دستور زیر را
