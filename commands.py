"""
أوامر بوت تلقرام التفاعلية
"""
from datetime import datetime, timedelta
import db


def fmt_duration(sec):
    if not sec:
        return "—"
    m = int(sec // 60); h = m // 60; m = m % 60
    if h > 0:
        return f"{h}س {m}د"
    return f"{m}د"


def cmd_help():
    return """🤖 <b>أوامر بوت الأسطول</b>
━━━━━━━━━━━━━━━
📊 <b>تقارير السرعة</b>
/speed — أعلى سرعات اليوم
/speed_week — آخر ٧ أيام
/top — أسرع ١٠ مركبات على الإطلاق

🏭 <b>تقارير المناطق</b>
/zones — آخر زيارات المناطق
/inside — المركبات الموجودة داخل مناطق الآن

🔍 <b>بحث</b>
/car اسم — كل سجلات مركبة معينة
مثال: <code>/car تورس</code>

⚙️ <b>أخرى</b>
/stats — إحصائيات عامة
/help — هذه القائمة
━━━━━━━━━━━━━━━"""


def cmd_speed_today():
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.get_speeding_report(today, limit=50)
    if not rows:
        return f"✅ ما فيه تجاوزات سرعة اليوم ({today})"

    t = f"🏎 <b>تجاوزات السرعة — {today}</b>\n━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(rows, 1):
        t += f"\n<b>{i}. {r['vehicle']}</b>\n"
        if r.get("plate"):
            t += f"   🔢 {r['plate']}\n"
        t += f"   🔺 أعلى سرعة: <b>{r['max_speed']:.0f} كم/س</b>\n"
        if r.get("road_limit"):
            t += f"   🛣 الحد: {r['road_limit']:.0f} كم/س"
            over = r['max_speed'] - r['road_limit']
            if over > 0:
                t += f" (تجاوز {over:.0f})"
            t += "\n"
        t += f"   🔁 عدد المرات: {r['count']}\n"
    t += f"\n━━━━━━━━━━━━━━━\n📊 الإجمالي: <b>{len(rows)}</b> مركبة"
    return t


def cmd_speed_week():
    rows = db.get_speeding_report(limit=200)
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = [r for r in rows if str(r["date"]) >= week_ago]
    if not rows:
        return "✅ ما فيه تجاوزات سرعة خلال آخر ٧ أيام"

    # تجميع حسب المركبة
    by_car = {}
    for r in rows:
        v = r["vehicle"]
        if v not in by_car or r["max_speed"] > by_car[v]["max_speed"]:
            by_car[v] = r
        by_car[v].setdefault("days", set()).add(str(r["date"]))

    items = sorted(by_car.values(), key=lambda x: -x["max_speed"])
    t = "📅 <b>تجاوزات السرعة — آخر ٧ أيام</b>\n━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(items[:25], 1):
        t += f"\n<b>{i}. {r['vehicle']}</b>\n"
        t += f"   🔺 أعلى سرعة: <b>{r['max_speed']:.0f} كم/س</b>\n"
        t += f"   📆 عدد الأيام: {len(r.get('days', []))}\n"
    t += f"\n━━━━━━━━━━━━━━━\n📊 <b>{len(items)}</b> مركبة"
    return t


def cmd_top():
    rows = db.get_speeding_report(limit=500)
    if not rows:
        return "لا توجد بيانات بعد"
    by_car = {}
    for r in rows:
        v = r["vehicle"]
        if v not in by_car or r["max_speed"] > by_car[v]["max_speed"]:
            by_car[v] = r
    items = sorted(by_car.values(), key=lambda x: -x["max_speed"])[:10]

    t = "🏆 <b>أعلى ١٠ سرعات مسجلة</b>\n━━━━━━━━━━━━━━━\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(items):
        m = medals[i] if i < 3 else f"{i+1}."
        t += f"\n{m} <b>{r['vehicle']}</b>\n"
        t += f"   <b>{r['max_speed']:.0f} كم/س</b> — {r['date']}\n"
    return t + "\n━━━━━━━━━━━━━━━"


def cmd_zones():
    rows = db.get_zone_report(limit=30)
    if not rows:
        return "لا توجد زيارات مسجلة للمناطق بعد"

    t = "🏭 <b>آخر زيارات المناطق</b>\n━━━━━━━━━━━━━━━\n"
    for r in rows[:20]:
        ent = str(r["entered_at"])[:19]
        t += f"\n🚗 <b>{r['vehicle']}</b>\n"
        t += f"   📍 {r['zone']}\n"
        t += f"   ⏱ دخل: {ent}\n"
        if r["exited_at"]:
            t += f"   ⏳ المدة: <b>{fmt_duration(r['duration_sec'])}</b>\n"
        else:
            t += f"   🔴 <b>لا يزال داخل المنطقة</b>\n"
    return t + "\n━━━━━━━━━━━━━━━"


def cmd_inside():
    rows = db.get_zone_report(limit=200)
    inside = [r for r in rows if not r["exited_at"]]
    if not inside:
        return "✅ ما فيه مركبات داخل المناطق حالياً"

    now = datetime.now()
    t = "🔴 <b>مركبات داخل مناطق الآن</b>\n━━━━━━━━━━━━━━━\n"
    for r in inside:
        try:
            ent = datetime.fromisoformat(str(r["entered_at"]))
            dur = fmt_duration((now - ent).total_seconds())
        except:
            dur = "—"
        t += f"\n🚗 <b>{r['vehicle']}</b>\n"
        t += f"   🏭 {r['zone']}\n"
        t += f"   ⏳ منذ: <b>{dur}</b>\n"
        if r.get("lat"):
            t += f"   📍 <a href='https://maps.google.com/?q={r['lat']},{r['lng']}'>الخريطة</a>\n"
    return t + "\n━━━━━━━━━━━━━━━"


def cmd_car(query):
    if not query:
        return "اكتب اسم المركبة بعد الأمر\nمثال: <code>/car تورس</code>"

    speed_rows = [r for r in db.get_speeding_report(limit=500)
                  if query.lower() in str(r["vehicle"]).lower()]
    zone_rows = [r for r in db.get_zone_report(limit=500)
                 if query.lower() in str(r["vehicle"]).lower()]

    if not speed_rows and not zone_rows:
        return f"🔍 ما لقيت أي سجلات لـ «{query}»"

    t = f"🔍 <b>سجلات: {query}</b>\n━━━━━━━━━━━━━━━\n"
    if speed_rows:
        t += "\n🏎 <b>تجاوزات السرعة:</b>\n"
        for r in speed_rows[:10]:
            t += f"  • {r['date']} — <b>{r['max_speed']:.0f} كم/س</b> ({r['count']} مرة)\n"
    if zone_rows:
        t += "\n🏭 <b>زيارات المناطق:</b>\n"
        for r in zone_rows[:10]:
            ent = str(r["entered_at"])[:16]
            dur = fmt_duration(r["duration_sec"]) if r["exited_at"] else "لا يزال داخل"
            t += f"  • {ent} — {r['zone']} ({dur})\n"
    return t + "\n━━━━━━━━━━━━━━━"


def cmd_stats():
    speed = db.get_speeding_report(limit=1000)
    zones = db.get_zone_report(limit=1000)
    today = datetime.now().strftime("%Y-%m-%d")

    cars = len(set(r["vehicle"] for r in speed))
    today_rows = [r for r in speed if str(r["date"]) == today]
    total_events = sum(r["count"] for r in speed)
    max_ever = max((r["max_speed"] for r in speed), default=0)
    inside_now = len([r for r in zones if not r["exited_at"]])

    return f"""📊 <b>إحصائيات الأسطول</b>
━━━━━━━━━━━━━━━
🏎 <b>السرعة</b>
  • مركبات سجّلت تجاوزات: <b>{cars}</b>
  • إجمالي التجاوزات: <b>{total_events}</b>
  • تجاوزات اليوم: <b>{len(today_rows)}</b> مركبة
  • أعلى سرعة على الإطلاق: <b>{max_ever:.0f} كم/س</b>

🏭 <b>المناطق</b>
  • إجمالي الزيارات: <b>{len(zones)}</b>
  • داخل مناطق الآن: <b>{inside_now}</b>
━━━━━━━━━━━━━━━"""


def handle_command(text):
    """يوجّه الأمر للدالة المناسبة"""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # يشيل @botname في القروبات
    arg = parts[1] if len(parts) > 1 else ""

    routes = {
        "/start": cmd_help,
        "/help": cmd_help,
        "/speed": cmd_speed_today,
        "/speed_week": cmd_speed_week,
        "/top": cmd_top,
        "/zones": cmd_zones,
        "/inside": cmd_inside,
        "/stats": cmd_stats,
    }

    if cmd == "/car":
        return cmd_car(arg)
    if cmd in routes:
        try:
            return routes[cmd]()
        except Exception as e:
            return f"⚠️ صار خطأ: {e}"
    return None
