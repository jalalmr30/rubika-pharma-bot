import os
import logging
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
    except Exception as e:
        logger.error(f"Gemini config error: {e}")

# مدیریت وضعیت دقیق کاربران (جلوگیری از تداخل و ارسال همزمان سوالات)
user_states = {}

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_message(chat_id, text):
    try:
        url = f"{BALE_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=10)
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

def analyze_prescription(image_url, pharmacy, organization, specialty):
    try:
        if not GEMINI_API_KEY:
            return "❌ خطا: کلید هوش مصنوعی تنظیم نشده است."

        img_resp = requests.get(image_url, timeout=30)
        if img_resp.status_code != 200:
            return "❌ خطا در دریافت تصویر از سرور."

        image_bytes = img_resp.content

        prompt = (
            f"تو یک کارشناس ارشد و ناظر اسناد پزشکی و دارویی بیمه البرز هستی.\n"
            f"مشخصات نسخه:\n"
            f"- داروخانه متقاضی: {pharmacy}\n"
            f"- سازمان بیمه‌شده / ارگان متبوع: {organization}\n"
            f"- تخصص پزشک تجویزکننده: {specialty}\n\n"
            f"دستورالعمل:\n"
            f"۱. اقلام دارویی، مکمل‌ها یا ویتامین‌های موجود در تصویر را تک‌به‌تک و شماره‌گذاری شده استخراج کن.\n"
            f"۲. تطابق داروها با تخصص پزشک ({specialty}) را بررسی کن.\n"
            f"۳. قوانین و ضوابط شیوه‌نامه سازمان '{organization}' و بیمه البرز را روی هر قلم اعمال کن.\n"
            f"۴. وضعیت هر قلم (قابل پرداخت / نیازمند تایید پزشک معتمد / غیرقابل پرداخت) و دلیل کارشناسی آن را بنویس.\n"
            f"۵. در انتها نتیجه کلی ارزیابی را اعلام کن."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        response = model.generate_content([prompt, image_part])
        return response.text if response and response.text else "متنی استخراج نشد."

    except Exception as e:
        logger.error(f"AI Error: {e}")
        return f"خطا در پردازش: {e}"

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

        # دستور شروع یا ریست کامل
        if text in ["/start", "شروع", "شروع مجدد", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 **مرحله ۱ از ۴:** لطفاً **نام داروخانه** را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # اگر کاربر جدید است یا سابقه ندارد
        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 **مرحله ۱ از ۴:** لطفاً **نام داروخانه** را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]

        # گام ۱: دریافت نام داروخانه
        if state["step"] == "WAIT_PHARMACY":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام معتبری برای داروخانه وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_message(
                chat_id,
                f"✅ داروخانه ثبت شد: **{text}**\n\n"
                "📌 **مرحله ۲ از ۴:** لطفاً **نام سازمان بیمه‌شده / ارگان متبوع** را وارد نمایید (مثال: بانک توسعه تعاون، جهاد کشاورزی، نفتکش و...):"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۲: دریافت سازمان بیمه‌شده
        elif state["step"] == "WAIT_ORG":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ لطفاً نام صحیح سازمان بیمه‌شده را وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["org"] = text
            state["step"] = "WAIT_SPEC"
            send_message(
                chat_id,
                f"✅ سازمان ثبت شد: **{text}**\n\n"
                "📌 **مرحله ۳ از ۴:** لطفاً **تخصص پزشک تجویزکننده** را وارد کنید (مثال: عمومی، قلب و عروق، داخلی و...):"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۳: دریافت تخصص پزشک با اعتبارسنجی
        elif state["step"] == "WAIT_SPEC":
            if not text or len(text) < 2:
                send_message(chat_id, "⚠️ خطای ورودی! لطفاً تخصص پزشک را به صورت صحیح (مثلاً عمومی یا متخصص داخلی) تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["spec"] = text
            state["step"] = "WAIT_IMG"
            send_message(
                chat_id,
                f"✅ تخصص پزشک: **{text}** ثبت شد.\n\n"
                "📌 **مرحله ۴ از ۴:** اکنون لطفاً **تصویر واضح، خوانا و اسکن‌شده از نسخه یا پیش‌فاکتور** را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۴: دریافت تصویر و پردازش نهایی
        elif state["step"] == "WAIT_IMG":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif document and document.get("mime_type", "").startswith("image/"):
                file_id = document.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ لطفاً حتماً تصویر نسخه (عکس) را ارسال کنید.")
                return jsonify({"status": "ok"}), 200

            send_message(chat_id, "⏳ تصویر دریافت شد. در حال استخراج اقلام و بررسی بند به بند طبق ضوابط...")
            img_url = get_file_url(file_id)

            if not img_url:
                send_message(chat_id, "❌ دریافت فایل ممکن نشد. لطفاً مجدداً تصویر را ارسال کنید.")
                return jsonify({"status": "ok"}), 200

            # تحلیل با هوش مصنوعی
            result = analyze_prescription(img_url, state["pharmacy"], state["org"], state["spec"])
            send_message(chat_id, f"📋 **نتیجه ارزیابی نسخه:**\n\n{result}")

            # بازنشانی کامل وضعیت برای جلوگیری از تداخل در نسخه بعدی
            user_states[chat_id] = {"step": "WAIT_PHARMACY", "pharmacy": "", "org": "", "spec": ""}
            send_message(
                chat_id, 
                "✅ بررسی به پایان رسید.\n"
                "🔄 برای بررسی نسخه بعدی، کافی است مجدداً دستور /start را ارسال کنید."
            )
            return jsonify({"status": "ok"}), 200

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
