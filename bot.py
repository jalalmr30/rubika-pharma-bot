import os
import logging
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = os.environ.get("BALE_BOT_TOKEN", "1099104992:7WNzacPcBN11EOOAnHXDzGDN7-c-cUoWCY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ساختار مدیریت وضعیت هر کاربر: user_states[chat_id] = {"step": ..., "specialty": ...}
user_states = {}

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_message(chat_id, text):
    try:
        url = f"{BALE_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=15)
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

def analyze_prescription_with_gemini(image_url, specialty):
    try:
        if not GEMINI_API_KEY:
            return "❌ خطا: کلید هوش مصنوعی (GEMINI_API_KEY) تنظیم نشده است."

        img_resp = requests.get(image_url, timeout=30)
        if img_resp.status_code != 200:
            return "❌ خطا در بارگیری فایل تصویر از سرور بله."

        image_bytes = img_resp.content

        # ساخت پرامپت بدون کوتیشن سه‌تایی برای جلوگیری از خطای سینتکس
        system_instruction = (
            "تو یک کارشناس ارشد و ناظر تخصصی اسناد پزشکی و نسخ دارویی بیمه البرز هستی.\n"
            f"تخصص پزشک تجویزکننده: {specialty}\n\n"
            "دستورالعمل ارزیابی بند به بند تصویر نسخه/پیش‌فاکتور:\n"
            "۱. استخراج اقلام: تمام اقلام دارویی، اقلام مصرفی یا مکمل‌های موجود در تصویر را تک‌به‌تک و به صورت تفکیک‌شده با شماره بند بنویس.\n"
            "۲. ارزیابی تطابق تخصص پزشک: بررسی کن آیا هر یک از اقلام با تخصص پزشک همخوانی دارد؟ (برای پزشک عمومی، تجویز داروهای بسیار تخصصی ممنوع یا فاقد تعهد است مگر در موارد اورژانسی یا ادامه درمان تایید شده).\n"
            "۳. ارزیابی ضوابط بیمه البرز: مکمل‌ها و ویتامین‌ها (مولتی‌ویتامین، زینک، کلسیم، امگا۳ و...) طبق شیوه‌نامه فقط با تایید، سن خاص یا اندیکاسیون درمانی تعهد می‌شوند؛ داروهای خارجی و بهداشتی خارج از شمول هستند مگر طبق الحاقیه؛ دوز و مدت مصرف باید منطقی باشد.\n"
            "۴. جدول یا خروجی ساختاریافته به ازای هر بند:\n"
            "- نام قلم دارویی/کالا\n"
            "- وضعیت تعهد (قابل پرداخت / غیرقابل پرداخت / مشروط)\n"
            "- توضیحات و استناد قانونی بیمه البرز\n"
            "۵. جمع‌بندی نهایی به متصدی داروخانه.\n"
            "پاسخ باید دقیق، ساختاریافته، کاملاً فارسی و رسمی باشد."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        
        image_part = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }

        response = model.generate_content([system_instruction, image_part])
        return response.text if response and response.text else "⚠️ متنی از تصویر نسخه خوانده نشد. لطفاً از کیفیت و وضوح نسخه اطمینان حاصل کنید."

    except Exception as e:
        logger.error(f"Gemini analysis error: {e}")
        return f"❌ خطا در پردازش هوشمند: {str(e)}"

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "ok"})

        message = data.get("message", {})
        if not message:
            return jsonify({"status": "ok"})

        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return jsonify({"status": "ok"})

        text = message.get("text", "").strip()
        photo = message.get("photo")
        document = message.get("document")

        # ثبت وضعیت پیش‌فرض برای چت جدید
        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAITING_SPECIALTY", "specialty": ""}

        state = user_states[chat_id]

        # دستور شروع یا بازنشانی
        if text in ["/start", "شروع", "شروع مجدد", "restart"]:
            user_states[chat_id] = {"step": "WAITING_SPECIALTY", "specialty": ""}
            welcome_msg = (
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه ارزیابی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "لطفاً **تخصص پزشک تجویزکننده** را وارد نمایید (مثال: عمومی، داخلی، قلب و عروق، اطفال، زنان و...):"
            )
            send_message(chat_id, welcome_msg)
            return jsonify({"status": "ok"})

        # گام اول: دریافت تخصص پزشک
        if state["step"] == "WAITING_SPECIALTY":
            if not text:
                send_message(chat_id, "⚠️ لطفاً نام تخصص پزشک را تایپ و ارسال کنید:")
                return jsonify({"status": "ok"})

            state["specialty"] = text
            state["step"] = "WAITING_IMAGE"
            send_message(
                chat_id,
                f"✅ تخصص پزشک: **{text}** ثبت شد.\n\n"
                "📷 لطفاً اکنون **تصویر واضح، خوانا و اسکن‌شده از نسخه یا پیش‌فاکتور** را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"})

        # گام دوم: دریافت تصویر نسخه و ارزیابی
        elif state["step"] == "WAITING_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif document and document.get("mime_type", "").startswith("image/"):
                file_id = document.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ فایل ارسالی تصویر نیست. لطفاً تصویر نسخه را ارسال فرمایید:")
                return jsonify({"status": "ok"})

            send_message(chat_id, "⏳ تصویر دریافت شد. در حال استخراج اقلام نسخه و ارزیابی بند به بند طبق ضوابط بیمه البرز...")

            image_url = get_file_url(file_id)
            if not image_url:
                send_message(chat_id, "❌ دریافت تصویر از سرور با خطا مواجه شد. لطفاً مجدداً ارسال کنید.")
                return jsonify({"status": "ok"})

            # پردازش با جمینی
            result = analyze_prescription_with_gemini(image_url, state["specialty"])
            
            # ارسال گزارش بند به بند
            send_message(chat_id, f"📋 **نتیجه بررسی و رسیدگی نسخه:**\n\n{result}")

            # پاک‌سازی کامل وضعیت برای نسخه بعدی (بدون تداخل با نسخه قبل)
            user_states[chat_id] = {"step": "WAITING_SPECIALTY", "specialty": ""}
            send_message(
                chat_id,
                "✅ بررسی این نسخه به پایان رسید.\n"
                "🔄 برای ارزیابی نسخه بعدی، لطفاً مجدداً **تخصص پزشک نسخه جدید** را ارسال کنید."
            )
            return jsonify({"status": "ok"})

        else:
            user_states[chat_id] = {"step": "WAITING_SPECIALTY", "specialty": ""}
            send_message(chat_id, "لطفاً ابتدا **تخصص پزشک تجویزکننده** را وارد نمایید:")
            return jsonify({"status": "ok"})

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
