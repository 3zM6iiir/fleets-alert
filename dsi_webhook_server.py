"""
سيرفر Webhook لتنبيهات الأسطول - DSI
- تنبيهات السرعة مع السرعة القانونية للشارع
- تنبيهات المناطق مع حساب مدة المكوث
- قاعدة بيانات: أعلى سرعة لكل مركبة يومياً + سجل زيارات المناطق
"""

from flask import Flask, request, jsonify
import requests, json, os
from datetime import datetime, timedelta

import db
import commands

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")                     # الرئيسي (أنت شخصياً أو قروب عام)
CHAT_SPEED = os.environ.get("CHAT_SPEED", "")            # قروب تنبيهات السرعة التفصيلية
CHAT_ZONES = os.environ.get("CHAT_ZONES", "")            # قروب التنبيهات المهمة (المناطق)
# لو ما ضبطت القروبات الفرعية، كل شي يروح للـ CHAT_ID الرئيسي

# فرق التوقيت بالساعات (DSI يرسل UTC، السعودية = +3)
TZ_OFFSET = float(os.environ.get("TZ_OFFSET", "3"))
# فترة التهدئة بالدقائق: لا نرسل تنبيه سرعة جديد لنفس المركبة قبل مرور هذه المدة
SPEED_COOLDOWN_MIN = float(os.environ.get("SPEED_COOLDOWN_MIN", "10"))
# أقل مدة بالدقائق حتى نعتبر الزيارة حقيقية (وليس مجرد عبور)
MIN_DWELL_MIN = int(os.environ.get("MIN_DWELL_MIN", "5"))

last_received = {"data": None, "time": None, "events": []}

try:
    db.init_db()
    print("✅ Database ready")
except Exception as e:
    print(f"⚠️ DB init error: {e}")


def send_telegram(text, chat_id=None):
    """إرسال رسالة لتلقرام — لو ما حددت chat_id يروح للرئيسي"""
    cid = chat_id or CHAT_ID
    if not TELEGRAM_TOKEN or not cid:
        print("ERROR: TELEGRAM_TOKEN or CHAT_ID not set!")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    try:
        return requests.post(url, json=payload, timeout=10).json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None


def send_to_channels(msg, event_type):
    """
    يوزّع الرسالة على القنوات المناسبة حسب نوع الحدث:
    - speed: قروب السرعة (CHAT_SPEED) + الرئيسي لو ما فيه قروب سرعة
    - zone_in / zone_out: قروب المناطق (CHAT_ZONES) + الرئيسي لو ما فيه قروب مناطق
    - other: الرئيسي فقط
    """
    if not msg:
        return

    sent_to = set()

    if event_type == "speed":
        if CHAT_SPEED:
            send_telegram(msg, CHAT_SPEED)
            sent_to.add(CHAT_SPEED)
        # الرئيسي ما يستقبل السرعة لو فيه قروب مخصص (عشان ما يتكرر)
        if CHAT_ID and CHAT_ID not in sent_to and not CHAT_SPEED:
            send_telegram(msg, CHAT_ID)

    elif event_type in ("zone_in", "zone_out"):
        if CHAT_ZONES:
            send_telegram(msg, CHAT_ZONES)
            sent_to.add(CHAT_ZONES)
        # المناطق مهمة → نرسل للرئيسي دايماً كمان
        if CHAT_ID and CHAT_ID not in sent_to:
            send_telegram(msg, CHAT_ID)

    else:
        send_telegram(msg, CHAT_ID)


def now_local():
    """الوقت المحلي (السعودية)"""
    return datetime.utcnow() + timedelta(hours=TZ_OFFSET)


def to_local(dt):
    """تحويل وقت UTC إلى محلي"""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("T", " ").split(".")[0])
        except Exception:
            return dt
    return dt + timedelta(hours=TZ_OFFSET)


def fmt_local(dt, with_date=False):
    """تنسيق وقت UTC إلى نص محلي"""
    d = to_local(dt)
    if not isinstance(d, datetime):
        return str(d)
    return d.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")


