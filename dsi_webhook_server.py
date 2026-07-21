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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN or CHAT_ID not set!")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def format_alert(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not isinstance(data, dict):
        return f"🚨 <b>تنبيه أسطول</b>\n📅 {now}\n\n{str(data)[:500]}"
    
    # استخراج البيانات من صيغة DSI
    name = data.get("name", data.get("device_name", data.get("device", "")))
    plate = data.get("plate_number", data.get("plate", data.get("registration_number", "")))
    event = data.get("event", data.get("event_type", data.get("alert", data.get("type", ""))))
    custom_data = data.get("custom_data", "")
    message = data.get("message", data.get("msg", data.get("description", "")))
    speed = data.get("speed", data.get("spd", ""))
    lat = data.get("lat", data.get("latitude", ""))
    lng = data.get("lng", data.get("lon", data.get("longitude", "")))
    address = data.get("address", data.get("location", ""))
    driver = data.get("driver", data.get("driver_name", data.get("current_driver_id", "")))
    
    # لو custom_data فيه نوع الحدث
    if custom_data and not event:
        event = custom_data
    
    # بناء الرسالة المختصرة
    text = f"🚨 <b>تنبيه أسطول</b>\n"
    text += f"━━━━━━━━━━━━━━━\n"
    
    if event:
        # ترجمة أنواع الأحداث
        event_ar = {
            "overspeed": "تجاوز السرعة",
            "moving": "تحرك",
            "stopped": "توقف",
            "geofence_enter": "دخول منطقة",
            "geofence_exit": "خروج من منطقة",
            "ignition_on": "تشغيل المحرك",
            "ignition_off": "إيقاف المحرك",
        }.get(str(event).lower(), event)
        text += f"⚡ الحدث: <b>{event_ar}</b>\n"
    
    if name:
        text += f"🚗 المركبة: <b>{name}</b>\n"
    if plate and str(plate).strip():
        text += f"🔢 اللوحة: <b>{plate}</b>\n"
    if driver and str(driver).strip() and str(driver) != "None":
        text += f"👤 السائق: {driver}\n"
    if message:
        text += f"💬 الرسالة: {message}\n"
    if speed:
        text += f"🏎 السرعة: <b>{speed} كم/س</b>\n"
    if lat and lng and str(lat) != "None" and str(lng) != "None":
        text += f"📍 الموقع: <a href='https://maps.google.com/?q={lat},{lng}'>فتح الخريطة</a>\n"
    if address and str(address).strip():
        text += f"📌 العنوان: {address}\n"
    
    text += f"━━━━━━━━━━━━━━━"
    return text

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "active", "message": "Fleet webhook is running"})
    
    data = None
    try:
        data = request.get_json(force=True, silent=True)
    except:
        pass
    if not data:
        try:
            data = request.form.to_dict()
        except:
            pass
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
    test_data = {"name":"تورس س ر ح 1678","plate_number":"أ ب ج 1234","event":"overspeed","speed":135,"lat":24.7136,"lng":46.6753,"message":"تجاوز السرعة (120 كيلومتر في الساعة)","address":"طريق الملك فهد، الرياض"}
    message = format_alert(test_data)
    result = send_telegram(message)
    return jsonify({"status": "test sent", "success": result is not None})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
