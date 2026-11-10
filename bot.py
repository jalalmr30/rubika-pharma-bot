import os
import time
import base64
import logging
import threading
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

user_states = {}
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_bale_msg(chat_id, text):
    """ارسال متن بدون قطع شدن با بخش‌بندی استاندارد"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        max_chunk = 1400
        for i in range(0, len(text), max_chunk):
            sub_text = text[i:i + max_chunk]
            requests.post(url, json={"chat_id": chat_id, "text": sub_text}, timeout=15)
            time.sleep(0.2)
    except Exception as e:
        logger.error(f"Error sending message to Bale: {e}")

def get_file_bytes(file_id):
    """دریافت فایل از سرور بله"""
    try:
        info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        res = requests.get(info_url, timeout=20).json()
        if not res.get("ok"):
            logger.error(f"getFile failed: {res}")
            return None

        file_path = res.get("result", {}).get("file_path")
        if not file_path:
            return None

        dl_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        r = requests.get(dl_url, timeout=30)
        if r.status_code == 200:
            return r.content
        else:
            logger.error(f"Download HTTP status: {r.status_code}")
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
    return None

def analyze_with_gemini_pure(image_bytes, prompt_text):
    """ارسال بایت‌های تصویر مستقیماً از طریق REST API گوگل بدون نیاز به PIL یا کتابخانه‌های سنگین"""
    if not GEMINI_API_KEY:
        raise ValueError("متغیر GEMINI_API_KEY روی سرور Render ثبت نشده است.")

    # تبدیل مستقیم بایت‌ها به رشته Base64 استاندارد
    base64_img = base64.b64encode(image_bytes).decode("utf-8")

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64_img
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048
        }
    }

    headers = {"Content-Type": "application/json"}
    resp = requests.post(api_url, headers=headers, json=payload, timeout=60)

    if resp.status_code != 200:
        logger.error(f"Gemini error {resp.status_code}: {resp.text}")
        raise RuntimeError(f"خطای وب‌سرویس گوگل (کد {resp.status_code})")

    data = resp.json()
    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")

    return "تحلیلی از تصویر به دست نیامد."

def process_prescription_worker(chat_id, file_id, pharmacy, org, doc_type, specialty):
    """پردازش ارزیابی نسخه در پس‌زمینه"""
    try:
        send_bale_msg(chat_id, "⚡ تصویر دریافت شد. در حال استخراج اقلام نسخه و تطبیق با ضوابط بیمه البرز...")

        raw_bytes = get_file_bytes(file_id)
        if not raw_bytes:
            send_bale_msg(chat_id, "❌ خطا در دریافت فایل از سرور بله. لطفاً مجدداً تلاش فرمایید.")
            return

        doc_title = "پزشک عمومی" if doc_type == "general" else f"متخصص ({specialty})"

        prompt = f"""
نقش شما: ممیز و ارزیاب ارشد اسناد دارویی بیمه البرز.
اطلاعات اعلامی داروخانه طرف قرارداد:
- نام داروخانه: {pharmacy}
- نام سازمان / ارگان بیمه‌شده: {org}
- رده پزشک تجویزکننده: {doc_title}

دستورالعمل جامع ارزیابی:
۱. استخراج دقیق کلیه اقلام:
تمامی اقلام شامل داروها، خدمات دارویی (حق فنی)، سرنگ، پد الکلی و ملزومات را با تعداد، دوز، مبلغ آزاد، سهم سازمان و سهم بیمار شماره‌گذاری کرده و فهرست نمایید.

۲. تطبیق با حیطه صلاحیت پزشک ({doc_title}):
مشخص فرمایید آیا داروها با تخصص پزشک انطباق دارند یا خیر و داروهای خارج از تخصص را مشخص کنید.

۳. اعمال ضوابط اختصاصی سازمان '{org}' و بیمه البرز:
- وضعیت پوشش مکمل‌ها، ویتامین‌ها و تقویتی‌ها بر اساس شیوه‌نامه سازمان.
- وضعیت داروهای خارجی / برند نسبت به معادل ژنریک ایرانی.
- وضعیت خدمات دارویی (تعرفه حق فنی) و لوازم مصرفی (سرنگ و...).

۴. وضعیت نهایی هر قلم:
روبروی هر قلم به تفکیک بنویسید: [قابل پرداخت]، [کسورات قطعی به همراه دلیل] یا [نیاز به مدارک/تاییدیه].

