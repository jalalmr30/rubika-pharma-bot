import os
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

app = Flask(__name__)

# تنظیمات کلید جمنای از متغیرهای محیطی Render
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# توکن ربات بله
BALE_TOKEN = "1099104992:7WNzacPcBNI1lEOOAnhXDzGdN7-c-cUoWcY"
BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

# انتخاب مدل هوشمند جمنای
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route("/", methods=["GET"])
def index():
    return "Rubika Pharma Bot is Running successfully!", 200

@app.route(f"/webhook/{BALE_TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "ok"}), 200

        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if chat_id:
            if text == "/start":
                send_message(chat_id, "سلام متصدی محترم داروخانه 🩺\nبه ربات هوشمند بررسی نسخ و ضوابط بیمه البرز خوش آمدید.\n\nلطفاً نام داروخانه خود را وارد کنید:")
            else:
                # پاسخ هوشمند توسط جمنای بر اساس ضوابط
                prompt = f"شما دستیار هوشمند داروخانه هستید. متصدی داروخانه پیام زیر را فرستاده است: {text}. راهنمایی لازم را بر اساس ضوابط بیمه صادر کنید."
                response = model.generate_content(prompt)
                send_message(chat_id, response.text)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error"}), 500

def send_message(chat_id, text):
    url = f"{BALE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send message: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
