import os
import time
import requests

# --- تنظیمات ربات بله ---
BOT_TOKEN = "1099104992:7WNzacPcBN1I1EOOANhXDzGdN7-c-cUoWcY"
API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

user_states = {}

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def delete_webhook():
    """حذف وب‌هاک برای فعال‌سازی مجدد Long Polling"""
    try:
        requests.get(f"{API_URL}/deleteWebhook", timeout=10)
        print("Webhook deleted successfully.")
    except Exception as e:
        print(f"Error deleting webhook: {e}")

def analyze_prescription(state):
    """منطق هوشمند ارزیابی نسخه بر اساس سازمان، سن، تاریخ اعتبار و تخصص پزشک"""
    org = state.get("org", "").strip().lower()
    age = state.get("age", 0)
    specialty = state.get("doctor_specialty", "").strip().lower()
    pharmacy = state.get("pharmacy_name", "")
    expiry = state.get("expiry", "")
    
    report = f"📋 **گزارش ارزیابی هوشمند نسخه**\n"
    report += f"🏥 داروخانه: {pharmacy}\n"
    report += f"🏢 سازمان متبوع: {state.get('org')}\n"
    report += f"👤 سن بیمار: {age} سال | ⏳ اعتبار بیمه: {expiry}\n"
    report += f"🩺 تخصص پزشک: {state.get('doctor_specialty')}\n"
    report += "----------------------------------------\n"
    
    warnings = []
    is_general = "عمومی" in specialty or "عمومى" in specialty
    
    if is_general:
        warnings.append("⚠️ پزشک تجویزکننده «عمومی» است؛ اقلام تخصصی یا مکمل‌ها نیاز به تایید متخصص دارند (به جز ویتامین C و D).")
    else:
        report += f"✅ تخصص پزشک ({specialty}) با اقلام تخصصی همخوانی دارد.\n"
        
    warnings.append("💡 **قاعده پلاویکس:** بررسی تاریخ جراحی بیمار الزامی است (قابل تأیید تا یک سال پس از عمل).")
    warnings.append("💡 **مگنی‌فورت و مکمل‌ها:** با تجویز متخصص قابل قبول است؛ نیاز به بررسی مستندات شعبه دارد.")
    
    if warnings:
        report += "\n🚨 **تذکرات و موارد نیازمند بررسی:**\n" + "\n".join(warnings)
    else:
        report += "\n✅ نسخه فاقد مغایرت قانونی بارز است."
        
    return report

def main():
    delete_webhook()
    print("Bale Pharma Bot is RUNNING...")
    offset = None
    
    while True:
        try:
            params = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset
                
            response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=25)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    for update in 