def dsi_time_local(s):
    """تحويل حقل time من DSI (UTC) إلى نص محلي"""
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(str(s).replace("T", " ").split(".")[0])
        return (dt + timedelta(hours=TZ_OFFSET)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(s)


def fmt_duration(sec):
    m = int(sec // 60); h = m // 60; m = m % 60
    if h > 0:
        return f"{h} ساعة و {m} دقيقة"
    if m > 0:
        return f"{m} دقيقة"
    return f"{int(sec)} ثانية"


_speed_cache = {}       # ذاكرة مؤقتة لحدود السرعة حسب الموقع
_last_speed_alert = {}  # آخر وقت أُرسل فيه تنبيه سرعة لكل مركبة


def speed_alert_allowed(vehicle, speed):
    """
    يمنع تكرار تنبيهات السرعة لنفس المركبة خلال فترة التهدئة.
    استثناء: لو السرعة الجديدة أعلى بـ 10+ كم/س من آخر تنبيه، نرسل رغم التهدئة.
    """
    if SPEED_COOLDOWN_MIN <= 0:
        return True
    now = datetime.utcnow()
    rec = _last_speed_alert.get(vehicle)
    try:
        spd = float(str(speed).replace(",", ""))
    except Exception:
        spd = 0
    if rec:
        elapsed = (now - rec["time"]).total_seconds()
        if elapsed < SPEED_COOLDOWN_MIN * 60 and spd <= rec["speed"] + 10:
            return False
    _last_speed_alert[vehicle] = {"time": now, "speed": spd}
    if len(_last_speed_alert) > 3000:
        _last_speed_alert.clear()
    return True

def get_road_speed_limit(lat, lng):
    """جلب السرعة القانونية للشارع من OpenStreetMap مع تخزين مؤقت"""
    try:
        # نقرّب الإحداثيات لـ 3 خانات (~100 متر) لزيادة نسبة الإصابة في الذاكرة
        key = (round(float(lat), 3), round(float(lng), 3))
    except:
        return None
    if key in _speed_cache:
        return _speed_cache[key]

    result = None
    try:
        query = f'[out:json][timeout:6];way(around:200,{lat},{lng})["maxspeed"];out tags;'
        r = requests.get("https://overpass-api.de/api/interpreter",
                         params={"data": query}, timeout=7,
                         headers={"User-Agent": "FleetAlertBot/1.0"})
        if r.status_code == 200:
            els = r.json().get("elements", [])
            if els:
                num = "".join(c for c in str(els[0].get("tags", {}).get("maxspeed", ""))
                              if c.isdigit())
                if num:
                    result = float(num)
    except Exception as e:
        print(f"Speed limit lookup skipped: {e}")

    # نخزّن حتى لو كانت None لتجنب إعادة المحاولة المتكررة
    if len(_speed_cache) < 5000:
        _speed_cache[key] = result
    return result


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


def parse_sensors(data):
    """يستخرج حالة المحرك من مصفوفة sensors في بيانات DSI"""
    out = {}
    for s in (data.get("sensors") or []):
        if not isinstance(s, dict):
            continue
        t = str(s.get("type", "")).lower()
        if t == "ignition":
            out["ignition"] = bool(s.get("value"))
            out["ignition_txt"] = s.get("formatted", "")
        elif t == "blocked":
            out["blocked"] = bool(s.get("value"))
    return out


def extract_fields(data):
    """استخراج الحقول من بيانات DSI الفعلية"""
    dev = data.get("device") or {}
    if not isinstance(dev, dict):
        dev = {}

    # اسم المركبة: device.name هو الصحيح (وليس name الذي يحمل اسم الحدث)
    name = dev.get("name") or ""
    if not name:
        name = deep_find(data, ["device_name", "unit_name", "vehicle_name"]) or ""
    imei = dev.get("imei") or ""
    if not name:
        name = f"جهاز {imei}" if imei else "مركبة غير معروفة"

    plate = dev.get("plate_number") or dev.get("registration_number") or ""

    # السائق
    driver = (dev.get("current_driver_name") or
              deep_find(data, ["driver_name", "driver"]) or "")

    # المنطقة الجغرافية
    gf = data.get("geofence")
    if isinstance(gf, dict):
        zone = gf.get("name") or gf.get("title") or ""
    else:
        zone = gf or ""
    if not zone:
        zone = deep_find(data, ["geofence_name", "zone_name", "area"]) or ""
    # استخراج من الرسالة: "دخول المنطقة الصناعية" → "المنطقة الصناعية"
    if not zone:
        m = str(data.get("message") or "")
        for prefix in ("دخول ", "خروج من ", "خروج "):
            if m.startswith(prefix):
                zone = m[len(prefix):].strip()
                break
    if not zone and data.get("geofence_id"):
        zone = f"منطقة رقم {data['geofence_id']}"

    # الحد المضبوط في DSI
    add = data.get("additional") or {}
    threshold = add.get("overspeed_speed") if isinstance(add, dict) else None

    sens = parse_sensors(data)

    return {
        "name": name,
        "imei": imei,
        "device_id": data.get("device_id") or dev.get("id") or "",
        "plate": plate,
        "driver": driver,
        "event": str(data.get("type") or deep_find(data, ["event", "event_type"]) or ""),
        "event_name": data.get("name") or "",
        "message": data.get("message") or data.get("detail") or "",
        "speed": data.get("speed") or deep_find(data, ["spd", "velocity"]),
        "threshold": threshold,
        "lat": data.get("latitude") if data.get("latitude") is not None else deep_find(data, ["lat"]),
        "lng": data.get("longitude") if data.get("longitude") is not None else deep_find(data, ["lng", "lon"]),
        "address": data.get("address") or "",
        "zone": zone,
        "event_time": dsi_time_local(data.get("time") or data.get("created_at") or ""),
        "ignition": sens.get("ignition"),
        "ignition_txt": sens.get("ignition_txt", ""),
        "course": data.get("course"),
        "geofence_id": data.get("geofence_id"),
    }


def compass_ar(course):
    """تحويل درجات الاتجاه لاتجاه بوصلة عربي"""
    try:
        c = float(course)
    except:
        return None
    dirs = ["شمال ⬆️", "شمال شرق ↗️", "شرق ➡️", "جنوب شرق ↘️",
            "جنوب ⬇️", "جنوب غرب ↙️", "غرب ⬅️", "شمال غرب ↖️"]
    return dirs[int(((c + 22.5) % 360) // 45)]


def is_zone_event(f):
    """هل هذا حدث منطقة جغرافية؟ (أقوى إشارة: geofence_id)"""
    if f.get("geofence_id") or f.get("zone"):
        return True
    blob = (f["event"] + " " + str(f["event_name"]) + " " + str(f["message"])).lower()
    return any(k in blob for k in ["geofence", "zone_", "حدود جغرافية"])


def zone_direction(f):
    """
    يحدد اتجاه حدث المنطقة: "in" أو "out" أو None (ليس حدث منطقة).
    الترتيب: type الصريح ← كلمات الرسالة ← حالة قاعدة البيانات.
    """
    if not is_zone_event(f):
        return None

    t = f["event"].lower()
    # type صريح مثل zone_in / geofence_out / zone_exit
    if any(k in t for k in ["_out", "exit", "outside"]) or t == "out":
        return "out"
    if any(k in t for k in ["_in", "enter", "inside"]) or t == "in":
        return "in"

    # كلمات الرسالة/الاسم (نتجنب "في" لأنها ترد في "في/خارج")
    blob = str(f["event_name"]) + " " + str(f["message"])
    has_in = "دخول" in blob
    has_out = ("خروج" in blob) or ("خارج" in blob and "في/خارج" not in blob)
    if has_out and not has_in:
        return "out"
    if has_in and not has_out:
        return "in"

    # غامض (مثل تنبيه "في/خارج" المدمج) → نحدد من حالة قاعدة البيانات:
    # لو للمركبة زيارة مفتوحة في هذه المنطقة = هذا خروج، وإلا دخول
    try:
        conn = db.get_conn(); cur = conn.cursor()
        cur.execute(db.q("""SELECT id FROM zone_visits
                         WHERE vehicle=? AND exited_at IS NULL LIMIT 1"""),
                    (f["name"],))
        is_open = cur.fetchone() is not None
        cur.close(); conn.close()
        return "out" if is_open else "in"
    except Exception as e:
        print(f"zone_direction DB check error: {e}")
        return "in"


def handle_speeding(f):
    """يسجل تجاوز السرعة في القاعدة ويبني رسالة تلقرام"""
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

    try:
        spd = float(str(f["speed"]).replace(",", ""))
    except:
        spd = None

    t = "🚨 <b>تجاوز سرعة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]:
        t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]:
        t += f"👤 السائق: {f['driver']}\n"
    if f["event_time"]:
        t += f"🕐 الوقت: {f['event_time']}\n"
    if spd is not None:
        t += f"🏎 السرعة: <b>{spd:.0f} كم/س</b>\n"
    comp = compass_ar(f.get("course"))
    if comp:
        t += f"🧭 الاتجاه: {comp}\n"
    if f["threshold"]:
        t += f"⚙️ حد التنبيه: {f['threshold']} كم/س\n"
    if limit:
        t += f"🛣 السرعة القانونية: <b>{limit:.0f} كم/س</b>\n"
        if spd is not None and spd > limit:
            t += f"🔴 متجاوز بـ: <b>{spd - limit:.0f} كم/س</b>\n"
    if is_record and prev_max:
        t += f"📈 <b>أعلى سرعة جديدة اليوم</b> (السابق {prev_max:.0f})\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    if f["address"]:
        t += f"📌 {f['address']}\n"
    t += "━━━━━━━━━━━━━━━"
    return t


def handle_zone_enter(f):
    zone = f["zone"] or "منطقة محددة"
    try:
        db.record_zone_enter(f["name"], f["plate"], f["driver"], zone, f["lat"], f["lng"])
    except Exception as e:
        print(f"DB zone enter error: {e}")

    t = "⛔ <b>دخول منطقة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]:
        t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]:
        t += f"👤 السائق: {f['driver']}\n"
    t += f"🏭 المنطقة: <b>{zone}</b>\n"
    t += f"🕐 وقت الدخول: {f['event_time'] or now_local().strftime('%Y-%m-%d %H:%M:%S')}\n"
    if f["ignition"] is not None:
        t += f"🔑 المحرك: <b>{'يعمل' if f['ignition'] else 'مطفأ'}</b>\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    if f["address"]:
        t += f"📌 {f['address']}\n"
    t += "━━━━━━━━━━━━━━━"
    return t


def handle_zone_exit(f):
    """يرجع رسالة الخروج، أو None لو كان مجرد عبور سريع"""
    zone = f["zone"] or "منطقة محددة"
    res = None
    try:
        res = db.record_zone_exit(f["name"], zone, f["lat"], f["lng"])
    except Exception as e:
        print(f"DB zone exit error: {e}")

    now_txt = f["event_time"] or now_local().strftime("%Y-%m-%d %H:%M:%S")

    if not res:
        # ما فيه دخول مسجل (السيرفر أعيد تشغيله أو فات الحدث) — نرسل بدون مدة
        t = "✅ <b>خروج من منطقة</b>\n━━━━━━━━━━━━━━━\n"
        t += f"🚗 المركبة: <b>{f['name']}</b>\n"
        if f["plate"]:
            t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
        t += f"🏭 المنطقة: <b>{zone}</b>\n"
        t += f"🕐 وقت الخروج: {now_txt}\n"
        t += "⏳ المدة: غير معروفة (لم يُسجَّل الدخول)\n"
        if f["lat"] and f["lng"]:
            t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
        t += "━━━━━━━━━━━━━━━"
        return t

    entered_at, duration, stored_zone = res
    if stored_zone:
        zone = stored_zone

    # عبور سريع = تجاهل صامت
    if duration < MIN_DWELL_MIN * 60:
        print(f"[ZONE] {f['name']} عبر {zone} خلال {fmt_duration(duration)} - تجاهل")
        return None

    t = "✅ <b>خروج من منطقة</b>\n━━━━━━━━━━━━━━━\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]:
        t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["driver"]:
        t += f"👤 السائق: {f['driver']}\n"
    t += f"🏭 المنطقة: <b>{zone}</b>\n"
    t += f"🕐 دخل: {fmt_local(entered_at)}\n"
    t += f"🕐 خرج: {now_txt}\n"
    t += f"⏳ <b>إجمالي المدة: {fmt_duration(duration)}</b>\n"
    if f["lat"] and f["lng"]:
        t += f"🎯 <code>{f['lat']}, {f['lng']}</code>\n"
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    t += "━━━━━━━━━━━━━━━"
    return t


def handle_generic(f):
    """تنبيه غير معروف النوع — منسق ومختصر بدون بيانات خام"""
    t = "🔔 <b>تنبيه</b>\n━━━━━━━━━━━━━━━\n"
    ev = f["event_name"] or f["event"] or "حدث"
    t += f"⚡ الحدث: <b>{ev}</b>\n"
    t += f"🚗 المركبة: <b>{f['name']}</b>\n"
    if f["plate"]:
        t += f"🔢 اللوحة: <b>{f['plate']}</b>\n"
    if f["event_time"]:
        t += f"🕐 الوقت: {f['event_time']}\n"
    if f["message"] and f["message"] != ev:
        t += f"💬 {f['message']}\n"
    if f["lat"] and f["lng"]:
        t += f"📍 <a href='https://maps.google.com/?q={f['lat']},{f['lng']}'>فتح الخريطة</a>\n"
    if f["address"]:
        t += f"📌 {f['address']}\n"
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
    last_received["events"] = ([{"time": str(datetime.now()),
                                 "type": str(data.get("type", "")),
                                 "data": data}]
                               + last_received.get("events", []))[:5]
    print(f"[{datetime.now()}] {json.dumps(data, ensure_ascii=False)[:600]}")

    f = extract_fields(data)
    msg = None

    zdir = zone_direction(f)
    if zdir == "out":
        msg = handle_zone_exit(f)
    elif zdir == "in":
        msg = handle_zone_enter(f)
    elif f["event"].lower() == "overspeed":
        msg = handle_speeding(f)
    else:
        # سرعة بدون type واضح؟
        try:
            spd = float(str(f["speed"] or 0).replace(",", ""))
        except:
            spd = 0
        if spd > 0 and "سرعة" in str(f["message"]):
            msg = handle_speeding(f)
        else:
            msg = handle_generic(f)

    if msg:
        if zdir == "in":
            send_to_channels(msg, "zone_in")
        elif zdir == "out":
            send_to_channels(msg, "zone_out")
        elif f["event"].lower() == "overspeed" or "سرعة" in str(f.get("message", "")):
            # التسجيل في القاعدة تم مسبقاً؛ هنا نقرر الإرسال فقط
            if speed_alert_allowed(f["name"], f["speed"]):
                send_to_channels(msg, "speed")
            else:
                print(f"[COOLDOWN] تنبيه سرعة مكتوم لـ {f['name']} ({f['speed']})")
        else:
            send_to_channels(msg, "other")
    return jsonify({"status": "ok"})


@app.route("/report/speeding", methods=["GET"])
def report_speeding():
    """تقرير المسرعين - صف واحد لكل مركبة يومياً بأعلى سرعة"""
    try:
        date = request.args.get("date")
        return jsonify(db.get_speeding_report(date))
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "type": type(e).__name__,
                        "trace": traceback.format_exc()[-1500:]}), 200


