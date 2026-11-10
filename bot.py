import os
import io
import time
import base64
import logging
import threading
import requests
from flask import Flask, request, jsonify
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

user_states = {}
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_bale_msg(chat_id, text):
    """ارسال متن بدون شکستگی در پیام‌رسان بله"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        max_chunk = 1500
        for i in range(0, len(text), max_chunk):
            sub_text = text[i:i + max_chunk]
            requests.post(url, json={"chat_id": chat_id, "text": sub_text}, timeout=15)
            time.sleep(0.3)
    except Exception as e:
        logger.error(f"Error sending message to Bale: {e}")

def get_file_content(file_id):
    """دانلود باینری عکس نسخه از بله"""
    try:
        info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        res = requests.get(info_url, timeout=20).json()
        if not res.get("ok"):
            logger.error(f"getFile returned not ok: {res}")
            return None

        file_path = res.get("result", {}).get("file_path")
        if not file_path:
            return None

        dl_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        r = requests.get(dl_url, timeout=40)
        if r.status_code == 200:
            return r.content
        else:
            logger.error(f"Download error HTTP: {r.status_code}")
    except Exception as e:
        logger.error(f"Exception while downloading file: {e}")
    return None

def call_gemini_vision_rest(image_bytes, prompt_text):
    """فراخوانی مستقیم و پایدار REST API گوگل جمینای بدون خطای gRPC یا Illegal Metadata"""
    if not GEMINI_API_KEY:
        raise ValueError("متغیر GEMINI_API_KEY روی سرور Render ست نشده است.")

    # تبدیل تصویر به JPEG و بهینه‌سازی حجم
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    
    # فشرده‌سازی کنترل‌شده برای سرعت حداکثری
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    base64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048
        }
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(api_url, headers=headers, json=payload, timeout=60)
    
    if response.status_code != 200:
        logger.error(f"Gemini API returned status {response.status_code}: {response.text}")
        raise RuntimeError(f"خطای API گوگل (کد {response.status_code})")

    res_json = response.json()
    candidates = res_json.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")
    
    return "متنی از تحلیل تصویر تولید نشد."

def process_prescription_ai(chat_id, file_id, pharmacy, org, doc_type, specialty):
    """پردازش ارزیابی اسناد نسخه داروخانه"""
    try:
        send_bale_msg(chat_id, "🔍 تصویر دریافت شد. در حال استخراج اقلام نسخه و تطبیق با ضوابط بیمه البرز...")

        img_raw = get_file_content(file_id)
        if not img_raw:
            send_bale_msg(chat_id, "❌ دریافت فایل از سرور بله ناموفق بود. لطفاً عکس را دوباره ارسال کنید.")
            return

        doc_title = "پزشک عمومی" if doc_type == "general" else f"متخصص ({specialty})"

        prompt = f"""
شما کارشناس ممیزی و ارزیاب ارشد اسناد دارویی بیمه البرز هستید.
اطلاعات اعلامی داروخانه:
- داروخانه: {pharmacy}
- سازمان/ارگان متبوع بیمه‌شده: {org}
- پزشک تجویزکننده: {doc_title}

دستورالعمل ارزیابی نسخه/فاکتور بر اساس شیوه‌نامه‌های دارویی بیمه البرز و ضوابط اختصاصی سازمان '{org}':

۱. استخراج و تفکیک تک‌تک اقلام:
تمامی اقلام، داروها، خدمات دارویی (تعرفه حق فنی)، سرنگ، پد الکلی و ملزومات را همراه با تعداد، دوز، مبلغ آزاد، سهم سازمان و سهم بیمار شماره‌گذاری کرده و بنویسید.

۲. ارزیابی انطباق تخصص پزشک ({doc_title}):
آیا اقلام در حوزه صلاحیت علمی و قانونی این پزشک است؟ برای داروهای تخصصی خارج از حیطه، اعلام نظر کنید.

۳. اعمال ضوابط سازمان '{org}' و بیمه البرز:
- مکمل‌ها و ویتامین‌ها: تعیین تکلیف بر اساس شیوه‌نامه (سقف تعهد، غیرقابل پرداخت، یا نیاز به تاییدیه).
- داروهای خارجی/برند: تعهد تا سقف قیمت ژنریک ایرانی یا عدم تعهد.
- خدمات دارویی (حق فنی) و لوازم مصرفی (سرنگ و...).

