import os
import logging
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

# تنظیمات لاگ‌گیری
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# دریافت توکن‌ها از متغیرهای محیطی
TOKEN = os.environ.get("BALE_BOT_TOKEN", "1099104992:7WNzacPcBN11EOOAnHXDzGDN7-c-cUoWCY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# دیکشنری برای نگهداری وضعیت گام‌به‌گام هر کاربر (برای جلوگیری از تداخل نسخه‌ها)
# ساختار: user_states[chat_id] = {"step": "...", "doctor_specialty": "..."}
user_states = {}

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_message(chat_id, text):
    """ارسال پیام متنی به کاربر در بله"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload)
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def get_file_url(file_id):
    """گرفتن لینک دانلود فایل از سرور بله"""
    try:
        url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(url).json()
        if resp.get("ok"):
            file_path = resp["result"]["file_path"]
            return f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
    except Exception as e:
        logger.error(f"Error getting file url: {e}")
    return None

def analyze_prescription_with_gemini(image_url, specialty):
    """ارزیابی هوشمند نسخه توسط جمینی بر اساس قوانین بیمه و تخصص پزشک"""
    try:
        if not GEMINI_API_KEY:
            return "❌ خطا: کلید Gemini API تنظیم نشده است."

        # دانلود تصویر نسخه
        img_resp = requests.get(image_url)
        if img_resp.status_code != 200:
            return "❌ خطا در دریافت تصویر از سرور پیام‌رسان."
        
        image_bytes = img_resp.content

        # استفاده از مدل gemini-1.5-flash
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
تو یک کارشناس ارشد ارزیابی و رسیدگی به اسناد پزشکی و دارویی بیمه البرز هستی.
تخصص پزشک تجویزکننده این نسخه: "{specialty}" است.

لطفاً تصویر نسخه/پیش‌فاکتور ضمیمه شده را به دقت بررسی کن و پاسخ خود را طبق ساختار زیر ارائه بده:

۱. **استخراج اقلام دارویی/خدمات:** نام دقیق هر قلم دارو یا مکمل ذکر شده در تصویر را به صورت لیست‌وار بنویس.
۲. **بررسی تطابق تخصص پزشک:** بررسی کن آیا اقلام تجویز شده با تخصص پزشک ("{specialty}") مطابقت دارد یا خیر؟ (مثلاً داروهای تخصصی قلب باید توسط متخصص قلب تجویز شده باشند).
۳. **قوانین و ضوابط (بیمه البرز):** بررسی کن آیا اقلام مشمول تعهد هستند یا نیاز به تأییدیه/مستندات خاص (مثل بندهای ویتامین‌ها، مکمل‌ها یا محدودیت دوز) دارند.
۴. **نتیجه نهایی ارزیابی:** اعلام کن که نسخه "تایید است"، "نیازمند بررسی بیشتر / تخصص مرتبط است"، یا "مردود" است و دلیل آن را به متصدی داروخانه اعلام کن.
"""

        # ارسال به جمینی (متن + تصویر)
        image_part = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }
        
        response = model.generate_content([prompt, image_part])
        return response.text

    except Exception as e:
        logger.error(f"Gemini analysis error: {e}")
        return f"❌ خطا در پردازش هوشمند تصویر: {str(e)}"

@app.route(f"/webhook/{TOKEN}", methods=['POST'])
@app.route("/webhook", methods=['POST'])
def webhook():
    """در
