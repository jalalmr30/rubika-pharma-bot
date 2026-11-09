import os
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# خواندن توکن‌ها و کلیدها از متغیرهای محیطی Render
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# تنظیم کلید جمنای
if GEMINI_API_KEY:
  genai.configure(api_key=GEMINI_API_KEY)

# دیکشنری موقت برای نگهداری وضعیت مکالمه کاربران در داروخانه
user_sessions = {}


@app.route(f"/webhook/{BALE_BOT_TOKEN}", methods=["POST"])
def webhook():
  data = request.get_json()
  if not data or "update" not in data:
    return jsonify({"status": "ok"})

  update = data["update"]
  message = update.get("message", {})
  chat_id = message.get("chat", {}).get("id")
  text = message.get("text", "").strip()
  photo = message.get("photo")

  if not chat_id:
    return jsonify({"status": "ok"})

  # اگر کاربر تازه شروع کرده یا دکمه شروع را زده
  if text == "/start" or chat_id not in user_sessions:
    user_sessions[chat_id] = {"step": "get_pharmacy_name"}
    send_bale_message(
        chat_id,
        "سلام متصدی محترم داروخانه؛ خوش آمدید. لطفاً **نام داروخانه** را وارد"
        " کنید:",
    )
    return jsonify({"status": "ok"})

  session = user_sessions[chat_id]
  step = session.get("step")

  # گام ۱: دریافت نام داروخانه
  if step == "get_pharmacy_name":
    session["pharmacy_name"] = text
    session["step"] = "get_organization"
    send_bale_message(
        chat_id, "لطفاً **نام سازمان / محل کار بیمه‌شده** را وارد کنید:"
    )

  # گام ۲: دریافت سازمان بیمه‌شده
  elif step == "get_organization":
    session["organization"] = text
    session["step"] = "get_age"
    send_bale_message(
        chat_id, "لطفاً **سن بیمه‌شده** (فقط عدد صحیح) را وارد کنید:"
    )

  # گام ۳: دریافت سن بیمه‌شده
  elif step == "get_age":
    if not text.isdigit():
      send_bale_message(
          chat_id, "لطفاً سن را به صورت یک عدد صحیح معتبر وارد کنید:"
      )
      return jsonify({"status": "ok"})
    session["age"] = int(text)
    session["step"] = "get_expiry"
    send_bale_message(
        chat_id,
        "لطفاً **تاریخ پایان اعتبار بیمه‌نامه (Expiry Date)** را وارد کنید"
        " (مثلاً 1405/12/29):",
    )

  # گام ۴: دریافت تاریخ انقضا
  elif step == "get_expiry":
    session["expiry_date"] = text
    session["step"] = "get_doctor_specialty"
    send_bale_message(
        chat_id,
        "لطفاً **تخصص پزشک تجویزکننده** را با دقت وارد کنید (مثلاً متخصص قلب و"
        " عروق):",
    )

  # گام ۵: دریافت تخصص پزشک
  elif step == "get_doctor_specialty":
    session["doctor_specialty"] = text
    session["step"] = "get_image"
    send_bale_message(
        chat_id,
        "مراحل اولیه ثبت شد. حالا لطفاً **تصویر کاملاً واضح و خوانا از"
        " پیش‌فاکتور یا نسخه** را ارسال کنید:",
    )

  # گام ۶: دریافت تصویر نسخه و تحلیل هوشمند با جمنای
  elif step == "get_image":
    if photo:
      # دریافت بهترین کیفیت تصویر از پیام بله
      file_id = photo[-1]["file_id"]
      image_bytes = download_bale_file(file_id)

      if image_bytes:
        send_bale_message(
            chat_id,
            "⏳ تصویر دریافت شد. در حال ارزیابی هوشمند نسخه بر اساس ضوابط بیمه"
            " البرز...",
        )

        # فراخوانی موتور جمنای به صورت کاملاً رایگان
        analysis_result = analyze_prescription_with_gemini(
            image_bytes, session
        )
        send_bale_message(chat_id, analysis_result)

        # ریست کردن مراحل برای نسخه جدید
        user_sessions[chat_id] = {"step": "get_pharmacy_name"}
        send_bale_message(
            chat_id,
            "برای بررسی نسخه جدید، نام داروخانه را وارد کنید یا /start را بزنید.",
        )
      else:
        send_bale_message(
            chat_id,
            "خطا در دانلود تصویر. لطفاً دوباره تصویر نسخه را ارسال کنید.",
        )
    else:
      send_bale_message(
          chat_id,
          "لطفاً حتماً تصویر نسخه/پیش‌فاکتور را به صورت عکس ارسال کنید.",
      )

  return jsonify({"status": "ok"})


def send_bale_message(chat_id, text):
  url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Error sending message: {e}")


def download_bale_file(file_id):
  try:
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/getFile?file_id={file_id}"
    res = requests.get(url).json()
    if res.get("ok"):
      file_path = res["result"]["file_path"]
      download_url = (
          f"https://tapi.bale.ai/file/bot{BALE_BOT_TOKEN}/{file_path}"
      )
      img_res = requests.get(download_url)
      return img_res.content
  except Exception as e:
    print(f"Error downloading file: {e}")
  return None


def analyze_prescription_with_gemini(image_bytes, session):
  try:
    # استفاده از مدل سبک و سریع جمنای
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = f"""
    تو یک دستیار هوشمند دارویی و بیمه ای (بیمه البرز) هستی. مخاطب تو متصدی داروخانه است.
    اطلاعات زیر توسط متصدی داروخانه ثبت شده است:
    - نام داروخانه: {session.get('pharmacy_name')}
    - سازمان محل کار بیمه‌شده: {session.get('organization')}
    - سن بیمه‌شده: {session.get('age')} سال
    - تاریخ پایان اعتبار بیمه‌نامه: {session.get('expiry_date')}
    - تخصص پزشک تجویزکننده: {session.get('doctor_specialty')}

    تصویر نسخه یا پیش‌فاکتور پیوست شده است. لطفاً اقلام دارویی، تعداد و دوز آن‌ها را با دقت بخوان و بررسی کن:
    1. آیا تخصص پزشک با داروهای تجویز شده تطابق دارد؟ (مثلاً داروهای تخصصی توسط متخصص مربوطه تجویز شده باشند).
    2. آیا محدودیتی بر اساس سن یا ضوابط بیمه وجود دارد؟
    3. وضعیت تایید یا نیاز به بررسی توسط داروخانه را به صورت شفاف و حرفه‌ای اعلام کن.
    """

    # ارسال تصویر و پرامپت به جمنای
    image_part = {"mime_type": "image/jpeg", "data": image_bytes}
    response = model.generate_content([prompt, image_part])

    return response.text
  except Exception as e:
    return f"خطا در تحلیل هوشمند تصویر با جمنای: {str(e)}"


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