۵. خلاصه مبالغ:
- جمع کل سهم سازمان قابل تایید
- جمع کل سهم بیمار
- مبلغ کسورات نهایی
"""

        analysis_result = analyze_with_gemini_pure(raw_bytes, prompt)

        header = (
            f"📋 نتیجه کارشناسی نسخه (بیمه البرز)\n"
            f"🏥 داروخانه: {pharmacy}\n"
            f"🏢 سازمان: {org}\n"
            f"🩺 پزشک: {doc_title}\n"
            f"────────────────────\n\n"
        )
        send_bale_msg(chat_id, header + analysis_result)

    except Exception as e:
        logger.error(f"Worker error: {e}")
        send_bale_msg(chat_id, f"❌ خطا در پردازش نسخه: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY"}
        send_bale_msg(chat_id, "🏁 پایان ارزیابی این پرونده.\n🔄 جهت بررسی نسخه بعدی، /start را ارسال فرمایید.")

@app.route("/", methods=["GET"])
def health():
    return "Pharma Bot Server Running", 200

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

        # شروع / ریست
        if text in ["/start", "شروع", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_bale_msg(
                chat_id,
                "سلام همکار گرامی، متصدی محترم داروخانه؛\n"
                "به سامانه ممیزی و ارزیابی آنلاین اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۵: لطفاً «نام کامل داروخانه» را وارد فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_bale_msg(
                chat_id,
                "سلام متصدی محترم داروخانه؛ لطفاً جهت شروع ارزیابی، «نام داروخانه» را وارد فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]
        step = state.get("step")

        # مرحله ۱: داروخانه
        if step == "WAIT_PHARMACY":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ نام داروخانه نمی‌تواند حروف ناقص باشد. لطفاً نام داروخانه را تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_bale_msg(
                chat_id,
                f"✅ داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۵: لطفاً «نام سازمان یا ارگان متبوع بیمه‌شده» را وارد نمایید:\n"
                "(مانند: بانک توسعه تعاون، جهاد کشاورزی، شرکت ملی نفتکش، بازرگانی دولتی، مپنا، بنیاد مسکن، ایمیدرو، صنعت و معدن یا سایر ارگان‌ها):"
            )
            return jsonify({"status": "ok"}), 200

        # مرحله ۲: سازمان
        elif step == "WAIT_ORG":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ لطفاً نام سازمان را کامل وارد فرمایید (حداقل ۳ حرف):")
                return jsonify({"status": "ok"}), 200

            state["org"] = text
            state["step"] = "WAIT_DOC_TYPE"
            send_bale_msg(
                chat_id,
                f"✅ سازمان ثبت شد: {text}\n\n"
                "📌 مرحله ۳ از ۵: رده پزشک تجویزکننده را مشخص فرمایید:\n"
                "۱. پزشک عمومی\n"
                "۲. پزشک متخصص\n\n"
                "لطفاً عدد (1 یا 2) یا عنوان «عمومی» / «متخصص» را ارسال نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # مرحله ۳: نوع پزشک
        elif step == "WAIT_DOC_TYPE":
            if text in ["1", "عمومی", "پزشک عمومی"]:
                state["doc_type"] = "general"
                state["specialty"] = "پزشک عمومی"
                state["step"] = "WAIT_IMAGE"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: پزشک عمومی\n\n"
                    "📌 مرحله نهایی: لطفاً تصویر واضح، بدون زاویه و خوانا از «پیش‌فاکتور یا نسخه» را ارسال فرمایید:"
                )
            elif text in ["2", "متخصص", "پزشک متخصص"]:
                state["doc_type"] = "specialist"
                state["step"] = "WAIT_SPEC"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: متخصص\n\n"
                    "📌 مرحله ۴ از ۵: عنوان دقیق «تخصص پزشک» را بنویسید:\n"
                    "(مثال: متخصص مغز و اعصاب، قلب و عروق، داخلی، ارتوپدی و...):"
                )
            else:
                send_bale_msg(chat_id, "⚠️ لطفاً مشخص کنید: عدد ۱ (عمومی) یا ۲ (متخصص):")
            return jsonify({"status": "ok"}), 200

        # مرحله ۴: تخصص
        elif step == "WAIT_SPEC":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ لطفاً عنوان تخصص را کامل وارد فرمایید:")
                return jsonify({"status": "ok"}), 200

            state["specialty"] = text
            state["step"] = "WAIT_IMAGE"
            send_bale_msg(
                chat_id,
                f"✅ تخصص ثبت شد: {text}\n\n"
                "📌 مرحله نهایی: اکنون تصویر واضح نسخه یا پیش‌فاکتور را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # مرحله ۵: دریافت تصویر
        elif step == "WAIT_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif doc and doc.get("mime_type", "").startswith("image/"):
                file_id = doc.get("file_id")

            if not file_id:
                send_bale_msg(chat_id, "⚠️ لطفاً سند را به صورت عکس ارسال فرمایید.")
                return jsonify({"status": "ok"}), 200

            t = threading.Thread(
                target=process_prescription_worker,
                args=(
                    chat_id,
                    file_id,
                    state.get("pharmacy"),
                    state.get("org"),
                    state.get("doc_type"),
                    state.get("specialty")
                )
            )
            t.start()
            return jsonify({"status": "ok"}), 200

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Global webhook exception: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
