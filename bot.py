import os
import io
import time
import logging
import threading
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Google Gemini API successfully configured.")
    except Exception as e:
        logger.error(f"Gemini configuration error: {e}")

user_states = {}
BALE_API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def send_bale_msg(chat_id, text):
    """ارسال متن بدون شکستگی با برش بخش‌های طولانی"""
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
    """دانلود باینری فایل تصویر از سرور بله"""
    try:
        info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        res = requests.get(info_url, timeout=20).json()
        if not res.get("ok"):
            logger.error(f"getFile returned not ok: {res}")
            return None

        file_path = res["result"].get("file_path")
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

def process_prescription_ai(chat_id, file_id, pharmacy, org, doc_type, specialty):
    """پردازش تصویر نسخه با هندلینگ قطعی خطای متادیتا و تایم‌اوت"""
    try:
        if not GEMINI_API_KEY:
            send_bale_msg(chat_id, "❌ خطا: متغیر GEMINI_API_KEY روی سرور تنظیم نشده است.")
            return

        send_bale_msg(chat_id, "🔍 تصویر دریافت شد. در حال استخراج اقلام و انطباق با شیوه‌نامه بیمه البرز...")

        img_raw = get_file_content(file_id)
        if not img_raw:
            send_bale_msg(chat_id, "❌ خطا در دریافت فایل از بله. لطفاً عکس واضح را مجدداً ارسال کنید.")
            return

        # تبدیل باینری به شیء تصویر PIL جهت جلوگیری از ارور 503 Illegal metadata
        try:
            image_obj = Image.open(io.BytesIO(img_raw))
            if image_obj.mode != "RGB":
                image_obj = image_obj.convert("RGB")
        except Exception as img_err:
            logger.error(f"PIL Image conversion error: {img_err}")
            send_bale_msg(chat_id, "❌ فرمت تصویر ارسالی نامعتبر است. لطفاً فایل تصویری مناسب (JPG یا PNG) بفرستید.")
            return

        doc_title = "پزشک عمومی" if doc_type == "general" else f"متخصص ({specialty})"

        prompt = f"""
نقش شما: کارشناس ممیزی و ارزیاب ارشد اسناد دارویی بیمه البرز.
اطلاعات اعلامی داروخانه:
- داروخانه طرف قرارداد: {pharmacy}
- ارگان / سازمان بیمه‌شده: {org}
- پزشک تجویزکننده: {doc_title}

شرح وظایف ارزیابی:
۱. استخراج دقیق اقلام نسخه:
تصویر فاکتور را بخوانید و تک‌تک اقلام، داروها، خدمات دارویی (حق فنی)، سرنگ و سایر لوازم مصرفی را همراه با تعداد، دوز، مبلغ پرداختی بیمار و سهم سازمان شماره‌گذاری کرده و فهرست کنید.

۲. ارزیابی انطباق صلاحیت تجویز با تخصص پزشک ({doc_title}):
مشخص کنید آیا هر یک از اقلام در حیطه تخصصی پزشک صادرکننده نسخه هست یا خیر. داروهایی که نیاز به تایید متخصص مشخصی دارند را علامت‌گذاری کنید.

۳. تطبیق با ضوابط سازمان '{org}' و آیین‌نامه‌های دارویی بیمه البرز:
- وضعیت پوشش مکمل‌ها و ویتامین‌ها (سقف تعهد، نیاز به پرونده یا عدم پرداخت).
- وضعیت پوشش داروهای خارجی / برند در برابر معادل ایرانی.
- وضعیت خدمات دارویی (تعرفه حق فنی) و ملزومات جانبی (مانند سرنگ، پد الکلی).

۴. جدول ارزیابی هر قلم:
برای هر قلم وضعیت [تایید و قابل پرداخت]، [غیرقابل پرداخت به همراه دلیل ممیزی]، یا [مشروط به تایید پزشک معتمد بیمه] را مشخص کنید.

۵. جمع‌بندی مالی:
مبلغ کل قابل تایید سهم سازمان، سهم بیمه‌شده و جمع کسورات احتمالی را درج نمایید.

پاسخ را کاملاً مرتب، اداری و به دور از کاراکترهای به هم ریخته تنظیم کنید.
"""

        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # فراخوانی ایمن با شیء استاندارد PIL
        response = model.generate_content(
            [prompt, image_obj],
            request_options={"timeout": 90}
        )

        if response and response.text:
            header = (
                f"📋 گزارش ارزیابی هوشمند نسخه (بیمه البرز)\n"
                f"🏥 داروخانه: {pharmacy}\n"
                f"🏢 سازمان: {org}\n"
                f"🩺 پزشک: {doc_title}\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
            )
            send_bale_msg(chat_id, header + response.text)
        else:
            send_bale_msg(chat_id, "⚠️ هیچ متنی از تصویر خوانده نشد. لطفاً عکس باکیفیت و از فاصله نزدیک‌تر ارسال فرمایید.")

    except Exception as e:
        logger.error(f"Prescription processing error: {e}")
        send_bale_msg(chat_id, f"❌ خطای تحلیل هوش مصنوعی: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY"}
        send_bale_msg(chat_id, "🏁 پایان بررسی این نسخه.\n🔄 برای بررسی نسخه بعدی، /start را بفرستید.")

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

        # شروع مجدد
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
                "سلام متصدی محترم؛ لطفاً جهت شروع بررسی، «نام داروخانه» را بنویسید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]
        step = state.get("step")

        # گام ۱: دریافت نام داروخانه
        if step == "WAIT_PHARMACY":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ لطفاً نام داروخانه را کامل بنویسید (حداقل ۳ حرف):")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"
            send_bale_msg(
                chat_id,
                f"✅ داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۵: لطفاً «نام سازمان یا ارگان متبوع بیمه‌شده» را تایپ فرمایید:\n"
                "(مانند: بانک توسعه تعاون، جهاد کشاورزی، شرکت ملی نفتکش، بازرگانی دولتی، مپنا، بنیاد مسکن، ایمیدرو، صنعت و معدن یا سایر ارگان‌ها):"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۲: دریافت نام سازمان (کاملاً آزاد و تایپی)
        elif step == "WAIT_ORG":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ نام سازمان نمی‌تواند حروف ناقص باشد. لطفاً نام سازمان را کامل بنویسید:")
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
                    "📌 مرحله نهایی: لطفاً تصویر واضح، بدون زاویه و خوانا از «پیش‌فاکتور یا نسخه» را ارسال فرمایید:"
                )
            elif text in ["2", "متخصص", "پزشک متخصص"]:
                state["doc_type"] = "specialist"
                state["step"] = "WAIT_SPEC"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: متخصص\n\n"
                    "📌 مرحله ۴ از ۵: لطفاً عنوان دقیق «تخصص پزشک» را بنویسید:\n"
                    "(مثال: متخصص مغز و اعصاب، قلب و عروق، داخلی، ارتوپدی، پوست و مو و...):"
                )
            else:
                send_bale_msg(chat_id, "⚠️ لطفاً یکی از گزینه‌ها را مشخص کنید: ۱ (عمومی) یا ۲ (متخصص):")
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
                "📌 مرحله نهایی: اکنون تصویر واضح، بدون زاویه و خوانا از «پیش‌فاکتور یا نسخه» را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # گام ۵: دریافت عکس
        elif step == "WAIT_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif doc and doc.get("mime_type", "").startswith("image/"):
                file_id = doc.get("file_id")

            if not file_id:
                send_bale_msg(chat_id, "⚠️ فایل دریافتی عکس معتبر نیست. لطفاً تصویر نسخه را ارسال فرمایید.")
                return jsonify({"status": "ok"}), 200

            # اجرای ارزیابی در ترد پس‌زمینه
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
