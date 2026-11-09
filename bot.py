import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# تنظیمات لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# توکن ربات بله
TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# راه‌اندازی گوگل جمنای
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.error("خطا: متغیر محیطی GEMINI_API_KEY تنظیم نشده است!")

def send_message(chat_id, text):
    """تابع ارسال پیام به کاربر در پیام‌رسان بله"""
    url = f"{BALE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        logger.error(f"خطا در ارسال پیام: {e}")
        return None

def download_bale_file(file_id):
    """دانلود تصویر نسخه از بله"""
    try:
        file_info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(file_info_url).json()
        if not resp.get("ok"):
            return None
        file_path = resp["result"]["file_path"]
        
        download_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        file_bytes = requests.get(download_url).content
        return file_bytes
    except Exception as e:
        logger.error(f"خطا در دانلود فایل از بله: {e}")
        return None

@app.route(f"/webhook/{TOKEN}", methods=['POST'])
def webhook():
    """مسیر وب‌پوک برای دریافت پیام‌ها و تصاویر از بله"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "ok"}), 200

        message = data.get("message") or data.get("callback_query", {}).get("message")
        if not message:
            return jsonify({"status": "ok"}), 200

        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()
        photo_list = message.get("photo")
        document = message.get("document")

        # دستور شروع
        if text == "/start":
            send_message(chat_id, "سلام متصدی محترم داروخانه؛\nبه ربات هوشمند ارزیابی نسخ بیمه البرز خوش آمدید.\n\nلطفاً **تصویر نسخه یا پیش‌فاکتور** خود را ارسال کنید تا بررسی و تحلیل هوشمند انجام شود.")
            return jsonify({"status": "ok"}), 200

        # اگر کاربر تصویر فرستاد
        if photo_list or document:
            send_message(chat_id, "⏳ در حال پردازش تصویر و ارزیابی نسخه بر اساس ضوابط بیمه البرز...")

            file_id = photo_list[-1]["file_id"] if photo_list else document["file_id"]
            image_bytes = download_bale_file(file_id)

            if not image_bytes:
                send_message(chat_id, "خطا در دریافت تصویر. لطفاً دوباره تصویر نسخه را بفرستید.")
                return jsonify({"status": "ok"}), 200

            if GEMINI_API_KEY:
                try:
                    prompt = """
                    تو دستیار هوشمند بررسی نسخ دارویی بیمه البرز هستی.
                    تصویر نسخه/پیش‌فاکتور ارسال شده را با دقت بررسی کن و موارد زیر را اعلام کن:
                    ۱. اقلام دارویی تجویز شده
                    ۲. تطابق تخصص پزشک و ضوابط دارویی
                    ۳. نتیجه‌گیری نهایی (تایید یا نیاز به بررسی بیشتر)
                    """
                    image_part = {
                        "mime_type": "image/jpeg",
                        "data": image_bytes
                    }
                    response = gemini_model.generate_content([prompt, image_part])
                    analysis_text = response.text
                except Exception as e:
                    logger.error(f"خطا در پردازش هوش مصنوعی: {e}")
                    analysis_text = "خطا در تحلیل هوشمند تصویر نسخه. لطفاً مجدداً تلاش کنید."
            else:
                analysis_text = "سرویس هوش مصنوعی غیرفعال است."

            send_message(chat_id, f"📋 **نتیجه ارزیابی هوشمند نسخه:**\n\n{analysis_text}")
        else:
            send_message(chat_id, "لطفاً برای بررسی نسخه، **تصویر** آن را ارسال کنید یا دستور /start را بزنید.")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"خطا در وب‌پوک: {e}")
        return jsonify({"status": "error"}), 500

@app.route("/", methods=['GET'])
def home():
    return "Rubika Pharma Bot is running successfully!", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
