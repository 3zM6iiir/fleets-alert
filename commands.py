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
📋 <b>ملخصات</b>
/today — ملخص اليوم الشامل
/yesterday — ملخص أمس
/date تاريخ — ملخص يوم محدد

📊 <b>تقارير السرعة</b>
/speed — أعلى سرعات اليوم
/speed_week — آخر ٧ أيام
/top — أسرع ١٠ مركبات على الإطلاق
/repeat — المتكررين (أكثر من تجاوز)

🏭 <b>تقارير المناطق</b>
/zones — آخر زيارات المناطق
/inside — المركبات داخل مناطق الآن

🔍 <b>بحث</b>
/car اسم — كل سجلات مركبة معينة

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



def cmd_today():
    """ملخص اليوم الشامل"""
    today = datetime.now().strftime("%Y-%m-%d")
    speed = db.get_speeding_report(today, limit=200)
    zones = db.get_zone_report(limit=200)
    today_zones = [z for z in zones if str(z.get("entered_at",""))[:10] == today]

    if not speed and not today_zones:
        return f"✅ يوم هادي! ما فيه أي تجاوزات أو زيارات مناطق اليوم ({today})"

    total_events = sum(r["count"] for r in speed)
    top = speed[0] if speed else None
    inside = [z for z in today_zones if not z["exited_at"]]

    t = f"📋 <b>ملخص اليوم — {today}</b>\n"
    t += "━━━━━━━━━━━━━━━\n"

    # قسم السرعة
    if speed:
        t += f"\n🏎 <b>تجاوزات السرعة</b>\n"
        t += f"  📊 عدد المركبات: <b>{len(speed)}</b>\n"
        t += f"  🔁 إجمالي التجاوزات: <b>{total_events}</b>\n"
        if top:
            t += f"  🏆 الأعلى: <b>{top['vehicle']}</b> ({top['max_speed']:.0f} كم/س)\n"
        t += f"\n  <b>التفاصيل:</b>\n"
        for i, r in enumerate(speed, 1):
            line = f"  {i}. {r['vehicle']}"
            if r.get("plate"):
                line += f" ({r['plate']})"
            line += f" — <b>{r['max_speed']:.0f}</b> كم/س"
            if r["count"] > 1:
                line += f" ({r['count']}×)"
            t += line + "\n"

    # قسم المناطق
    if today_zones:
        t += f"\n🏭 <b>زيارات المناطق</b>\n"
        t += f"  📊 عدد الزيارات: <b>{len(today_zones)}</b>\n"
        if inside:
            t += f"  🔴 داخل الآن: <b>{len(inside)}</b>\n"
        t += "\n"
        for z in today_zones[:15]:
            t += f"  🚗 <b>{z['vehicle']}</b>\n"
            t += f"     📍 {z['zone']}\n"
            ent = str(z.get('entered_at',''))
            if 'T' in ent:
                ent = ent.split('T')[1][:8]
            elif ' ' in ent:
                ent = ent.split(' ')[1][:8]
            t += f"     ⏱ دخل: {ent}\n"
            if z.get("exited_at"):
                ext = str(z['exited_at'])
                if 'T' in ext:
                    ext = ext.split('T')[1][:8]
                elif ' ' in ext:
                    ext = ext.split(' ')[1][:8]
                t += f"     ⏱ خرج: {ext}\n"
                t += f"     ⏳ المدة: <b>{fmt_duration(z['duration_sec'])}</b>\n"
            else:
                now = datetime.now()
                try:
                    ea = str(z['entered_at'])
                    ea_dt = datetime.fromisoformat(ea)
                    elapsed = (now - ea_dt).total_seconds()
                    t += f"     🔴 <b>لا يزال داخل المنطقة ({fmt_duration(elapsed)})</b>\n"
                except:
                    t += f"     🔴 <b>لا يزال داخل المنطقة</b>\n"
            t += "\n"

    t += "\n━━━━━━━━━━━━━━━"
    return t


