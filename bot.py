import os
import logging
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# توکن ثابت و دقیق شما
TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Gemini config error: {e}")

# دیکشنری نگهداری وضعیت کاربر
user_states = {}

BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_message(chat_id, text):
    try:
        url = f"{BALE_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        res = requests.post(url, json=payload, timeout=10)
        logger.info(f"Send message status: {res.status_code}")
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

def analyze_prescription(image_url, specialty):
    try:
        if not GEMINI_API_KEY:
            return "❌ خطا: کلید هوش مصنوعی (GEMINI_API_KEY) تنظیم نشده است."

        img_resp = requests.get(image_url, timeout=30)
        if img_resp.status_code != 200:
            return "❌ خطا در دریافت تصویر از سرور."

        image_bytes = img_resp.content

        prompt = (
            f"نقش: کارشناس ارشد رسیدگی به اسناد پزشکی و نسخ دارویی بیمه البرز.\n"
            f"تخصص پزشک تجویزکننده: {specialty}\n\n"
            f"دستورالعمل:\n"
            f"۱. اقلام نسخه یا فاکتور را خط به خط و تفکیک‌شده استخراج کن.\n"
            f"۲. تطابق داروها با تخصص پزشک ({specialty}) را بررسی کن.\n"
            f"۳. قوانین بیمه البرز (مکمل‌ها، ویتامین‌ها، داروهای برند و غیربیمه‌ای) را روی اقلام اعمال کن.\n"
            f"۴. به ازای هر قلم: وضعیت (تایید / نیازمند مدارک / غیرقابل پرداخت) و علت را ذکر کن.\n"
            f"۵. نظر نهایی را خلاصه بنویس."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        response = model.generate_content([prompt, image_part])
        return response.text if response and response.text else "متنی از نسخه استخراج نشد."

    except Exception as e:
        logger.error(f"AI Error: {e}")
        return f"خطا در پردازش تصویر: {e}"

# هم مسیر با توکن و هم بدون توکن تعریف شده تا هیچ درخواستی رد نشود
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

        # کاربر جدید
        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_SPEC", "spec": ""}

        state = user_states[chat_id]

        # دستورات شروع مجدد
        if text in ["/start", "شروع", "شروع مجدد", "restart"]:
            user_states[chat_id] = {"step": "WAIT_SPEC", "spec": ""}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "لطفاً **تخصص پزشک تجویزکننده** را وارد نمایید (مثال: عمومی، قلب و عروق، اطفال، داخلی و...):"
            )
            return jsonify({"status": "ok"}), 200

        # مرحله اول: گرفتن تخصص
        if state["step"] == "WAIT_SPEC":
            if not text:
                send_message(chat_id, "لطفاً تخصص پزشک را تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["spec"] = text
            state["step"] = "WAIT_IMG"
            send_message(
                chat_id,
                f"✅ تخصص پزشک: **{text}** ثبت شد.\n\n"
                "اکنون لطفاً **تصویر باکیفیت و واضح نسخه یا فاکتور** را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # مرحله دوم: گرفتن عکس و پردازش
        elif state["step"] == "WAIT_IMG":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif document and document.get("mime_type", "").startswith("image/"):
                file_id = document.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ لطفاً یک تصویر (عکس نسخه) ارسال کنید.")
                return jsonify({"status": "ok"}), 200

            send_message(chat_id, "⏳ تصویر دریافت شد. در حال استخراج و بررسی بند به بند طبق ضوابط...")
            img_url = get_file_url(file_id)

            if not img_url:
                send_message(chat_id, "❌ دریافت فایل ممکن نشد. لطفاً مجدد تلاش کنید.")
                return jsonify({"status": "ok"}), 200

            result = analyze_prescription(img_url, state["spec"])
            send_message(chat_id, f"📋 **نتیجه ارزیابی:**\n\n{result}")

            # بازنشانی برای نسخه بعدی
            user_states[chat_id] = {"step": "WAIT_SPEC", "spec": ""}
            send_message(chat_id, "🔄 بررسی پایان یافت. برای نسخه بعدی، مجدداً **تخصص پزشک** را وارد کنید.")
            return jsonify({"status": "ok"}), 200

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
