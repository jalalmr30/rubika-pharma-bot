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

VALID_ORGS = {
    "1": "بانک توسعه تعاون",
    "2": "جهاد کشاورزی",
    "3": "شرکت ملی نفتکش ایران",
    "4": "مادر تخصصی بازرگانی دولتی",
    "5": "گروه مپنا",
    "6": "بنیاد مسکن انقلاب اسلامی",
    "7": "سازمان توسعه و نوسازی معادن (ایمیدرو)",
    "8": "سازمان فضایی / فناوری اطلاعات",
    "9": "سایر ارگان‌های طرف قرارداد بیمه البرز"
}

def send_bale_msg(chat_id, text):
    """ارسال متن ساده و ایمن بدون به هم ریختگی در بله"""
    try:
        url = f"{BALE_API_URL}/sendMessage"
        # برش به قطعات ۱۲۰۰ کاراکتری
        max_chunk = 1200
        for i in range(0, len(text), max_chunk):
            sub_text = text[i:i + max_chunk]
            requests.post(url, json={"chat_id": chat_id, "text": sub_text}, timeout=15)
    except Exception as e:
        logger.error(f"Error sending msg: {e}")

def get_file_content(file_id):
    """دریافت مستقیم بایت‌های عکس از سرور بله"""
    try:
        info_url = f"{BALE_API_URL}/getFile?file_id={file_id}"
        res = requests.get(info_url, timeout=20).json()
        if not res.get("ok"):
            logger.error(f"getFile failed: {res}")
            return None
        
        file_path = res["result"].get("file_path")
        if not file_path:
            return None
            
        dl_url = f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
        r = requests.get(dl_url, timeout=40)
        if r.status_code == 200:
            return r.content
        else:
            logger.error(f"Download failed with status: {r.status_code}")
    except Exception as e:
        logger.error(f"Exception downloading file: {e}")
    return None

def process_prescription_ai(chat_id, file_id, pharmacy, org, doc_type, specialty):
    try:
        if not GEMINI_API_KEY:
            send_bale_msg(chat_id, "❌ خطای سیستمی: کلید هوش مصنوعی (GEMINI_API_KEY) روی سرور ست نشده است.")
            return

        send_bale_msg(chat_id, "🔍 تصویر دریافت شد. در حال استخراج داروها و اعمال ضوابط بیمه البرز...")

        img_data = get_file_content(file_id)
        if not img_data:
            send_bale_msg(chat_id, "❌ خطا در دانلود تصویر نسخه از سرور بله. لطفاً عکس را دوباره با زاویه مناسب و حجم کمتر ارسال کنید.")
            return

        doc_title = "پزشک عمومی" if doc_type == "general" else f"متخصص ({specialty})"

        prompt = f"""
نقش شما: ممیز ارشد اسناد دارویی بیمه البرز.
اطلاعات متصدی داروخانه:
- داروخانه: {pharmacy}
- سازمان بیمه‌شده: {org}
- وضعیت پزشک تجویزکننده: {doc_title}

دستورات صریح ارزیابی:
۱. بازخوانی و استخراج اقلام:
تمام اقلام، داروها و خدمات ثبت‌شده در فاکتور را به ترتیب شماره‌گذاری کن و بنویس (نام دارو یا خدمت، تعداد، دوز، مبلغ کل و سهم بیمه‌شده).

۲. ارزیابی انطباق با تخصص پزشک ({doc_title}):
آیا این داروها در محدوده صلاحیت قانونی تجویز این رده پزشک هستند؟ داروهایی که نیاز به تایید متخصص دیگر دارند را مشخص کن.

۳. ارزیابی تطبیقی با شیوه‌نامه سازمان '{org}' و آیین‌نامه بیمه البرز:
- مکمل‌ها و ویتامین‌ها: آیا قابل پرداخت هستند؟ سقف دارند یا نیاز به تاییدیه دارند؟
- داروهای تخصصی/برند/خارجی: ضوابط پرداخت سهم سازمان چیست؟
- خدمات فنی و لوازم جانبی (سرنگ، تعرفه خدمات دارویی): مجاز یا غیرمجاز بودن را تعیین کن.

۴. نتیجه‌گیری برای هر قلم:
روبروی هر قلم به صراحت بنویس: [قابل پرداخت] یا [غیرقابل پرداخت با دلیل] یا [مشروط به تایید پزشک معتمد].

۵. خلاصه نهایی:
جمع مبالغ قابل تایید سهم سازمان و سهم بیمار را درج کن.

نکته مهم: خروجی به زبان فارسی سلیس، تمیز و ساختاریافته برای متصدی داروخانه باشد.
"""

        model = genai.GenerativeModel("gemini-1.5-flash")
        contents = [
            prompt,
            {"mime_type": "image/jpeg", "data": img_data}
        ]

        logger.info("Calling Gemini API...")
        response = model.generate_content(contents)

        if response and response.text:
            header = (
                f"📋 نتیجه بررسی کارشناسی نسخه\n"
                f"🏥 داروخانه: {pharmacy}\n"
                f"🏢 سازمان: {org}\n"
                f"🩺 پزشک: {doc_title}\n"
                f"────────────────────\n"
            )
            send_bale_msg(chat_id, header + response.text)
        else:
            send_bale_msg(chat_id, "⚠️ هوش مصنوعی نتوانست متن یا اقلامی از این تصویر استخراج کند. لطفاً تصویر باکیفیت‌تری ارسال فرمایید.")

    except Exception as e:
        logger.error(f"Error in process_prescription_ai: {e}")
        send_bale_msg(chat_id, f"❌ بروز خطا در تحلیل نسخه: {str(e)}")

    finally:
        user_states[chat_id] = {"step": "WAIT_PHARMACY"}
        send_bale_msg(chat_id, "✅ پرونده بسته شد.\n🔄 برای بررسی نسخه بعدی، /start را بفرستید.")

