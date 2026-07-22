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

# آخر بيانات وصلت (للتشخيص)
last_received = {"data": None, "time": None}

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

def deep_find(data, keys):
    """يبحث عن مفتاح في كل مستويات البيانات حتى داخل القواميس المتداخلة"""
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] not in (None, "", "None"):
                return data[k]
        for v in data.values():
            if isinstance(v, (dict, list)):
                found = deep_find(v, keys)
                if found:
                    return found
    elif isinstance(data, list):
        for item in data:
            found = deep_find(item, keys)
            if found:
                return found
    return None

def format_alert(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not isinstance(data, dict):
        return f"🚨 <b>تنبيه أسطول</b>\n📅 {now}\n\n{str(data)[:500]}"
    
    # البحث العميق عن البيانات في أي مستوى
    # اسم المركبة - نبحث في device أولاً
    device_obj = data.get("device", {})
    if isinstance(device_obj, dict):
        name = device_obj.get("name", "")
        plate = device_obj.get("plate_number", "")
        imei = device_obj.get("imei", "")
    else:
        name = ""
        plate = ""
        imei = ""
    
    if not name:
        name = deep_find(data, ["device_name", "unit_name", "vehicle_name", "object_name"])
    # لو ما لقينا، نجرب name بس لازم نتأكد إنه مو اسم الحدث
    if not name:
        candidate = data.get("name", "")
        event_check = data.get("event", data.get("message", ""))
        if candidate and candidate != event_check:
            name = candidate
    
    if not plate:
        plate = deep_find(data, ["plate_number", "plate", "registration_number", "reg_number"])
    if not imei:
        imei = deep_find(data, ["imei"])
    
    event = deep_find(data, ["event", "event_type", "alert", "type", "event_name"])
    message = deep_find(data, ["message", "msg", "description", "text"])
    speed = deep_find(data, ["speed", "spd", "velocity"])
    lat = deep_find(data, ["lat", "latitude"])
    lng = deep_find(data, ["lng", "lon", "longitude"])
    address = deep_find(data, ["address", "location_address", "place"])
    driver = deep_find(data, ["driver_name", "driver"])
    
    # ترجمة أنواع الأحداث
    event_ar = ""
    if event:
        event_ar = {
            "overspeed": "⚠️ تجاوز السرعة",
            "moving": "🔄 تحرك",
            "stopped": "🛑 توقف",
            "geofence_enter": "📥 دخول منطقة",
            "geofence_exit": "📤 خروج من منطقة",
            "ignition_on": "🔑 تشغيل المحرك",
            "ignition_off": "🔒 إيقاف المحرك",
        }.get(str(event).lower(), str(event))
    
    # بناء الرسالة
    text = f"🚨 <b>تنبيه أسطول</b>\n"
    text += f"━━━━━━━━━━━━━━━\n"
    
    if event_ar:
        text += f"⚡ الحدث: <b>{event_ar}</b>\n"
    if name:
        text += f"🚗 المركبة: <b>{name}</b>\n"
    if plate:
        text += f"🔢 اللوحة: <b>{plate}</b>\n"
    if imei and not name:
        text += f"📟 IMEI: {imei}\n"
    if driver:
        text += f"👤 السائق: {driver}\n"
    if message and message != event:
        text += f"💬 الرسالة: {message}\n"
    if speed:
        text += f"🏎 السرعة: <b>{speed} كم/س</b>\n"
    if lat and lng:
        text += f"📍 الموقع: <a href='https://maps.google.com/?q={lat},{lng}'>فتح الخريطة</a>\n"
    if address:
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
    
    # حفظ آخر بيانات للتشخيص
    last_received["data"] = data
    last_received["time"] = str(datetime.now())
    
    print(f"[{datetime.now()}] Received: {json.dumps(data, ensure_ascii=False)[:1000]}")
    
    message = format_alert(data)
    result = send_telegram(message)
    return jsonify({"status": "ok", "telegram": result is not None})

@app.route("/debug", methods=["GET"])
def debug():
    """يعرض آخر بيانات وصلت من DSI - للتشخيص"""
    return jsonify(last_received)

@app.route("/", methods=["GET"])
def home():
    return "<html dir='rtl'><body style='font-family:Arial;text-align:center;padding:50px'><h1>✅ سيرفر تنبيهات الأسطول شغّال</h1><p>Webhook: <code>/webhook</code></p></body></html>"

@app.route("/test", methods=["GET"])
def test():
    test_data = {"device":{"name":"تورس س ر ح 1678 - 2","plate_number":"أ ب ج 1234"},"event":"overspeed","speed":145,"lat":20.4306516,"lng":44.9318583,"message":"تجاوز السرعة (120 كيلومتر في الساعة)","address":"طريق الخميس السليل"}
    message = format_alert(test_data)
    result = send_telegram(message)
    return jsonify({"status": "test sent", "success": result is not None})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