۴. وضعیت نهایی هر قلم:
روبروی هر قلم درج کنید: [قابل تایید]، [کسورات قطعی به همراه دلیل] یا [نیاز به مدارک تکمیلی].

۵. خلاصه مبالغ:
- جمع کل سهم سازمان قابل پرداخت
- جمع سهم بیمار
- مبلغ کل کسورات

پاسخ را کاملاً مرتب، اداری و به دور از کاراکترهای نامتعارف ارسال فرمایید.
"""

        result_text = call_gemini_vision_rest(img_raw, prompt)

        header = (
            f"📋 نتیجه ارزیابی هوشمند نسخه (بیمه البرز)\n"
            f"🏥 داروخانه: {pharmacy}\n"
            f"🏢 سازمان: {org}\n"
            f"🩺 پزشک: {doc_title}\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
        send_bale_msg(chat_id, header + result_text)

    except Exception as e:
        logger.error(f"Prescription processing error: {e}")
        send_bale_msg(chat_id, f"❌ خطای ارزیابی هوش مصنوعی: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY"}
        send_bale_msg(chat_id, "🏁 پرونده ارزیابی پایان یافت.\n🔄 برای بررسی نسخه جدید، دستور /start را ارسال فرمایید.")

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

        # گام ۱: دریافت نام داروخانه (حداقل ۳ حرف)
        if step == "WAIT_PHARMACY":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ نام داروخانه نمی‌تواند حروف ناقص باشد. لطفاً نام کامل داروخانه را وارد کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_bale_msg(
                chat_id,
                f"✅ داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۵: لطفاً «نام سازمان یا ارگان متبوع بیمه‌شده» را تایپ فرمایید:\n"
                "(مانند: بانک توسعه تعاون، جهاد کشاورزی، شرکت ملی نفتکش، بازرگانی دولتی، مپنا، بنیاد مسکن، ایمیدرو، صنعت و معدن و سایر ارگان‌ها):"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۲: دریافت نام سازمان (کاملاً تایپی و بر اساس مراجع)
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

        # گام ۳: رده پزشک
        elif step == "WAIT_DOC_TYPE":
            if text in ["1", "عمومی", "پزشک عمومی"]:
                state["doc_type"] = "general"
                state["specialty"] = "پزشک عمومی"
                state["step"] = "WAIT_IMAGE"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: پزشک عمومی\n\n"
                    "📌 مرحله نهایی: اکنون تصویر واضح نسخه یا پیش‌فاکتور را ارسال فرمایید:"
                )
            elif text in ["2", "متخصص", "پزشک متخصص"]:
                state["doc_type"] = "specialist"
                state["step"] = "WAIT_SPEC"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: متخصص\n\n"
                    "📌 مرحله ۴ از ۵: لطفاً عنوان دقیق «تخصص پزشک» را بنویسید:\n"
                    "(مثال: متخصص مغز و اعصاب، داخلی، قلب و عروق، ارتوپد، پوست و...):"
                )
            else:
                send_bale_msg(chat_id, "⚠️ لطفاً مشخص کنید: عدد ۱ (عمومی) یا ۲ (متخصص):")
            return jsonify({"status": "ok"}), 200

        # گام ۴: تخصص پزشک
        elif step == "WAIT_SPEC":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ لطفاً عنوان تخصص را کامل بنویسید:")
                return jsonify({"status": "ok"}), 200

            state["specialty"] = text
            state["step"] = "WAIT_IMAGE"
            send_bale_msg(
                chat_id,
                f"✅ تخصص ثبت شد: {text}\n\n"
                "📌 مرحله نهایی: اکنون تصویر واضح نسخه یا پیش‌فاکتور را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۵: دریافت تصویر
        elif step == "WAIT_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif doc and doc.get("mime_type", "").startswith("image/"):
                file_id = doc.get("file_id")

            if not file_id:
                send_bale_msg(chat_id, "⚠️ لطفاً سند را به عنوان عکس یا پیش‌فاکتور تصویری ارسال فرمایید.")
                return jsonify({"status": "ok"}), 200

            t = threading.Thread(
                target=process_prescription_ai,
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
