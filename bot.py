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
    """ارسال پیام با تقسیم هوشمند متن برای جلوگیری از محدودیت بله"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        max_len = 1800
        for i in range(0, len(text), max_len):
            chunk = text[i:i + max_len]
            requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=15)
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def get_bale_file_bytes(file_id):
    """دریافت امن بایت‌های تصویر نسخه از سرور بله"""
    try:
        url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=20).json()
        if not resp.get("ok"):
            logger.error(f"getFile error response: {resp}")
            return None

        file_path = resp.get("result", {}).get("file_path")
        if not file_path:
            return None

        dl_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        dl_resp = requests.get(dl_url, timeout=35)
        if dl_resp.status_code == 200:
            return dl_resp.content
        else:
            logger.error(f"Download HTTP status: {dl_resp.status_code}")
    except Exception as e:
        logger.error(f"Download file exception: {e}")
    return None

def analyze_prescription(chat_id, file_id, pharmacy, org, doc_type, specialty):
    """تحلیل دقیق نسخه توسط هوش مصنوعی و ارسال خروجی به متصدی داروخانه"""
    try:
        if not GEMINI_API_KEY:
            send_message(chat_id, "❌ خطا: کلید هوش مصنوعی در سرور فعال نشده است.")
            return

        send_message(chat_id, "⏳ تصویر در حال پردازش توسط هوش مصنوعی است، لطفاً چند لحظه صبر کنید...")
        
        img_bytes = get_bale_file_bytes(file_id)
        if not img_bytes:
            send_message(chat_id, "❌ دریافت تصویر نسخه از سرور بله ناموفق بود. لطفاً عکس را با حجم کمتر یا به صورت فایل ارسال فرمایید.")
            return

        doc_info = f"پزشک عمومی" if doc_type == "general" else f"پزشک متخصص ({specialty})"

        prompt = f"""
تو ممیز و کارشناس ارشد اسناد دارویی بیمه البرز هستی.
اطلاعات ثبت‌شده توسط متصدی داروخانه:
- نام داروخانه: {pharmacy}
- سازمان طرف قرارداد: {org}
- وضعیت پزشک تجویزکننده: {doc_info}

لطفاً تصویر پیش‌فاکتور/نسخه را با دقت بالا تحلیل کرده و گزارش زیر را ارائه ده:
۱. استخراج اقلام: نام تک‌به‌تک داروها، دوز، تعداد و مبلغ هر قلم را شماره‌گذاری و فهرست کن.
۲. انطباق تخصص: بررسی کن آیا داروها با تخصص پزشک ({doc_info}) همخوانی دارند یا خیر.
۳. تطبیق با ضوابط سازمان '{org}' و بیمه البرز: بررسی سقف پرداخت مکمل‌ها، ویتامین‌ها، داروهای خارجی/برند، و حق فنی.
۴. تعیین وضعیت برای هر قلم: [قابل پرداخت]، [غیرقابل پرداخت]، یا [کسورات احتمالی / نیاز به تایید].
۵. جمع‌بندی مالی: جمع کل سهم سازمان و بیمار.

