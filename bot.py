import os
import sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)

# راه‌اندازی پایگاه داده محلی SQLite برای ذخیره وضعیت مکاتبات متصدی داروخانه
DB_NAME = 'bot_database.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_state (
            chat_id TEXT PRIMARY KEY,
            step TEXT,
            pharmacy_name TEXT,
            organization TEXT,
            age INTEGER,
            expiry_date TEXT,
            doctor_specialty TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    return "Rubika Pharma Bot (Bimeh Alborz) is running successfully!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ok"})

    # استخراج اطلاعات پیام از ساختار پیام‌رسان بله / روبیکا
    try:
        message = data.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', message.get('from', {}).get('id', '')))
        text = message.get('text', '').strip()
        
        if not chat_id:
            return jsonify({"status": "ok"})

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT step, pharmacy_name, organization, age, expiry_date, doctor_specialty FROM user_state WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()

        if not row or text == '/start':
            # شروع مکالمه و گام اول: پرسیدن نام داروخانه از متصدی
            cursor.execute('INSERT OR REPLACE INTO user_state (chat_id, step) VALUES (?, ?)', (chat_id, 'get_pharmacy'))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "سلام متصدی محترم داروخانه؛\nبه سامانه هوشمند بررسی نسخ بیمه البرز خوش آمدید.\n\nلطفاً «نام داروخانه» خود را وارد کنید:"
            })

        step, pharmacy_name, organization, age, expiry_date, doctor_specialty = row

        if step == 'get_pharmacy':
            cursor.execute('UPDATE user_state SET pharmacy_name = ?, step = ? WHERE chat_id = ?', (text, 'get_org', chat_id))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "ممنون.\nلطفاً «نام سازمان / محل کار بیمه‌شده» را وارد کنید:"
            })

        elif step == 'get_org':
            cursor.execute('UPDATE user_state SET organization = ?, step = ? WHERE chat_id = ?', (text, 'get_age', chat_id))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "لطفاً «سن بیمه‌شده» را به صورت عدد صحیح وارد کنید:"
            })

        elif step == 'get_age':
            try:
                age_val = int(text)
            except ValueError:
                conn.close()
                return jsonify({
                    "method": "sendMessage",
                    "chat_id": chat_id,
                    "text": "لطفاً سن را فقط به صورت عدد صحیح وارد کنید:"
                })
            cursor.execute('UPDATE user_state SET age = ?, step = ? WHERE chat_id = ?', (age_val, 'get_expiry', chat_id))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "لطفاً «تاریخ پایان اعتبار بیمه‌نامه (Expiry Date)» را وارد کنید (مثلا 1405/12/29):"
            })

        elif step == 'get_expiry':
            cursor.execute('UPDATE user_state SET expiry_date = ?, step = ? WHERE chat_id = ?', (text, 'get_doctor', chat_id))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "لطفاً «تخصص پزشک تجویزکننده» را با دقت وارد کنید (مثلاً قلب و عروق، عمومی، داخلی):"
            })

        elif step == 'get_doctor':
            cursor.execute('UPDATE user_state SET doctor_specialty = ?, step = ? WHERE chat_id = ?', (text, 'completed', chat_id))
            conn.commit()
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": f"اطلاعات اولیه با موفقیت ثبت شد:\n\n داروخانه: {pharmacy_name}\n سازمان: {organization}\n تخصص پزشک: {text}\n\nاکنون لطفاً تصویر یا اقلام نسخه را برای ارزیابی هوشمند ضوابط بیمه البرز ارسال کنید."
            })

        else:
            conn.close()
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "برای شروع بررسی نسخه جدید، دستور /start را ارسال کنید."
            })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
