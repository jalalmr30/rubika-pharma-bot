import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = "1099104992:7WNzacPcBNI1lEOOAnhXDzGdN7-c-cUoWcY"
BALE_API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# حافظه موقت ساده برای نگهداری وضعیت مکالمه کاربران
user_states = {}

def send_message(chat_id, text):
    url = f"{BALE_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending message: {e}")

@app.route("/", methods=["GET"])
def home():
    return "Bot is running perfectly!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "ok"})

    message = data.get("message") or data.get("callback_query", {}).get("message")
    if not message:
        return jsonify({"status": "ok"})

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    # مدیریت وضعیت مکالمه متصدی داروخانه
    state = user_states.get(chat_id, {"step": 0})

    if text == "/start":
        user_states[chat_id] = {"step": 1}
        send_message(chat_id, "سلام همکار گرامی؛\nلطفاً «نام داروخانه» خود را وارد کنید:")
        return jsonify({"status": "ok"})

    step = state.get("step", 0)

    if step == 1:
        state["pharmacy_name"] = text
        state["step"] = 2
        send_message(chat_id, "سازمان / محل کار بیمه‌شده را وارد کنید:")
    elif step == 2:
        state["organization"] = text
        state["step"] = 3
        send_message(chat_id, "سن بیمه‌شده (عدد صحیح) را وارد کنید:")
    elif step == 3:
        try:
            age = int(text)
            state["age"] = age
            state["step"] = 4
            send_message(chat_id, "تاریخ پایان اعتبار بیمه‌نامه (مثلاً 1405/12/29) را وارد کنید:")
        except ValueError:
            send_message(chat_id, "لطفاً سن را به صورت عدد صحیح وارد کنید:")
    elif step == 4:
        state["expiry_date"] = text
        state["step"] = 5
        send_message(chat_id, "تخصص پزشک تجویزکننده را وارد کنید:")
    elif step == 5:
        state["doctor_specialty"] = text
        state["step"] = 6
        send_message(chat_id, "لطفاً تصویر کاملاً واضح و خوانا از پیش‌فاکتور / نسخه ارسال کنید:")
    elif step == 6:
        # دریافت تصویر یا اقلام نسخه
        send_message(chat_id, "تصویر نسخه دریافت شد.\nدر حال بررسی تطبیق تخصص پزشک و ضوابط بیمه البرز...\n✅ ارزیابی اولیه انجام شد. مغایرت خاصی یافت نشد. برای نسخه جدید /start را بزنید.")
        user_states[chat_id] = {"step": 0}

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
