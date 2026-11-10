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
    try:
        url = f"{BALE_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        resp = requests.post(url, json=payload, timeout=15)
        logger.info(f"Send message status: {resp.status_code}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def get_file_url(file_id):
    try:
        url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=15).json()
        if resp.get("ok"):
            file_path = resp["result"]["file_path"]
            return f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
    except Exception as e:
        logger.error(f"Error getting file url: {e}")
    return None

def process_and_reply(chat_id, img_url, pharmacy, organization, specialty):
    """پردازش تصویر در پس‌زمینه برای جلوگیری از تایم‌اوت وب‌هوک بله"""
    try:
        if not GEMINI_API_KEY:
            send_message(chat_id, "❌ خطا: کلید هوش مصنوعی (GEMINI_API_KEY) در سرور تنظیم نشده است.")
            return

        logger.info(f"Downloading image from: {img_url}")
        img_resp = requests.get(img_url, timeout=35)
        if img_resp.status_code != 200:
            send_message(chat_id, "❌ خطا در بارگیری تصویر نسخه از سرور بله.")
            return

        image_bytes = img_resp.content

        prompt = (
            "تو ارزیاب و ناظر تخصصی اسناد دارویی بیمه البرز هستی.\n"
            f"اطلاعات نسخه:\n"
            f"- داروخانه: {pharmacy}\n"
            f"- سازمان متبوع: {organization}\n"
            f"- تخصص پزشک: {specialty}\n\n"
            "دستورالعمل:\n"
            "۱. تمام اقلام فاکتور/نسخه را با نام، تعداد، دوز و قیمت تک‌به‌تک شماره‌گذاری کن.\n"
            f"۲. بررسی کن آیا اقلام با تخصص پزشک ({specialty}) مرتبط هستند یا خیر.\n"
            f"۳. قوانین اختصاصی شیوه‌نامه سازمان '{organization}' و ضوابط عمومی بیمه البرز (مکمل، ویتامین، برند، حق فنی) را روی هر قلم تطبیق بده.\n"
            "۴. وضعیت هر قلم را صریحاً مشخص کن: [قابل پرداخت] یا [غیرقابل پرداخت] یا [مشروط به تایید پزشک معتمد/مدارک].\n"
            "۵. جمع‌بندی نهایی را اعلام کن."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        
        logger.info("Calling Gemini API...")
        response = model.generate_content([prompt, image_part])
        
        if response and response.text:
            result_text = f"📋 نتیجه بررسی نسخه:\n\n{response.text}"
            # ارسال نتیجه به متصدی
            send_message(chat_id, result_text)
        else:
            send_message(chat_id, "⚠️ متنی از تصویر نسخه استخراج نشد. لطفاً تصویر واضح‌تری ارسال فرمایید.")

    except Exception as e:
        logger.error(f"Processing Error: {e}")
        send_message(chat_id, f"❌ خطا در پردازش نسخه: {str(e)}")

    finally:
        # پیام پایان و ریست وضعیت کاربر برای نسخه بعدی
        user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
        send_message(chat_id, "✅ رسیدگی نسخه پایان یافت.\n🔄 برای بررسی نسخه جدید، دستور /start را ارسال کنید.")

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

        # ریست با دستور شروع
        if text in ["/start", "شروع", "شروع مجدد", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۴: لطفاً نام داروخانه را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۴: لطفاً نام داروخانه را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]

        # ۱. نام داروخانه
        if state["step"] == "WAIT_PHARMACY":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام معتبری برای داروخانه وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_message(
                chat_id,
                f"✅ داروخانه: {text} ثبت شد.\n\n"
                "📌 مرحله ۲ از ۴: لطفاً نام سازمان بیمه‌شده / ارگان متبوع را وارد نمایید (مثال: بانک توسعه تعاون، جهاد کشاورزی و...):"
            )
            return jsonify({"status": "ok"}), 200

        # ۲. نام سازمان
        elif state["step"] == "WAIT_ORG":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام سازمان بیمه‌شده را وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["org"] = text
            state["step"] = "WAIT_SPEC"
            send_message(
                chat_id,
                f"✅ سازمان: {text} ثبت شد.\n\n"
                "📌 مرحله ۳ از ۴: لطفاً تخصص پزشک تجویزکننده را وارد کنید (مثال: عمومی، متخصص داخلی، متخصص مغز و اعصاب و...):"
            )
            return jsonify({"status": "ok"}), 200

        # ۳. تخصص پزشک
        elif state["step"] == "WAIT_SPEC":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ تخصص پزشک را به درستی تایپ کنید (مثلاً: عمومی یا متخصص مغز و اعصاب):")
                return jsonify({"status": "ok"}), 200

            state["spec"] = text
            state["step"] = "WAIT_IMG"
            send_message(
                chat_id,
                f"✅ تخصص پزشک: {text} ثبت شد.\n\n"
                "📌 مرحله ۴ از ۴: اکنون تصویر واضح، خوانا و اسکن‌شده نسخه یا پیش‌فاکتور را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # ۴. دریافت تصویر و تحلیل در Thread جداگانه
        elif state["step"] == "WAIT_IMG":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif document and document.get("mime_type", "").startswith("image/"):
                file_id = document.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ لطفاً فایل ارسالی به صورت تصویر (عکس نسخه) باشد.")
                return jsonify({"status": "ok"}), 200

            send_message(chat_id, "⏳ تصویر دریافت شد. در حال استخراج و بررسی دقیق اقلام طبق ضوابط بیمه البرز...")
            img_url = get_file_url(file_id)

            if not img_url:
                send_message(chat_id, "❌ خطایی در خواندن لینک فایل از بله رخ داد. لطفاً دوباره عکس را بفرستید.")
                return jsonify({"status": "ok"}), 200

            # اجرا در Thread مجزا تا وب‌هوک معطل نشود و گیر نکند
            t = threading.Thread(
                target=process_and_reply,
                args=(chat_id, img_url, state["pharmacy"], state["org"], state["spec"])
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