@app.route("/", methods=["GET"])
def home():
    return "Pharma Assessment Bot is Active.", 200

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

        # فرمان شروع یا ریست
        if text in ["/start", "شروع", "restart"]:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_bale_msg(
                chat_id,
                "سلام متصدی محترم داروخانه؛\n"
                "به سامانه ممیزی و ارزیابی هوشمند اسناد دارویی بیمه البرز خوش آمدید.\n\n"
                "📌 مرحله ۱ از ۵: لطفاً «نام کامل داروخانه» را وارد نمایید (حداقل ۳ حرف):"
            )
            return jsonify({"status": "ok"}), 200

        if chat_id not in user_states:
            user_states[chat_id] = {"step": "WAIT_PHARMACY"}
            send_bale_msg(
                chat_id,
                "سلام متصدی محترم داروخانه؛ جهت ارزیابی نسخه، لطفاً «نام داروخانه» را وارد نمایید:"
            )
            return jsonify({"status": "ok"}), 200

        state = user_states[chat_id]
        step = state.get("step")

        # ۱. نام داروخانه (اعتبارسنجی حداقل ۳ حرف)
        if step == "WAIT_PHARMACY":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ نام داروخانه نمی‌تواند تک‌حرفی باشد. لطفاً نام دقیق داروخانه را تایپ کنید:")
                return jsonify({"status": "ok"}), 200

            state["pharmacy"] = text
            state["step"] = "WAIT_ORG"

            org_menu = (
                f"✅ داروخانه: {text}\n\n"
                "📌 مرحله ۲ از ۵: لطفاً سازمان بیمه‌شده / ارگان طرف قرارداد را مشخص نمایید:\n\n"
                "۱. بانک توسعه تعاون\n"
                "۲. جهاد کشاورزی\n"
                "۳. شرکت ملی نفتکش ایران\n"
                "۴. مادر تخصصی بازرگانی دولتی\n"
                "۵. گروه مپنا\n"
                "۶. بنیاد مسکن انقلاب اسلامی\n"
                "۷. سازمان توسعه و نوسازی معادن (ایمیدرو)\n"
                "۸. سازمان فضایی / فناوری اطلاعات\n"
                "۹. سایر سازمان‌های طرف قرارداد بیمه البرز\n\n"
                "👈 لطفاً شماره گزینه (۱ تا ۹) یا نام سازمان را وارد نمایید:"
            )
            send_bale_msg(chat_id, org_menu)
            return jsonify({"status": "ok"}), 200

        # ۲. نام سازمان (اعتبارسنجی دقیق)
        elif step == "WAIT_ORG":
            selected_org = None
            if text in VALID_ORGS:
                selected_org = VALID_ORGS[text]
            elif len(text) >= 3:
                # جستجو در نام‌ها یا ثبت مستقیم
                for k, v in VALID_ORGS.items():
                    if text in v or v in text:
                        selected_org = v
                        break
                if not selected_org:
                    selected_org = text

            if not selected_org:
                send_bale_msg(chat_id, "⚠️ نام سازمان وارد شده معتبر نیست. لطفاً یکی از گزینه‌ها (مثلاً عدد 1 تا 9 یا نام کامل ارگان) را بفرستید:")
                return jsonify({"status": "ok"}), 200

            state["org"] = selected_org
            state["step"] = "WAIT_DOC_TYPE"
            send_bale_msg(
                chat_id,
                f"✅ سازمان ثبت شد: {selected_org}\n\n"
                "📌 مرحله ۳ از ۵: نوع پزشک تجویزکننده را مشخص کنید:\n"
                "۱. عمومی\n"
                "۲. متخصص\n\n"
                "لطفاً عدد (1 یا 2) یا کلمه «عمومی» / «متخصص» را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # ۳. نوع پزشک
        elif step == "WAIT_DOC_TYPE":
            if text in ["1", "عمومی", "پزشک عمومی"]:
                state["doc_type"] = "general"
                state["specialty"] = "پزشک عمومی"
                state["step"] = "WAIT_IMAGE"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: پزشک عمومی\n\n"
                    "📌 مرحله نهایی: لطفاً تصویر واضح، خوانا و اسکن‌شده نسخه یا پیش‌فاکتور را ارسال فرمایید:"
                )
            elif text in ["2", "متخصص", "پزشک متخصص"]:
                state["doc_type"] = "specialist"
                state["step"] = "WAIT_SPEC"
                send_bale_msg(
                    chat_id,
                    "✅ رده پزشک: متخصص\n\n"
                    "📌 مرحله ۴ از ۵: عنوان دقیق تخصص پزشک چیست؟\n"
                    "(مثال: مغز و اعصاب، داخلی، قلب و عروق، ارتوپد، پوست و مو و...):"
                )
            else:
                send_bale_msg(chat_id, "⚠️ لطفاً تنها یکی از گزینه‌ها را انتخاب کنید: ۱ (عمومی) یا ۲ (متخصص)")
            return jsonify({"status": "ok"}), 200

        # ۴. عنوان تخصص پزشک
        elif step == "WAIT_SPEC":
            if len(text) < 3:
                send_bale_msg(chat_id, "⚠️ لطفاً عنوان تخصص را به طور کامل بنویسید (مثلاً: متخصص ارتوپد):")
                return jsonify({"status": "ok"}), 200

            state["specialty"] = text
            state["step"] = "WAIT_IMAGE"
            send_bale_msg(
                chat_id,
                f"✅ تخصص ثبت شد: {text}\n\n"
                "📌 مرحله نهایی: لطفاً تصویر واضح، خوانا و اسکن‌شده نسخه یا پیش‌فاکتور را ارسال فرمایید:"
            )
            return jsonify({"status": "ok"}), 200

        # ۵. دریافت تصویر نسخه
        elif step == "WAIT_IMAGE":
            file_id = None
            if photo:
                file_id = photo[-1].get("file_id")
            elif doc and doc.get("mime_type", "").startswith("image/"):
                file_id = doc.get("file_id")

            if not file_id:
                send_bale_msg(chat_id, "⚠️ لطفاً سند را صرفاً به عنوان تصویر (عکس یا پیش‌فاکتور) ارسال فرمایید.")
                return jsonify({"status": "ok"}), 200

            # ارسال به Thread مجزا جهت جلوگیری از تایم‌اوت وب‌هوک
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
