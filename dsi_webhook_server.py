"""
سيرفر Webhook لتنبيهات الأسطول - DSI
- تنبيهات السرعة مع السرعة القانونية للشارع
- تنبيهات المناطق مع حساب مدة المكوث
- قاعدة بيانات: أعلى سرعة لكل مركبة يومياً + سجل زيارات المناطق
"""

from flask import Flask, request, jsonify
import requests, json, os
from datetime import datetime

import db
import commands

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
# أقل مدة بالدقائق حتى نعتبر الزيارة حقيقية (وليس مجرد عبور)
MIN_DWELL_MIN = int(os.environ.get("MIN_DWELL_MIN", "5"))

last_received = {"data": None, "time": None}

try:
    db.init_db()
    print("✅ Database ready")
except Exception as e:
    print(f"⚠️ DB init error: {e}")


def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN or CHAT_ID not set!")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    try:
        return requests.post(url, json=payload, timeout=10).json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None


def fmt_duration(sec):
    m = int(sec // 60); h = m // 60; m = m % 60
    if h > 0:
        return f"{h} ساعة و {m} دقيقة"
    if m > 0:
        return f"{m} دقيقة"
    return f"{int(sec)} ثانية"


def get_road_speed_limit(lat, lng):
    try:
        query = f'[out:json];way(around:200,{lat},{lng})["maxspeed"];out tags;'
        r = requests.get("https://overpass-api.de/api/interpreter",
                         params={"data": query}, timeout=8,
                         headers={"User-Agent": "FleetAlertBot/1.0"})
        if r.status_code == 200:
            els = r.json().get("elements", [])
            if els:
                tags = els[0].get("tags", {})
                num = "".join(c for c in str(tags.get("maxspeed", "")) if c.isdigit())
                if num:
                    return float(num)
    except Exception as e:
        print(f"Speed limit error: {e}")
    return None


def deep_find(data, keys):
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] not in (None, "", "None"):
                return data[k]
        for v in data.values():
            if isinstance(v, (dict, list)):
                f = deep_find(v, keys)
                if f: return f
    elif isinstance(data, list):
        for item in data:
            f = deep_find(item, keys)
            if f: return f
    return None


def extract_fields(data):
    dev = data.get("device", {})
    name = plate = ""
    if isinstance(dev, dict):
        name = dev.get("name", "")
        plate = dev.get("plate_number", "")
    if not name:
        name = deep_find(data, ["device_name", "unit_name", "vehicle_name", "object_name"])
    if not name:
        c = data.get("name", "")
        if c and c != data.get("event", data.get("message", "")):
            name = c
    if not plate:
        plate = deep_find(data, ["plate_number", "plate", "registration_number"])

    return {
        "name": name or "مركبة غير معروفة",
        "plate": plate or "",
        "driver": deep_find(data, ["driver_name", "driver"]) or "",
        "event": str(deep_find(data, ["event", "event_type", "alert", "type"]) or ""),
        "message": deep_find(data, ["message", "msg", "description"]) or "",
        "speed": deep_find(data, ["speed", "spd", "velocity"]),
        "lat": deep_find(data, ["lat", "latitude"]),
        "lng": deep_find(data, ["lng", "lon", "longitude"]),
        "address": deep_find(data, ["address", "location_address", "place"]) or "",
        "zone": deep_find(data, ["geofence", "geofence_name", "zone", "zone_name", "area"]) or "",
        "ignition": deep_find(data, ["ignition", "engine", "acc"]),
    }


def is_zone_enter(f):
    e = f["event"].lower(); m = str(f["message"]).lower()
    return any(k in e or k in m for k in ["geofence_in", "geofence_enter", "zone_in", "enter", "دخول"])


def is_zone_exit(f):
    e = f["event"].lower(); m = str(f["message"]).lower()
    return any(k in e or k in m for k in ["geofence_out", "geofence_exit", "zone_out", "exit", "خروج"])


def handle_speeding(f):
    """يسجل في القاعدة ويرجع رسالة تلقرام"""
    limit = None
    if f["lat"] and f["lng"]:
        limit = get_road_speed_limit(f["lat"], f["lng"])

    is_record, prev_max = (False, None)
    try:
        is_record, prev_max = db.record_speeding(
            f["name"], f["plate"], f["driver"], f["speed"],
            limit, f["lat"], f["lng"], f["address"])
    except Exception as e:
        print(f"DB speeding error: {e}")

    t = "🚨 <b>تجاوز سرعة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]: t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]: t += f"👤 السائق: {f['driver']}\n"
    if f["speed"]: t += f"🏎 السرعة: <b>{f['speed']} كم/س</b>\n"
    if limit:
        t += f"🛣 السرعة القانونية: <b>{limit:.0f} كم/س</b>\n"
        try:
            over = float(str(f["speed"]).replace(",", "")) - limit
            if over > 0: t += f"🔴 متجاوز بـ: <b>{over:.0f} كم/س</b>\n"
        except: pass
    if is_record and prev_max:
        t += f"📈 <b>أعلى سرعة جديدة اليوم</b> (السابق {prev_max:.0f})\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    if f["address"]: t += f"📌 {f['address']}\n"
    t += "━━━━━━━━━━━━━━━"
    return t


def handle_zone_enter(f):
    zone = f["zone"] or "منطقة محظورة"
    try:
        db.record_zone_enter(f["name"], f["plate"], f["driver"], zone, f["lat"], f["lng"])
    except Exception as e:
        print(f"DB zone enter error: {e}")

    t = "⛔ <b>دخول منطقة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]: t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]: t += f"👤 السائق: {f['driver']}\n"
    t += f"🏭 المنطقة: <b>{zone}</b>\n"
    t += f"⏱ وقت الدخول: {datetime.now().strftime('%H:%M:%S')}\n"
    if str(f.get("ignition","")).lower() in ("0","false","off","no"):
        t += "🔒 المحرك: <b>مطفأ</b>\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    if f["address"]: t += f"📌 {f['address']}\n"
    t += "━━━━━━━━━━━━━━━"
    return t