def cmd_yesterday():
    """ملخص أمس"""
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    speed = db.get_speeding_report(yest, limit=200)
    zones = db.get_zone_report(limit=500)
    yest_zones = [z for z in zones if str(z.get("entered_at",""))[:10] == yest]

    if not speed and not yest_zones:
        return f"✅ أمس ({yest}) كان يوم هادي — ما فيه تجاوزات أو زيارات مناطق"

    total_events = sum(r["count"] for r in speed)
    top = speed[0] if speed else None

    t = f"📋 <b>ملخص أمس — {yest}</b>\n"
    t += "━━━━━━━━━━━━━━━\n"

    if speed:
        t += f"\n🏎 <b>تجاوزات السرعة</b>\n"
        t += f"  📊 المركبات: <b>{len(speed)}</b> | التجاوزات: <b>{total_events}</b>\n"
        if top:
            t += f"  🏆 الأعلى: <b>{top['vehicle']}</b> ({top['max_speed']:.0f} كم/س)\n"
        t += "\n"
        for i, r in enumerate(speed, 1):
            line = f"  {i}. {r['vehicle']}"
            line += f" — <b>{r['max_speed']:.0f}</b> كم/س"
            if r["count"] > 1:
                line += f" ({r['count']}×)"
            t += line + "\n"

    if yest_zones:
        t += f"\n🏭 <b>زيارات المناطق:</b> {len(yest_zones)} زيارة\n\n"
        for z in yest_zones[:10]:
            t += f"  🚗 <b>{z['vehicle']}</b>\n"
            t += f"     📍 {z['zone']}\n"
            ent = str(z.get('entered_at',''))
            if 'T' in ent:
                ent = ent.split('T')[1][:8]
            elif ' ' in ent:
                ent = ent.split(' ')[1][:8]
            ext = str(z.get('exited_at','') or '')
            if 'T' in ext:
                ext = ext.split('T')[1][:8]
            elif ' ' in ext:
                ext = ext.split(' ')[1][:8]
            if z.get("duration_sec"):
                t += f"     ⏱ دخل: {ent} → خرج: {ext}\n"
                t += f"     ⏳ المدة: <b>{fmt_duration(z['duration_sec'])}</b>\n"
            else:
                t += f"     ⏱ دخل: {ent}\n"
            t += "\n"

    t += "\n━━━━━━━━━━━━━━━"
    return t


def cmd_repeat():
    """المركبات المتكررة في التجاوزات - أكثر من مرة اليوم"""
    today = datetime.now().strftime("%Y-%m-%d")
    speed = db.get_speeding_report(today, limit=200)
    repeaters = [r for r in speed if r["count"] > 1]

    if not repeaters:
        return f"✅ ما فيه مركبات تكررت تجاوزاتها أكثر من مرة اليوم ({today})"

    repeaters.sort(key=lambda x: -x["count"])
    t = f"🔁 <b>المتكررين اليوم — {today}</b>\n"
    t += "━━━━━━━━━━━━━━━\n\n"
    for i, r in enumerate(repeaters, 1):
        t += f"{i}. <b>{r['vehicle']}</b>\n"
        t += f"   🔁 عدد التجاوزات: <b>{r['count']}</b>\n"
        t += f"   🔺 أعلى سرعة: <b>{r['max_speed']:.0f} كم/س</b>\n"
        if r.get("road_limit"):
            t += f"   🛣 الحد: {r['road_limit']:.0f} كم/س\n"
    t += f"\n━━━━━━━━━━━━━━━\n📊 الإجمالي: <b>{len(repeaters)}</b> مركبة متكررة"
    return t


def cmd_date(arg):
    """ملخص تاريخ معين: /date 2026-07-22"""
    if not arg or len(arg) < 8:
        return "اكتب التاريخ بعد الأمر\nمثال: <code>/date 2026-07-22</code>"

    date = arg.strip()
    speed = db.get_speeding_report(date, limit=200)
    zones = db.get_zone_report(limit=500)
    day_zones = [z for z in zones if str(z.get("entered_at",""))[:10] == date]

    if not speed and not day_zones:
        return f"ما فيه بيانات ليوم {date}"

    total_events = sum(r["count"] for r in speed)

    t = f"📅 <b>ملخص — {date}</b>\n"
    t += "━━━━━━━━━━━━━━━\n"

    if speed:
        t += f"\n🏎 <b>{len(speed)}</b> مركبة سرّعت ({total_events} تجاوز)\n\n"
        for i, r in enumerate(speed, 1):
            t += f"  {i}. {r['vehicle']} — <b>{r['max_speed']:.0f}</b> كم/س ({r['count']}×)\n"

    if day_zones:
        t += f"\n🏭 <b>{len(day_zones)}</b> زيارة منطقة\n\n"
        for z in day_zones[:10]:
            t += f"  🚗 <b>{z['vehicle']}</b> → {z['zone']}\n"
            ent = str(z.get('entered_at',''))
            if 'T' in ent: ent = ent.split('T')[1][:8]
            elif ' ' in ent: ent = ent.split(' ')[1][:8]
            if z.get("duration_sec"):
                ext = str(z.get('exited_at','') or '')
                if 'T' in ext: ext = ext.split('T')[1][:8]
                elif ' ' in ext: ext = ext.split(' ')[1][:8]
                t += f"     ⏱ {ent} → {ext} (<b>{fmt_duration(z['duration_sec'])}</b>)\n"
            else:
                t += f"     ⏱ دخل {ent} — 🔴 لا يزال\n"

    t += "\n━━━━━━━━━━━━━━━"
    return t


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
        "/today": cmd_today,
        "/yesterday": cmd_yesterday,
        "/repeat": cmd_repeat,
    }

    if cmd == "/car":
        return cmd_car(arg)
    if cmd == "/date":
        return cmd_date(arg)
    if cmd in routes:
        try:
            return routes[cmd]()
        except Exception as e:
            return f"⚠️ صار خطأ: {e}"
    return None