@app.route("/report/zones", methods=["GET"])
def report_zones():
    """سجل زيارات المناطق"""
    try:
        zone = request.args.get("zone")
        rows = db.get_zone_report(zone)
        for r in rows:
            if r.get("duration_sec"):
                r["duration"] = fmt_duration(r["duration_sec"])
        return jsonify(rows)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "type": type(e).__name__,
                        "trace": traceback.format_exc()[-1500:]}), 200



@app.route("/channels", methods=["GET"])
def channels():
    """فحص إعدادات القنوات واختبار الإرسال لكل واحدة"""
    conf = {
        "CHAT_ID (الرئيسي)": CHAT_ID or "غير مضبوط",
        "CHAT_SPEED (قروب السرعة)": CHAT_SPEED or "غير مضبوط",
        "CHAT_ZONES (قروب المناطق)": CHAT_ZONES or "غير مضبوط",
        "TZ_OFFSET (فرق التوقيت)": TZ_OFFSET,
        "SPEED_COOLDOWN_MIN": SPEED_COOLDOWN_MIN,
        "MIN_DWELL_MIN": MIN_DWELL_MIN,
        "الوقت المحلي الآن": now_local().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tests = {}
    if request.args.get("test") == "1":
        for label, cid in [("CHAT_ID", CHAT_ID), ("CHAT_SPEED", CHAT_SPEED),
                           ("CHAT_ZONES", CHAT_ZONES)]:
            if not cid:
                tests[label] = "غير مضبوط - تم التخطي"
                continue
            r = send_telegram(f"✅ رسالة اختبار للقناة <b>{label}</b>", cid)
            if r and r.get("ok"):
                chat = r.get("result", {}).get("chat", {})
                tests[label] = {
                    "الحالة": "✅ نجح",
                    "اسم المحادثة": chat.get("title") or chat.get("first_name", ""),
                    "النوع": chat.get("type", ""),
                }
            else:
                desc = (r or {}).get("description", "لا يوجد رد")
                hint = ""
                if "chat not found" in str(desc).lower():
                    hint = "تأكد أن البوت مضاف للقروب وأن الـ ID صحيح (قروبات تلقرام تبدأ بـ -100)"
                elif "kicked" in str(desc).lower() or "not a member" in str(desc).lower():
                    hint = "البوت غير موجود في القروب - أضفه أولاً"
                tests[label] = {"الحالة": "❌ فشل", "السبب": desc, "الحل": hint}
    else:
        tests = "أضف ?test=1 للرابط لإرسال رسالة اختبار لكل قناة"

    return jsonify({"الإعدادات": conf, "الاختبار": tests})


@app.route("/dbcheck", methods=["GET"])
def dbcheck():
    """فحص شامل لقاعدة البيانات"""
    out = {}
    try:
        out["using_postgres"] = db.USE_PG
        url = os.environ.get("DATABASE_URL", "")
        out["database_url_set"] = bool(url)
        if url:
            # نعرض جزء آمن فقط من الرابط
            safe = url.split("@")[-1] if "@" in url else "hidden"
            out["host"] = safe
        conn = db.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM speeding")
        out["speeding_rows"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM zone_visits")
        out["zone_rows"] = cur.fetchone()[0]
        cur.execute("SELECT vehicle, max_speed, event_date FROM speeding LIMIT 3")
        out["sample"] = [[str(x) for x in r] for r in cur.fetchall()]
        cur.close(); conn.close()
        out["status"] = "✅ قاعدة البيانات تعمل"
    except Exception as e:
        import traceback
        out["status"] = "❌ خطأ"
        out["error"] = str(e)
        out["trace"] = traceback.format_exc()[-1200:]
    return jsonify(out)



@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """يستقبل أوامر تلقرام ويرد عليها"""
    upd = request.get_json(force=True, silent=True) or {}
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat", {})
    text = msg.get("text", "")
    chat_id = str(chat.get("id", ""))

    # أمر /chatid يرد على أي محادثة (لمعرفة الـ Chat ID)
    if text.strip().lower().startswith("/chatid"):
        info = f"🔑 <b>Chat ID:</b>\n<code>{chat_id}</code>\n\nانسخ هذا الرقم وحطه في Render"
        send_telegram(info, chat_id)
        return jsonify({"ok": True})

    # أمان: نرد فقط على المحادثات المصرح لها
    allowed = {str(x) for x in [CHAT_ID, CHAT_SPEED, CHAT_ZONES] if x}
    if allowed and chat_id not in allowed:
        print(f"[AUTH] Chat ID {chat_id} tried command: {text}")
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
            {"command": "today", "description": "📋 ملخص اليوم الشامل"},
            {"command": "yesterday", "description": "📋 ملخص أمس"},
            {"command": "speed", "description": "أعلى سرعات اليوم"},
            {"command": "repeat", "description": "المتكررين اليوم"},
            {"command": "speed_week", "description": "تجاوزات آخر ٧ أيام"},
            {"command": "top", "description": "أعلى ١٠ سرعات"},
            {"command": "zones", "description": "آخر زيارات المناطق"},
            {"command": "inside", "description": "مركبات داخل مناطق الآن"},
            {"command": "car", "description": "بحث عن مركبة"},
            {"command": "date", "description": "ملخص تاريخ محدد"},
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



@app.route("/cleanup_test", methods=["GET"])
def cleanup_test():
    """حذف بيانات الاختبار فقط (التي تبدأ بكلمة اختبار)"""
    try:
        conn = db.get_conn(); cur = conn.cursor()
        cur.execute(db.q("DELETE FROM speeding WHERE vehicle LIKE ?"), ("اختبار%",))
        n1 = cur.rowcount
        cur.execute(db.q("DELETE FROM zone_visits WHERE vehicle LIKE ?"), ("اختبار%",))
        n2 = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return jsonify({"deleted_speeding": n1, "deleted_zones": n2, "status": "تم التنظيف"})
    except Exception as e:
        return jsonify({"error": str(e)})


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
    <p><a href='/setup_commands'>⚙️ تفعيل أوامر البوت</a> | <a href='/channels?test=1'>📡 فحص القنوات</a></p></body></html>"""


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