def handle_zone_exit(f):
    """يرجع رسالة، أو None لو كان مجرد عبور سريع"""
    zone = f["zone"] or "منطقة محظورة"
    res = None
    try:
        res = db.record_zone_exit(f["name"], zone, f["lat"], f["lng"])
    except Exception as e:
        print(f"DB zone exit error: {e}")

    if not res:
        return None
    entered_at, duration = res

    # عبور سريع = نتجاهل
    if duration < MIN_DWELL_MIN * 60:
        print(f"[ZONE] {f['name']} عبر {zone} خلال {fmt_duration(duration)} - تجاهل")
        return None

    t = "✅ <b>خروج من منطقة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]: t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]: t += f"👤 السائق: {f['driver']}\n"
    t += f"🏭 المنطقة: <b>{zone}</b>\n"
    t += f"⏱ دخل: {entered_at.strftime('%H:%M:%S')}\n"
    t += f"⏱ خرج: {datetime.now().strftime('%H:%M:%S')}\n"
    t += f"⏳ <b>إجمالي المدة: {fmt_duration(duration)}</b>\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
    t += "━━━━━━━━━━━━━━━"
    return t


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "active"})

    data = request.get_json(force=True, silent=True)
    if not data:
        try: data = request.form.to_dict()
        except: data = None
    if not data:
        data = {"raw": request.get_data(as_text=True)}

    last_received["data"] = data
    last_received["time"] = str(datetime.now())
    print(f"[{datetime.now()}] {json.dumps(data, ensure_ascii=False)[:600]}")

    f = extract_fields(data)
    msg = None

    if is_zone_exit(f):
        msg = handle_zone_exit(f)
    elif is_zone_enter(f):
        msg = handle_zone_enter(f)
    elif f["speed"]:
        msg = handle_speeding(f)
    else:
        msg = f"🔔 <b>تنبيه</b>\n🚗 {f['name']}\n💬 {f['message'] or f['event']}"

    if msg:
        send_telegram(msg)
    return jsonify({"status": "ok"})


@app.route("/report/speeding", methods=["GET"])
def report_speeding():
    """تقرير المسرعين - صف واحد لكل مركبة يومياً بأعلى سرعة"""
    date = request.args.get("date")
    return jsonify(db.get_speeding_report(date))


@app.route("/report/zones", methods=["GET"])
def report_zones():
    """سجل زيارات المناطق"""
    zone = request.args.get("zone")
    rows = db.get_zone_report(zone)
    for r in rows:
        if r["duration_sec"]:
            r["duration"] = fmt_duration(r["duration_sec"])
    return jsonify(rows)



@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """يستقبل أوامر تلقرام ويرد عليها"""
    upd = request.get_json(force=True, silent=True) or {}
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat", {})
    text = msg.get("text", "")
    chat_id = str(chat.get("id", ""))

    # أمان: نرد فقط على المحادثة المصرح لها
    if CHAT_ID and chat_id != str(CHAT_ID):
        print(f"Ignored command from unauthorized chat {chat_id}")
        return jsonify({"ok": True})

    reply = commands.handle_command(text)
    if reply:
        send_telegram(reply)
    return jsonify({"ok": True})


@app.route("/setup_commands", methods=["GET"])
def setup_commands():
    """يربط البوت بالسيرفر ويسجل قائمة الأوامر - يُشغّل مرة واحدة"""
    base = request.url_root.rstrip("/")
    results = {}
    try:
        r1 = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={"url": f"{base}/telegram"}, timeout=10)
        results["webhook"] = r1.json()

        cmds = [
            {"command": "speed", "description": "أعلى سرعات اليوم"},
            {"command": "speed_week", "description": "تجاوزات آخر ٧ أيام"},
            {"command": "top", "description": "أعلى ١٠ سرعات"},
            {"command": "zones", "description": "آخر زيارات المناطق"},
            {"command": "inside", "description": "مركبات داخل مناطق الآن"},
            {"command": "car", "description": "بحث عن مركبة"},
            {"command": "stats", "description": "إحصائيات عامة"},
            {"command": "help", "description": "قائمة الأوامر"},
        ]
        r2 = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
            json={"commands": cmds}, timeout=10)
        results["commands"] = r2.json()
    except Exception as e:
        results["error"] = str(e)
    return jsonify(results)


@app.route("/debug", methods=["GET"])
def debug():
    return jsonify(last_received)


@app.route("/", methods=["GET"])
def home():
    return """<html dir='rtl'><body style='font-family:Arial;text-align:center;padding:40px'>
    <h1>✅ سيرفر تنبيهات الأسطول</h1>
    <p>Webhook: <code>/webhook</code></p>
    <p><a href='/report/speeding'>تقرير المسرعين</a> |
       <a href='/report/zones'>سجل المناطق</a> |
       <a href='/debug'>تشخيص</a></p>
    <p><a href='/setup_commands'>⚙️ تفعيل أوامر البوت</a></p></body></html>"""


@app.route("/test", methods=["GET"])
def test():
    f = extract_fields({"device": {"name": "تورس س ر ح 1678 - 2", "plate_number": "أ ب ج 1234"},
                        "event": "overspeed", "speed": 130,
                        "lat": 20.4306516, "lng": 44.9318583,
                        "address": "طريق الخميس السليل"})
    send_telegram(handle_speeding(f))
    return jsonify({"status": "test sent"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