پاسخ را با لحن اداری، ساختاریافته و کاملاً خوانا ارسال کن.
"""

        model = genai.GenerativeModel("gemini-1.5-flash")
        image_part = {"mime_type": "image/jpeg", "data": img_bytes}

        response = model.generate_content([prompt, image_part])

        if response and response.text:
            header = f"📋 گزارش کارشناسی اسناد دارویی بیمه البرز\n🏥 داروخانه: {pharmacy}\n🏢 سازمان: {org}\n🩺 پزشک: {doc_info}\n━━━━━━━━━━━━━━━━━━\n"
            send_message(chat_id, header + response.text)
        else:
            send_message(chat_id, "⚠️ متن یا ارقامی از تصویر خوانده نشد. لطفاً عکس واضح‌تر و بدون زاویه ارسال فرمایید.")

    except Exception as e:
        logger.error(f"Analysis error: {e}")
        send_message(chat_id, f"❌ خطای پردازش هوش مصنوعی: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY"}
        send_message(chat_id, "✅ بررسی این پرونده به پایان رسید.\n🔄 برای بررسی نسخه بعدی، دستور /start را ارسال کنید.")

@app.route("/", methods=["GET"])
def index():
    return "Pharma Assessment Bot is Online.", 200

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data or "message" not in data:
            return jsonify({"status": "ignored"}), 200

        msg = data["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        photo = msg.get("photo")
        doc = msg.get("document")

        if not chat_id:
            return jsonify({"status": "no chat_id"}), 200

        # دستور شروع
        if text in ["/start", "شروع", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه بررسی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۵: لطفاً «نام داروخانه» را وارد فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_message(
                chat_id,
                "سلام متصدی محترم داروخانه؛ لطفاً جهت شروع، «نام داروخانه» را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]
        step = state.get("step")

        # گام ۱: نام داروخانه
        if step == "WAIT_PHARMACY":
            if not text:
                send_message(chat_id, "⚠️ لطفاً نام داروخانه را تایپ کنید:")
                return jsonify({"status": "ok"}), 200
            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_message(
                chat_id,
                f"✅ داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۵: نام سازمان بیمه‌شده / ارگان متبوع را وارد فرمایید\n"
                "(مثال: بانک توسعه تعاون، جهاد کشاورزی، شرکت نفتکش و...):"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۲: نام سازمان
        elif step == "WAIT_ORG":
            if not text:
                send_message(chat_id, "⚠️ لطفاً نام سازمان را وارد فرمایید:")
                return jsonify({"status": "ok"}), 200
            state["org"] = text
            state["step"] = "WAIT_DOC_TYPE"
            send_message(
                chat_id,
                f"✅ سازمان: {text}\n\n"
                "📌 مرحله ۳ از ۵: نوع پزشک تجویزکننده را مشخص کنید:\n"
                "۱. عمومی\n"
                "۲. متخصص\n\n"
                "لطفاً عدد (1 یا 2) یا کلمه «عمومی» / «متخصص» را بفرستید:"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۳: رده پزشک
        elif step == "WAIT_DOC_TYPE":
            if text in ["1", "عمومی", "پزشک عمومی"]:
                state["doc_type"] = "general"
                state["specialty"] = "عمومی"
                state["step"] = "WAIT_IMAGE"
                send_message(
                    chat_id,
                    "✅ رده پزشک: عمومی\n\n"
                    "📌 مرحله نهایی: اکنون تصویر واضح نسخه یا پیش‌فاکتور را ارسال فرمایید:"
                )
            elif text in ["2", "متخصص", "پزشک متخصص"]:
                state["doc_type"] = "specialist"
                state["step"] = "WAIT_SPECIALTY_NAME"
                send_message(
                    chat_id,
                    "✅ رده پزشک: متخصص\n\n"
                    "📌 مرحله ۴ از ۵: لطفاً عنوان دقیق «تخصص پزشک» را بنویسید\n"
                    "(مثال: مغز و اعصاب، قلب و عروق، داخلی، ارتوپد و...):"
                )
            else:
                send_message(chat_id, "⚠️ لطفاً مشخص کنید پزشک عمومی است یا متخصص (ارسال عدد 1 یا 2):")
            return jsonify({"status": "ok"}), 200

        # گام ۴: تخصص پزشک
        elif step == "WAIT_SPECIALTY_NAME":
            if not text:
                send_message(chat_id, "⚠️ لطفاً عنوان تخصص را وارد فرمایید:")
                return jsonify({"status": "ok"}), 200
            state["specialty"] = text
            state["step"] = "WAIT_IMAGE"
            send_message(
                chat_id,
                f"✅ تخصص ثبت شد: {text}\n\n"
                "📌 مرحله نهایی: اکنون تصویر واضح نسخه یا پیش‌فاکتور را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # گام نهایی: تصویر
        elif step == "WAIT_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif doc and doc.get("mime_type", "").startswith("image/"):
                file_id = doc.get("file_id")

            if not file_id:
                send_message(chat_id, "⚠️ لطفاً فایل را حتماً به صورت عکس یا تصویر نسخه ارسال کنید.")
                return jsonify({"status": "ok"}), 200

            # اجرا در Thread مستقل
            t = threading.Thread(
                target=analyze_prescription,
                args=(
                    chat_id,
                    file_id,
                    state.get("pharmacy", "نامشخص"),
                    state.get("org", "عمومی"),
                    state.get("doc_type", "general"),
                    state.get("specialty", "عمومی")
                )
            )
            t.start()
            return jsonify({"status": "ok"}), 200

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Global webhook error: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
