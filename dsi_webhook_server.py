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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8928442710:AAHKJjfo37wZhgiWxyArbXPI8bkm6qwVeMo")
CHAT_ID = os.environ.get("CHAT_ID", "1127549999")
# ==================================

def send_telegram(text):
    """إرسال رسالة لتلقرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def format_alert(data):
    """تنسيق التنبيه كرسالة تلقرام"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # محاولة استخراج البيانات من صيغ مختلفة
    if isinstance(data, dict):
        device = data.get("device_name", data.get("device", data.get("unit", data.get("name", "غير معروف"))))
        event = data.get("event", data.get("alert", data.get("type", data.get("event_type", ""))))
        speed = data.get("speed", data.get("spd", ""))
        lat = data.get("lat", data.get("latitude", ""))
        lng = data.get("lng", data.get("lon", data.get("longitude", "")))
        address = data.get("address", data.get("location", ""))
        plate = data.get("plate", data.get("plate_number", data.get("registration", "")))
        driver = data.get("driver", data.get("driver_name", ""))
        message = data.get("message", data.get("msg", data.get("description", "")))
        
        # بناء الرسالة
        text = f"🚨 <b>تنبيه أسطول</b>\n"
        text += f"━━━━━━━━━━━━━━━\n"
        text += f"📅 {now}\n"
        
        if device:
            text += f"🚗 الجهاز: <b>{device}</b>\n"
        if plate:
            text += f"🔢 اللوحة: <b>{plate}</b>\n"
        if driver:
            text += f"👤 السائق: {driver}\n"
        if event:
            text += f"⚡ الحدث: <b>{event}</b>\n"
        if message:
            text += f"💬 الرسالة: {message}\n"
        if speed:
            text += f"🏎 السرعة: <b>{speed} كم/س</b>\n"
        if lat and lng:
            text += f"📍 الموقع: {lat}, {lng}\n"
            text += f"🗺 <a href='https://maps.google.com/?q={lat},{lng}'>فتح الخريطة</a>\n"
        if address:
            text += f"📌 العنوان: {address}\n"
        
        # لو ما لقينا بيانات معروفة، نرسل كل شي
        if not any([device, event, speed, message]):
            text += f"\n📋 البيانات الكاملة:\n{json.dumps(data, ensure_ascii=False, indent=2)[:500]}\n"
        
        text += f"━━━━━━━━━━━━━━━"
        return text
    else:
        return f"🚨 <b>تنبيه أسطول</b>\n📅 {now}\n\n{str(data)[:1000]}"

# ======== نقاط الاستقبال (Endpoints) ========

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    """نقطة استقبال التنبيهات الرئيسية"""
    if request.method == "GET":
        # بعض الأنظمة ترسل GET للتحقق
        return jsonify({"status": "active", "message": "Fleet webhook is running"})
    
    # استقبال البيانات بأي صيغة
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
    
    # تنسيق وإرسال لتلقرام
    message = format_alert(data)
    result = send_telegram(message)
    
    return jsonify({"status": "ok", "telegram": result is not None})

@app.route("/", methods=["GET"])
def home():
    return """
    <html dir='rtl'>
    <head><title>بوت تنبيهات الأسطول</title></head>
    <body style='font-family: Arial; text-align: center; padding: 50px;'>
        <h1>✅ سيرفر تنبيهات الأسطول شغّال</h1>
        <p>رابط الـ Webhook: <code>/webhook</code></p>
    </body>
    </html>
    """

@app.route("/test", methods=["GET"])
def test():
    """إرسال رسالة تجريبية"""
    test_data = {
        "device_name": "سيارة تجريبية",
        "event": "تجاوز السرعة",
        "speed": 135,
        "lat": 24.7136,
        "lng": 46.6753,
        "message": "هذه رسالة تجريبية"
    }
    message = format_alert(test_data)
    result = send_telegram(message)
    return jsonify({"status": "test sent", "success": result is not None})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Fleet Alert Server running on port {port}")
    app.run(host="0.0.0.0", port=port)
