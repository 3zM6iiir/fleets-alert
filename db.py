"""
طبقة قاعدة البيانات - تدعم SQLite و PostgreSQL
"""
import os
import sqlite3
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = DATABASE_URL.startswith("postgres")

if USE_PG:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLITE_PATH = os.environ.get("SQLITE_PATH", "/tmp/fleet.db")


def get_conn():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(sql):
    """تحويل علامات الاستعلام حسب نوع قاعدة البيانات"""
    return sql.replace("?", "%s") if USE_PG else sql


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS speeding (
                id SERIAL PRIMARY KEY,
                vehicle TEXT NOT NULL,
                plate TEXT,
                driver TEXT,
                event_date DATE NOT NULL,
                max_speed REAL NOT NULL,
                road_limit REAL,
                lat REAL, lng REAL,
                address TEXT,
                event_count INTEGER DEFAULT 1,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                UNIQUE (vehicle, event_date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zone_visits (
                id SERIAL PRIMARY KEY,
                vehicle TEXT NOT NULL,
                plate TEXT,
                driver TEXT,
                zone TEXT NOT NULL,
                entered_at TIMESTAMP NOT NULL,
                exited_at TIMESTAMP,
                duration_sec INTEGER,
                enter_lat REAL, enter_lng REAL,
                exit_lat REAL, exit_lng REAL,
                engine_off INTEGER DEFAULT 0
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS speeding (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle TEXT NOT NULL,
                plate TEXT,
                driver TEXT,
                event_date TEXT NOT NULL,
                max_speed REAL NOT NULL,
                road_limit REAL,
                lat REAL, lng REAL,
                address TEXT,
                event_count INTEGER DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT,
                UNIQUE (vehicle, event_date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zone_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle TEXT NOT NULL,
                plate TEXT,
                driver TEXT,
                zone TEXT NOT NULL,
                entered_at TEXT NOT NULL,
                exited_at TEXT,
                duration_sec INTEGER,
                enter_lat REAL, enter_lng REAL,
                exit_lat REAL, exit_lng REAL,
                engine_off INTEGER DEFAULT 0
            )
        """)
    conn.commit()
    cur.close()
    conn.close()


def record_speeding(vehicle, plate, driver, speed, road_limit, lat, lng, address):
    """
    يسجل تجاوز سرعة. لو نفس المركبة سبق سجلت اليوم:
    - يحدّث السرعة القصوى فقط لو الجديدة أعلى
    - يزيد العداد
    يرجع: (is_new_record, previous_max) لمعرفة إذا كان رقم قياسي جديد
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    try:
        speed = float(str(speed).replace(",", ""))
    except:
        return False, None

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(q("SELECT max_speed, event_count FROM speeding WHERE vehicle=? AND event_date=?"),
                (vehicle, today))
    row = cur.fetchone()

    if row is None:
        cur.execute(q("""INSERT INTO speeding
            (vehicle, plate, driver, event_date, max_speed, road_limit, lat, lng, address,
             event_count, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""),
            (vehicle, plate, driver, today, speed, road_limit, lat, lng, address,
             1, now, now))
        conn.commit()
        cur.close(); conn.close()
        return True, None

    prev_max = float(row[0] if not USE_PG else row[0])
    if speed > prev_max:
        cur.execute(q("""UPDATE speeding SET max_speed=?, road_limit=?, lat=?, lng=?,
                      address=?, event_count=event_count+1, last_seen=?
                      WHERE vehicle=? AND event_date=?"""),
                    (speed, road_limit, lat, lng, address, now, vehicle, today))
        conn.commit(); cur.close(); conn.close()
        return True, prev_max
    else:
        cur.execute(q("""UPDATE speeding SET event_count=event_count+1, last_seen=?
                      WHERE vehicle=? AND event_date=?"""), (now, vehicle, today))
        conn.commit(); cur.close(); conn.close()
        return False, prev_max


def record_zone_enter(vehicle, plate, driver, zone, lat, lng):
    """يسجل دخول منطقة"""
    now = datetime.now()
    conn = get_conn(); cur = conn.cursor()
    # لو فيه دخول مفتوح بدون خروج لنفس المركبة والمنطقة، ما نكرر
    cur.execute(q("SELECT id FROM zone_visits WHERE vehicle=? AND zone=? AND exited_at IS NULL"),
                (vehicle, zone))
    if cur.fetchone():
        cur.close(); conn.close()
        return
    cur.execute(q("""INSERT INTO zone_visits
        (vehicle, plate, driver, zone, entered_at, enter_lat, enter_lng)
        VALUES (?,?,?,?,?,?,?)"""), (vehicle, plate, driver, zone, now, lat, lng))
    conn.commit(); cur.close(); conn.close()


def record_zone_exit(vehicle, zone, lat, lng):
    """يسجل الخروج ويحسب المدة. يرجع (entered_at, duration_sec) أو None"""
    now = datetime.now()
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q("""SELECT id, entered_at FROM zone_visits
                  WHERE vehicle=? AND zone=? AND exited_at IS NULL
                  ORDER BY id DESC LIMIT 1"""), (vehicle, zone))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return None

    visit_id, entered_at = row[0], row[1]
    if isinstance(entered_at, str):
        entered_at = datetime.fromisoformat(entered_at)
    duration = int((now - entered_at).total_seconds())

    cur.execute(q("""UPDATE zone_visits SET exited_at=?, duration_sec=?,
                  exit_lat=?, exit_lng=? WHERE id=?"""),
                (now, duration, lat, lng, visit_id))
    conn.commit(); cur.close(); conn.close()
    return entered_at, duration


def get_speeding_report(date=None, limit=100):
    conn = get_conn(); cur = conn.cursor()
    if date:
        cur.execute(q("""SELECT vehicle, plate, driver, event_date, max_speed, road_limit,
                      event_count, address, lat, lng FROM speeding
                      WHERE event_date=? ORDER BY max_speed DESC LIMIT ?"""), (date, limit))
    else:
        cur.execute(q("""SELECT vehicle, plate, driver, event_date, max_speed, road_limit,
                      event_count, address, lat, lng FROM speeding
                      ORDER BY event_date DESC, max_speed DESC LIMIT ?"""), (limit,))
    cols = ["vehicle","plate","driver","date","max_speed","road_limit","count","address","lat","lng"]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def get_zone_report(zone=None, limit=100):
    conn = get_conn(); cur = conn.cursor()
    if zone:
        cur.execute(q("""SELECT vehicle, plate, driver, zone, entered_at, exited_at,
                      duration_sec, enter_lat, enter_lng FROM zone_visits
                      WHERE zone=? ORDER BY entered_at DESC LIMIT ?"""), (zone, limit))
    else:
        cur.execute(q("""SELECT vehicle, plate, driver, zone, entered_at, exited_at,
                      duration_sec, enter_lat, enter_lng FROM zone_visits
                      ORDER BY entered_at DESC LIMIT ?"""), (limit,))
    cols = ["vehicle","plate","driver","zone","entered_at","exited_at","duration_sec","lat","lng"]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["entered_at"] = str(r["entered_at"])
        r["exited_at"] = str(r["exited_at"]) if r["exited_at"] else None
    cur.close(); conn.close()
    return rows
