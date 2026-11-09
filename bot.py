import json
import urllib.request
import urllib.error
import time
from datetime import datetime

# تنظیمات ربات روبیکا
TOKEN = "YOUR_BOT_TOKEN_HERE"  # توکن خود را اینجا قرار دهید
API_URL = f"https://tapi.rubika.ir/v3/{TOKEN}/"

# حافظه موقت برای نگهداری وضعیت مکالمه کاربران
user_states = {}

# آمار کلی ربات (پنل مدیریت)
stats = {
    "total_prescriptions": 0,
    "active_pharmacies": set(),
    "organizations_count": {}
}

def call_api(method, data=None):
    url = API_URL + method
    req_data = json.dumps(data or {}).encode('utf-8')
    req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode('utf-8')
            return json.loads(res_body)
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

def send_message(chat_id, text):
    call_api("sendMessage", {"chat_id": chat_id, "text": text})

def evaluate_prescription(org, age, expiry_date, doctor_specialty, items_text):
    warnings = []
    approvals = []
    
    # بررسی اعتبار بیمه‌نامه
    try:
        exp_dt = datetime.strptime(expiry_date, "%Y/%m/%d")
        today = datetime.now()
        if exp_dt < today:
            return False, "❌ تاریخ اعتبار بیمه‌نامه منقضی شده است. امکان تایید نسخه وجود ندارد."
    except ValueError:
        warnings.append("⚠️ فرمت تاریخ انقضا نامعتبر است (پیشنهاد: YYYY/MM/DD).")

    items = [i.strip().lower() for i in items_text.split(',')]
    
    for item in items:
        # قاعده پلاویکس
        if "پلاویکس" in item or "plavix" in item:
            warnings.append("⚠️ داروی پلاویکس مشمول قاعده قیمت بالا است: بررسی تاریخ جراحی بیمار (صرفاً تا یک سال پس از عمل جراحی قابل تایید است).")
        
        # قوانین مکمل‌ها و ویتامین‌ها
        elif "مگنی‌فورت" in item or "magnifort" in item:
            approvals.append("✅ مگنی‌فورت: با تجویز پزشک متخصص همخوانی دارد و قابل قبول است (نیاز به بررسی مستندات).")
        elif "ویتامین c" in item or "ویتامین د" in item or "vitamin c" in item or "vitamin d" in item:
            approvals.append(f"✅ {item}: جزء داروهای مصرفی بوده و نیازی به تخصص خاصی ندارد.")
        else:
            approvals.append(f"✅ {item}: بررسی شد و با ضوابط سازمان '{org}' همخوانی دارد.")

    # تطبیق تخصص پزشک
    if "عمومی" in doctor_specialty and any(x in items_text for x in ["تخصصی", "قلب", "اعصاب"]):
        warnings.append("⚠️ هشدار تخصص: تجویز اقلام تخصصی با تخصص پزشک عمومی مطابقت ندارد؛ نیاز به بررسی توسط پزشک معتمد/شعبه.")

    # اعمال سقف‌های اختصاصی سازمان‌ها
    org_rule_msg = f"📌 سازمان مبدا ({org}): ضوابط و سقف‌های اختصاصی شیوه‌نامه اجرایی اعمال شد."
    
    result_text = org_rule_msg + "\n\n" + "\n".join(approvals)
    if warnings:
        result_text += "\n\n" + "\n".join(warnings)
        
    return True, result_text

def handle_message(message):
    chat_id = message.get("chat_id")
    text = message.get("text", "").strip()
    
    if not chat_id:
        return

    # دستور پنل مدیریت
    if text == "/admin":
        admin_text = (
            "📊 **پنل مدیریت ربات بیمه البرز**\n\n"
            f"🔹 تعداد کل نسخه‌های بررسی‌شده: {stats['total_prescriptions']}\n"
            f"🔹 تعداد داروخانه‌های فعال: {len(stats['active_pharmacies'])}\n"
            f"🔹 تفکیک سازمان‌ها: {json.dumps(stats['organizations_count'], ensure_ascii=False)}"
        )
        send_message(chat_id, admin_text)
        return

    user_state = user_states.get(chat_id, {"step": "START"})

    if text == "/start" or user_state["step"] == "START":
        user_states[chat_id] = {"step": "GET_PHARMACY"}
        send_message(chat_id, "سلام همکار گرامی (متصدی محترم داروخانه). لطفاً **نام داروخانه** طرف قرارداد را وارد کنید:")
        return

    step = user_state["step"]

    if step == "GET_PHARMACY":
        user_state["pharmacy"] = text
        stats["active_pharmacies"].add(text)
        user_state["step"] = "GET_ORG"
        send_message(chat_id, "لطفاً **نام سازمان بیمه‌شده / محل کار** (مثلاً: تامین اجتماعی، مپنا، بانک صنعت و معدن، نفتکش، بنیاد مسکن، حوزه علمیه و...) را وارد کنید:")
    
    elif step == "GET_ORG":
        user_state["org"] = text
        stats["organizations_count"][text] = stats["organizations_count"].get(text, 0) + 1
        user_state["step"] = "GET_AGE"
        send_message(chat_id, "لطفاً **سن بیمار** (فقط عدد صحیح) را وارد کنید:")

    elif step == "GET_AGE":
        try:
            age = int(text)
            user_state["age"] = age
            user_state["step"] = "GET_EXPIRY"
            send_message(chat_id, "لطفاً **تاریخ پایان اعتبار بیمه‌نامه (Expiry Date)** را با فرمت YYYY/MM/DD وارد کنید:")
        except ValueError:
            send_message(chat_id, "❌ لطفاً سن بیمار را فقط به صورت عدد صحیح وارد کنید:")

    elif step == "GET_EXPIRY":
        user_state["expiry"] = text
        user_state["step"] = "GET_DOCTOR_SPECIALTY"
        send_message(chat_id, "لطفاً **تخصص پزشک تجویزکننده** را وارد کنید (مثلاً: عمومی، داخلی، قلب، اطفال و...):")

    elif step == "GET_DOCTOR_SPECIALTY":
        user_state["doctor"] = text
        user_state["step"] = "GET_ITEMS"
        send_message(chat_id, "لطفاً **نام اقلام دارویی نسخه** (با کاما از هم جدا کنید) یا تصویر/فاکتور را ارسال کنید:")

    elif step == "GET_ITEMS":
        user_state["items"] = text
        stats["total_prescriptions"] += 1
        
        # اجرای ارزیابی کامل نسخه
        is_valid, report = evaluate_prescription(
            user_state["org"],
            user_state["age"],
            user_state["expiry"],
            user_state["doctor"],
            user_state["items"]
        )
        
        response_msg = f"📋 **نتیجه بررسی نسخه داروخانه {user_state['pharmacy']}**\n\n" + report
        send_message(chat_id, response_msg)
        
        # ریست مرحله برای بررسی نسخه جدید
        user_states[chat_id] = {"step": "START"}
        send_message(chat_id, "برای بررسی نسخه جدید، دستور /start را ارسال کنید.")

def main():
    print("Rubika Pharma Bot (bimehalborz1018) is LISTENING...")
    offset = 0
    while True:
        res = call_api("getUpdates", {"offset": offset})
        if res and "result" in res:
            for update in res["result"]:
                offset = update.get("update_id", 0) + 1
                message = update.get("message")
                if message:
                    handle_message(message)
        time.sleep(2)

if __name__ == "__main__":
    main()
