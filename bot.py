import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# تنظیمات لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# توکن جدید ربات بله
TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# راه‌اندازی گوگل جمنای با کلید محیطی
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # استفاده از مدل سبک و سریع جمنای
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.error("خطا: متغیر محیطی GEMINI_API_KEY تنظیم نشده است!")

# حافظه موقت ساده برای نگهداری وضعیت مکاتبات کاربران (در محیط واقعی از پایگاه داده استفاده شود)
user_states = {}

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
    """دانلود تصویر یا فایل ارسال شده از بله"""
    try:
        # ۱. دریافت مسیر فایل از بله
        file_info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(file_info_url).json()
        if not resp.get("ok"):
            return None
        file_path = resp["result"]["file_path"]
        
        # ۲. دانلود بایت‌های فایل
        download_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        file_bytes = requests.get(download_url).content
        return file_bytes
    except Exception as e:
        logger.error(f"خطا در دانلود فایل از بله: {e}")
        return None

@app.route(f"/webhook/{TOKEN}", methods=['POST'])
def webhook():
    """مسیر وب‌پوک برای دریافت پیام‌ها از بله"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "ok"}), 200

        message = data.get("message") or data.get("callback_query", {}).get("message")
        if not message:
            return jsonify({"status": "ok"}), 200

        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()
        
        # بررسی وضعیت کاربر
        state = user_states.get(chat_id, {"step": "START"})

        # دستور شروع یا ریست
        if text == "/start" or text == "شروع مجدد":
            user_states[chat_id] = {"step": "GET_PHARMACY_NAME"}
            send_message(chat_id, "سلام متصدی محترم داروخانه؛\nبه ربات هوشمند بررسی نسخ و ضوابط دارویی بیمه البرز خوش آمدید.\n\nلطفاً **نام داروخانه** خود را وارد کنید:")
            return jsonify({"status": "ok"}), 200

        step = state.get("step")

        if step == "GET_PHARMACY_NAME":
            state["pharmacy_name"] = text
            state["step"] = "GET_ORGANIZATION"
            user_states[chat_id] = state
            send_message(chat_id, "ممنون. حالا لطفاً **نام سازمان / محل کار بیمه‌شده** را وارد کنید:")

        elif step == "GET_ORGANIZATION":
            state["organization"] = text
            state["step"] = "GET_AGE"
            user_states[chat_id] = state
            send_message(chat_id, "لطفاً **سن بیمه‌شده** (فقط عدد صحیح) را وارد کنید:")

        elif step == "GET_AGE":
            if not text.isdigit():
                send_message(chat_id, "خطا: لطفاً سن بیمه‌شده را به صورت عدد صحیح وارد کنید:")
                return jsonify({"status": "ok"}), 200
            state["age"] = int(text)
            state["step"] = "GET_EXPIRY_DATE"
            user_states[chat_id] = state
            send_message(chat_id, "لطفاً **تاریخ پایان اعتبار بیمه‌نامه** (مثلاً 1405/12/29) را وارد کنید:")

        elif step == "GET_EXPIRY_DATE":
            state["expiry_date"] = text
            state["step"] = "GET_DOCTOR_SPECIALTY"
            user_states[chat_id] = state
            send_message(chat_id, "لطفاً **تخصص پزشک تجویزکننده** را با دقت وارد کنید (مثلاً: قلب و عروق، داخلی، عمومی):")

        elif step == "GET_DOCTOR_SPECIALTY":
            state["doctor_specialty"] = text
            state["step"] = "GET_IMAGE"
            user_states[chat_id] = state
            send_message(chat_id, "اطلاعات اولیه ثبت شد.\nحاکمیت ضوابط آماده است؛ اکنون لطفاً **تصویر کاملاً واضح و خوانا از پیش‌فاکتور یا نسخه** را ارسال کنید:")

        elif step == "GET_IMAGE":
            # بررسی اینکه آیا کاربر عکس فرستاده است
            photo_list = message.get("photo")
            document = message.get("document")

            if not photo_list and not document:
                send_message(chat_id, "لطفاً یک تصویر واضح از نسخه یا پیش‌فاکتور ارسال کنید:")
                return jsonify({"status": "ok"}), 200

            send_message(chat_id, "⏳ در حال پردازش تصویر و ارزیابی هوشمند نسخه بر اساس ضوابط بیمه البرز...")

            # انتخاب بزرگترین سایز عکس در صورت ارسال عکس
            file_id = None
            if photo_list:
                file_id = photo_list[-1]["file_id"]
            elif document:
                file_id = document["file_id"]

            image_bytes = download_bale_file(file_id)
            if not image_bytes:
                send_message(chat_id, "خطا در دریافت تصویر. لطفاً دوباره تصویر نسخه را بفرستید.")
                return jsonify({"status": "ok"}), 200

            # تحلیل با جمنای
            if GEMINI_API_KEY:
                try:
                    prompt = f"""
                    تو دستیار هوشمند ارزیابی نسخ دارویی بیمه البرز هستی. اطلاعات زیر از متصدی داروخانه دریافت شده است:
                    - نام داروخانه: {state.get('pharmacy_name')}
                    - سازمان بیمه‌شده: {state.get('organization')}
                    - سن بیمار: {state.get('age')} سال
                    - تاریخ انقضای بیمه‌نامه: {state.get('expiry_date')}
                    - تخصص پزشک: {state.get('doctor_specialty')}

                    لطفاً تصویر نسخه/پیش‌فاکتور پیوست شده را بررسی کن و موارد زیر را اعلام کن:
                    ۱. اقلام دارویی تجویز شده
                    ۲. تطابق تخصص پزشک با داروهای تجویز شده (آیا تخصص فوق با داروها همخوانی دارد یا نیاز به بررسی دارد؟)
                    ۳. بررسی ضوابط سنی، سقف تعهدات و محدودیت اعتبار
                    ۴. نتیجه‌گیری نهایی (تایید، نیاز به اصلاح یا عدم تعهد)
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
                analysis_text = "سرویس هوش مصنوعی در حال حاضر غیرفعال است."

            send_message(chat_id, f"📋 **نتیجه ارزیابی هوشمند نسخه:**\n\n{analysis_text}\n\nبرای بررسی نسخه جدید، دستور /start را ارسال کنید.")
            # ریست کردن وضعیت برای نسخه جدید
            user_states[chat_id] = {"step": "START"}

        else:
            user_states[chat_id] = {"step": "START"}
            send_message(chat_id, "برای شروع بررسی نسخه، لطفاً دستور /start را ارسال کنید.")

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
