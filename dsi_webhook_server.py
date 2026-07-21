"""
سيرفر Webhook لتنبيهات الأسطول
يستقبل التنبيهات من DSI ويرسلها لتلقرام
"""

from flask import Flask, request, jsonify
import requests
import json
from datetime import datetime
import os

app = Flask(__name__)

# ============ الإعدادات ============
# لا تكتب التوكن هنا! حطه في Environment Variables على Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
# ==================================

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN or CHAT_ID not set!")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def format_alert(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(data, dict):
        device = data.get("device_name", data.get("device", data.get("unit", data.get("name", ""))))
        event = data.get("event", data.get("alert", data.get("type", data.get("event_type", ""))))
        speed = data.get("speed", data.get("spd", ""))
        lat = data.get("lat", data.get("latitude", ""))
        lng = data.get("lng", data.get("lon", data.get("longitude", "")))
        address = data.get("address", data.get("location", ""))
        plate = data.get("plate", data.get("plate_number", data.get("registration", "")))
        driver = data.get("driver", data.get("driver_name", ""))
        message = data.get("message", data.get("msg", data.get("description", "")))
        
        text = f"🚨 <b>تنبيه أسطول</b>\n━━━━━━━━━━━━━━━\n📅 {now}\n"
        if device: text += f"🚗 الجهاز: <b>{device}</b>\n"
        if plate: text += f"🔢 اللوحة: <b>{plate}</b>\n"
        if driver: text += f"👤 السائق: {driver}\n"
        if event: text += f"⚡ الحدث: <b>{event}</b>\n"
        if message: text += f"💬 الرسالة: {message}\n"
        if speed: text += f"🏎 السرعة: <b>{speed} كم/س</b>\n"
        if lat and lng:
            text += f"📍 الموقع: {lat}, {lng}\n"
            text += f"🗺 <a href='https://maps.google.com/?q={lat},{lng}'>فتح الخريطة</a>\n"
        if address: text += f"📌 العنوان: {address}\n"
        if not any([device, event, speed, message]):
            text += f"\n📋 البيانات:\n{json.dumps(data, ensure_ascii=False, indent=2)[:500]}\n"
        text += "━━━━━━━━━━━━━━━"
        return text
    else:
        return f"🚨 <b>تنبيه أسطول</b>\n📅 {now}\n\n{str(data)[:1000]}"

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "active", "message": "Fleet webhook is running"})
    data = None
    try: data = request.get_json(force=True, silent=True)
    except: pass
    if not data:
        try: data = request.form.to_dict()
        except: pass
    if not data:
        data = {"raw": request.get_data(as_text=True)}
    print(f"[{datetime.now()}] Received: {json.dumps(data, ensure_ascii=False)[:500]}")
    message = format_alert(data)
    result = send_telegram(message)
    return jsonify({"status": "ok", "telegram": result is not None})

@app.route("/", methods=["GET"])
def home():
    return "<html dir='rtl'><body style='font-family:Arial;text-align:center;padding:50px'><h1>✅ سيرفر تنبيهات الأسطول شغّال</h1><p>Webhook: <code>/webhook</code></p></body></html>"

@app.route("/test", methods=["GET"])
def test():
    test_data = {"device_name":"سيارة تجريبية","event":"تجاوز السرعة","speed":135,"lat":24.7136,"lng":46.6753,"message":"رسالة تجريبية"}
    message = format_alert(test_data)
    result = send_telegram(message)
    return jsonify({"status": "test sent", "success": result is not None})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
