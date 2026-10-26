"""SQLite data layer. Swap for Postgres/Supabase later without touching app.py."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "clinic.db"
RESULTS_DIR = DATA_DIR / "results"

# Lifecycle of a diagnostic order
STATUSES = ["Ordered", "Sent to lab", "In progress", "Result received", "Reviewed with patient"]
TEST_TYPES = ["OPG", "CBCT", "IOPA", "Bitewing", "Blood - HbA1c", "Blood - CBC", "Blood - BT/CT", "Biopsy", "Other"]
URGENCY = ["Routine", "Urgent"]
APPT_STATUSES = ["Scheduled", "Completed", "Cancelled", "No-show"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    dob TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    start_at TEXT NOT NULL,
    procedure TEXT,
    status TEXT NOT NULL DEFAULT 'Scheduled',
    notes TEXT
);
CREATE TABLE IF NOT EXISTS lab_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    test_type TEXT NOT NULL,
    lab_name TEXT,
    urgency TEXT NOT NULL DEFAULT 'Routine',
    clinical_notes TEXT,
    status TEXT NOT NULL DEFAULT 'Ordered',
    result_path TEXT,
    result_summary TEXT,
    ordered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES lab_orders(id),
    status TEXT NOT NULL,
    note TEXT,
    at TEXT NOT NULL
);
"""

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

@contextmanager
def conn():
    DATA_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript(SCHEMA)

# ---------- patients ----------
def add_patient(name, phone="", dob="", notes=""):
    with conn() as c:
        c.execute("INSERT INTO patients(name,phone,dob,notes,created_at) VALUES(?,?,?,?,?)",
                  (name.strip(), phone.strip(), dob, notes.strip(), _now()))

def list_patients(search=""):
    with conn() as c:
        q = "SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? ORDER BY name"
        return [dict(r) for r in c.execute(q, (f"%{search}%", f"%{search}%"))]

# ---------- appointments ----------
def add_appointment(patient_id, start_at, procedure="", notes=""):
    with conn() as c:
        c.execute("INSERT INTO appointments(patient_id,start_at,procedure,notes) VALUES(?,?,?,?)",
                  (patient_id, start_at, procedure, notes))

def list_appointments():
    with conn() as c:
        q = """SELECT a.id, p.name AS patient, a.start_at, a.procedure, a.status, a.notes
               FROM appointments a JOIN patients p ON p.id = a.patient_id
               ORDER BY a.start_at"""
        return [dict(r) for r in c.execute(q)]

def set_appointment_status(appt_id, status):
    with conn() as c:
        c.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))

# ---------- lab orders ----------
def create_order(patient_id, test_type, lab_name, urgency, clinical_notes):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO lab_orders(patient_id,test_type,lab_name,urgency,clinical_notes,ordered_at) "
            "VALUES(?,?,?,?,?,?)",
            (patient_id, test_type, lab_name, urgency, clinical_notes, _now()))
        c.execute("INSERT INTO order_events(order_id,status,note,at) VALUES(?,?,?,?)",
                  (cur.lastrowid, "Ordered", "Order created", _now()))
        return cur.lastrowid

def list_orders(status=None):
    with conn() as c:
        q = """SELECT o.id, p.name AS patient, o.test_type, o.lab_name, o.urgency,
                      o.status, o.ordered_at, o.result_path, o.result_summary
               FROM lab_orders o JOIN patients p ON p.id = o.patient_id"""
        args = ()
        if status:
            q += " WHERE o.status = ?"
            args = (status,)
        q += " ORDER BY (o.urgency='Urgent') DESC, o.ordered_at DESC"
        return [dict(r) for r in c.execute(q, args)]

def update_order(order_id, status, note="", result_file=None, result_summary=None):
    with conn() as c:
        if result_file is not None:
            path = RESULTS_DIR / f"order{order_id}_{result_file.name}"
            path.write_bytes(result_file.getbuffer())
            c.execute("UPDATE lab_orders SET result_path=? WHERE id=?", (str(path), order_id))
        if result_summary:
            c.execute("UPDATE lab_orders SET result_summary=? WHERE id=?", (result_summary, order_id))
        c.execute("UPDATE lab_orders SET status=? WHERE id=?", (status, order_id))
        c.execute("INSERT INTO order_events(order_id,status,note,at) VALUES(?,?,?,?)",
                  (order_id, status, note, _now()))

def order_history(order_id):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT status, note, at FROM order_events WHERE order_id=? ORDER BY id", (order_id,))]
