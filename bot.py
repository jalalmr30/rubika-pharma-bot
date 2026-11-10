import os
import logging
import threading
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini configured successfully.")
    except Exception as e:
        logger.error(f"Gemini config error: {e}")

user_states = {}
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_message(chat_id, text):
    """ارسال پیام با تقسیم خودکار متن‌های طولانی به چند پیام"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        # بله محدودیت طول کاراکتر دارد، متن را در قطعات ۱۵۰۰ کاراکتری ارسال می‌کنیم
        max_len = 1500
        for i in range(0, len(text), max_len):
            chunk = text[i:i + max_len]
            payload = {"chat_id": chat_id, "text": chunk}
            requests.post(url, json=payload, timeout=15)
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def download_bale_file(file_id):
    """دانلود مطمئن فایل از بله با بررسی هر دو روش file_path و دانلود مستقیم"""
    try:
        url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=15).json()
        if not resp.get("ok"):
            logger.error(f"getFile failed: {resp}")
            return None

        file_path = resp.get("result", {}).get("file_path")
        if not file_path:
            return None

        # دانلود محتوای فایل
        file_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        dl_resp = requests.get(file_url, timeout=30)
        if dl_resp.status_code == 200:
            return dl_resp.content
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
    return None

def process_and_reply(chat_id, file_id, pharmacy, organization, specialty):
    """پردازش مستقل نسخه و ارسال خروجی تضمینی"""
    try:
        if not GEMINI_API_KEY:
            send_message(chat_id, "❌ خطا: کلید هوش مصنوعی در تنظیمات سرور ثبت نشده است.")
            return

        image_bytes = download_bale_file(file_id)
        if not image_bytes:
            send_message(chat_id, "❌ دریافت فایل تصویر از سرور بله ناموفق بود. لطفاً دوباره عکس نسخه را ارسال کنید.")
            return

        prompt = (
            "تو ارزیاب ارشد اسناد دارویی بیمه البرز هستی.\n"
            f"نام داروخانه: {pharmacy}\n"
            f"نام سازمان بیمه‌شده: {organization}\n"
            f"تخصص پزشک معالج: {specialty}\n\n"
            "دستورات اختصاصی:\n"
            "۱. کلیه اقلام تصویر نسخه/فاکتور را تک‌به‌تک همراه با تعداد، دوز و قیمت استخراج و شماره‌گذاری کن.\n"
            f"۲. تطابق داروها با تخصص اعلام‌شده پزشک ({specialty}) را بررسی کن.\n"
            f"۳. قوانین اختصاصی سازمان '{organization}' و ضوابط بیمه البرز (در خصوص مکمل‌ها، ویتامین‌ها، داروهای خارجی و حق فنی) را بررسی کن.\n"
            "۴. به تفکیک هر قلم اعلام کن: [قابل پرداخت]، [غیرقابل پرداخت]، یا [مشروط به تایید پزشک معتمد].\n"
            "۵. در انتها جمع مبالغ و راهنمایی لازم برای داروخانه را بنویس."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        
        response = model.generate_content([prompt, image_part])
        
        if response and response.text:
            send_message(chat_id, f"📋 نتیجه بررسی کارشناسی نسخه:\n\n{response.text}")
        else:
            send_message(chat_id, "⚠️ نتیجه‌ای از تصویر نسخه استخراج نشد. لطفاً عکس واضح‌تری بفرستید.")

    except Exception as e:
        logger.error(f"Processing error: {e}")
        send_message(chat_id, f"❌ خطا در پردازش نسخه: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
        send_message(chat_id, "✅ رسیدگی این نسخه تمام شد.\n🔄 برای بررسی نسخه جدید دستور /start را ارسال کنید.")

@app.route("/", methods=["GET"])
def home():
    return "Pharma Bot is Running!", 200

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "no data"}), 200

        message = data.get("message")
        if not message:
            return jsonify({"status": "no message"}), 200

        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        photo = message.get("photo")
        document = message.get("document")

        if not chat_id:
            return jsonify({"status": "no chat_id"}), 200

        # شروع یا ریست
        if text in ["/start", "شروع", "شروع مجدد", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۴: لطفاً نام داروخانه را وارد فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۴: لطفاً نام داروخانه را وارد فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]

        # ۱. دریافت نام داروخانه
        if state["step"] == "WAIT_PHARMACY":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام داروخانه را به درستی تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_message(
                chat_id,
                f"✅ نام داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۴: لطفاً نام سازمان بیمه‌شده / ارگان متبوع را وارد فرمایید (مثال: بانک توسعه تعاون، جهاد کشاورزی و...):"
            )
            return jsonify({"status": "ok"}), 200

        # ۲. دریافت نام سازمان
        elif state["step"] == "WAIT_ORG":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام سازمان بیمه‌شده را وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["org"] = text
            state["step"] = "WAIT_SPEC"
            send_message(
                chat_id,
                f"✅ سازمان: {text}\n\n"
                "📌 مرحله ۳ از ۴: لطفاً تخصص پزشک معالج را وارد فرمایید (مثال: عمومی، متخصص مغز و اعصاب، ارتوپد و...):"
            )
            return jsonify({"status": "ok"}), 200

        # ۳. دریافت تخصص پزشک
        elif state["step"] == "WAIT_SPEC":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً تخصص پزشک را تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["spec"] = text
            state["step"] = "WAIT_IMG"
            send_message(
                chat_id,
                f"✅ تخصص پزشک: {text}\n\n"
                "📌 مرحله ۴ از ۴: اکنون لطفاً تصویر نسخه یا پیش‌فاکتور را ارسال کنید:"
            )
            return jsonify({"status": "ok"}), 200

        # ۴. دریافت تصویر و اجرای پردازش در پس‌زمینه
        elif state["step"] == "WAIT_IMG":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif document and document.get("mime_type", "").startswith("image/"):
                file_id = document.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ لطفاً فایل ارسالی به صورت عکس (تصویر نسخه) باشد.")
                return jsonify({"status": "ok"}), 200

            send_message(chat_id, "⏳ تصویر دریافت شد. در حال استخراج و تحلیل بند به بند نسخه...")

            # ارسال file_id به ترد جداگانه
            t = threading.Thread(
                target=process_and_reply,
                args=(chat_id, file_id, state["pharmacy"], state["org"], state["spec"])
            )
            t.start()

            return jsonify({"status": "ok"}), 200

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
