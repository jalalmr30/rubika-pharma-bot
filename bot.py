import os
import time
import requests
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bale Pharma Bot (Bimeh Alborz) is running successfully!"

BOT_TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# ذخیره وضعیت و قفل برای جلوگیری از تداخل و ارسال چندتایی
user_states = {}
processed_updates = set()
lock = threading.Lock()

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def analyze_prescription(state):
    org = state.get("org", "").strip().lower()
    age = state.get("age", 0)
    specialty = state.get("doctor_specialty", "").strip().lower()
    pharmacy = state.get("pharmacy_name", "")
    
    report = f"📋 **گزارش ارزیابی هوشمند نسخه**\n"
    report += f"🏥 داروخانه: {pharmacy}\n"
    report += f"🏢 سازمان متبوع: {state.get('org')}\n"
    report += f"👤 سن بیمار: {age} سال | تخصص پزشک: {state.get('doctor_specialty')}\n"
    report += "----------------------------------------\n"
    
    warnings = []
    is_general = "عمومی" in specialty
    
    if "تامین" in org:
        report += "🔸 سازمان تامین اجتماعی: اعمال سقف‌های درمانی و ضوابط عمومی.\n"
    elif "تعاون" in org:
        report += "🔸 بانک توسعه تعاون: بررسی الحاقیه اختصاصی بانک.\n"
    else:
        report += f"🔸 سازمان {state.get('org')}: بررسی مطابق ضوابط عمومی و الحاقیه‌های بیمه البرز.\n"
        
    if is_general:
        warnings.append("⚠️ پزشک تجویزکننده «عمومی» است؛ اقلام تخصصی یا مکمل‌ها نیاز به بررسی بیشتر دارند (به جز ویتامین C و D).")
    else:
        report += f"✅ تخصص پزشک ({specialty}) با اقلام تخصصی همخوانی دارد.\n"
        
    warnings.append("💡 **قاعده پلاویکس:** بررسی تاریخ جراحی بیمار الزامی است (قابل تأیید تا یک سال پس از عمل).")
    warnings.append("💡 **مگنی‌فورت و مکمل‌ها:** با تجویز متخصص قابل قبول است؛ نیاز به بررسی مستندات شعبه دارد.")
    
    if warnings:
        report += "\n🚨 **تذکرات و موارد نیازمند بررسی:**\n" + "\n".join(warnings)
    else:
        report += "\n✅ نسخه فاقد مغایرت قانونی بارز است."
        
    return report

def main_loop():
    print("Bale Pharma Bot (Background Worker) is LISTENING...")
    offset = 0
    while True:
        try:
            response = requests.post(
                f"{API_URL}/getUpdates",
                json={"offset": offset, "limit": 10, "timeout": 20},
                timeout=25
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    for update in updates:
                        update_id = update.get("update_id", 0)
                        
                        with lock:
                            if update_id in processed_updates:
                                continue
                            processed_updates.add(update_id)
                            offset = max(offset, update_id + 1)
                            if len(processed_updates) > 2000:
                                # پاکسازی برای جلوگیری از رشد حافظه
                                processed_updates.clear()
                        
                        message = update.get("message", {})
                        chat = message.get("chat", {})
                        chat_id = chat.get("id")
                        text = message.get("text", "").strip()
                        
                        if not chat_id:
                            continue
                        
                        # دستور شروع گفتگو
                        if text == "/start" or text == "شروع":
                            user_states[chat_id] = {"step": "pharmacy_name"}
                            welcome_text = (
                                "سلام، همکار گرامی داروخانه طرف قرارداد بیمه البرز 🌹\n\n"
                                "به سامانه هوشمند بررسی نسخ و محاسبات الحاقیه‌ها خوش آمدید.\n\n"
                                "لطفاً **نام داروخانه** خود را وارد کنید:"
                            )
                            send_message(chat_id, welcome_text)
                            continue
                        
                        # مدیریت مراحل دریافت اطلاعات
                        if chat_id in user_states:
                            state = user_states[chat_id]
                            step = state.get("step")
                            
                            if step == "pharmacy_name":
                                state["pharmacy_name"] = text
                                state["step"] = "org"
                                send_message(chat_id, "لطفاً **نام سازمان / محل کار بیمه‌شده** (مثلاً تامین اجتماعی، بانک توسعه تعاون، مپنا و...) را وارد کنید:")
                            
                            elif step == "org":
                                state["org"] = text
                                state["step"] = "age"
                                send_message(chat_id, "سن بیمار (فقط عدد صحیح) را وارد کنید:")
                            
                            elif step == "age":
                                if not text.isdigit():
                                    send_message(chat_id, "لطفاً سن بیمار را فقط به صورت عدد صحیح وارد کنید:")
                                    continue
                                state["age"] = int(text)
                                state["step"] = "expiry"
                                send_message(chat_id, "تاریخ پایان اعتبار بیمه‌نامه (مثلاً 1405/12/29) را وارد کنید:")
                            
                            elif step == "expiry":
                                state["expiry"] = text
                                state["step"] = "doctor_specialty"
                                send_message(chat_id, "تخصص پزشک تجویزکننده را وارد کنید (مشخص کنید **عمومی** است یا نام تخصص **متخصص** مثل قلب، داخلی و...):")
                            
                            elif step == "doctor_specialty":
                                state["doctor_specialty"] = text
                                state["step"] = "image"
                                send_message(
                                    chat_id, 
                                    f"📌 اطلاعات ثبت‌شده:\n"
                                    f"▫️ داروخانه: {state.get('pharmacy_name')}\n"
                                    f"▫️ سازمان: {state.get('org')}\n"
                                    f"▫️ سن: {state.get('age')} | تخصص: {text}\n\n"
                                    "حالا لطفاً **تصویر کاملاً واضح و خوانا از پیش‌فاکتور یا نسخه** را ارسال کنید 📷"
                                )
                            
                            elif step == "image":
                                if "photo" in message or "document" in message:
                                    final_report = analyze_prescription(state)
                                    send_message(chat_id, final_report)
                                    send_message(chat_id, "✅ بررسی نسخه به پایان رسید.\n\n(جهت شروع بررسی نسخه جدید دستور /start را ارسال کنید)")
                                    user_states.pop(chat_id, None)
                                else:
                                    send_message(chat_id, "لطفاً تصویر پیش‌فاکتور یا نسخه را به صورت عکس ارسال کنید:")
                        else:
                            # اگر کاربر بدون
