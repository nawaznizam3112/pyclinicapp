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
TREATMENT_STATUSES = ["Planned", "In progress", "Completed", "Declined"]
PAY_METHODS = ["Cash", "UPI", "Card", "Bank transfer", "Insurance"]
COMMON_PROCEDURES = ["Consultation", "Scaling & polishing", "Composite filling", "GIC filling", "Root canal treatment",
                     "Crown (PFM)", "Crown (zirconia)", "Extraction - simple", "Extraction - surgical", "Implant",
                     "Denture", "Orthodontic consultation", "Other"]

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
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS treatments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    tooth TEXT,
    procedure TEXT NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Planned',
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    amount REAL NOT NULL,
    method TEXT,
    note TEXT,
    at TEXT NOT NULL
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


# ---------- tooth notation (FDI) ----------
_PERMANENT = {f"{q}{n}" for q in "1234" for n in "12345678"}
_PRIMARY = {f"{q}{n}" for q in "5678" for n in "12345"}
VALID_FDI = _PERMANENT | _PRIMARY


def normalize_tooth(text: str) -> str:
    """'' = whole mouth / general. Otherwise comma-separated FDI numbers, validated."""
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    bad = [p for p in parts if p not in VALID_FDI]
    if bad:
        raise ValueError(f"Not valid FDI tooth number(s): {', '.join(bad)}")
    return ",".join(parts)


# ---------- users ----------
def count_users() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username, full_name, role, pw_hash):
    with conn() as c:
        c.execute("INSERT INTO users(username,full_name,role,pw_hash,created_at) VALUES(?,?,?,?,?)",
                  (username.strip().lower(), full_name.strip(), role, pw_hash, _now()))


def get_user(username):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        return dict(r) if r else None


def list_users():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, username, full_name, role, active, created_at FROM users ORDER BY username")]


def set_user_active(user_id, active: bool):
    with conn() as c:
        c.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))


def set_password(user_id, pw_hash):
    with conn() as c:
        c.execute("UPDATE users SET pw_hash=?, failed_count=0, locked_until=NULL WHERE id=?", (pw_hash, user_id))


def record_login_failure(username, max_failed=5, lock_minutes=10):
    from datetime import timedelta
    with conn() as c:
        c.execute("UPDATE users SET failed_count = failed_count + 1 WHERE username=?", (username.strip().lower(),))
        r = c.execute("SELECT failed_count FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        if r and r[0] >= max_failed:
            until = (datetime.now() + timedelta(minutes=lock_minutes)).isoformat(timespec="seconds")
            c.execute("UPDATE users SET locked_until=?, failed_count=0 WHERE username=?",
                      (until, username.strip().lower()))


def reset_login_failures(username):
    with conn() as c:
        c.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE username=?", (username.strip().lower(),))


# ---------- audit ----------
def log(actor, action, entity="", entity_id=None, detail=""):
    with conn() as c:
        c.execute("INSERT INTO audit_log(at,username,action,entity,entity_id,detail) VALUES(?,?,?,?,?,?)",
                  (_now(), actor, action, entity, entity_id, detail))


def list_audit(limit=500):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT at, username, action, entity, entity_id, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


# ---------- treatment plans ----------
def add_treatment(patient_id, tooth, procedure, fee):
    tooth = normalize_tooth(tooth)
    if fee < 0:
        raise ValueError("Fee cannot be negative")
    with conn() as c:
        cur = c.execute("INSERT INTO treatments(patient_id,tooth,procedure,fee,created_at) VALUES(?,?,?,?,?)",
                        (patient_id, tooth, procedure, float(fee), _now()))
        return cur.lastrowid


def list_treatments(patient_id):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM treatments WHERE patient_id=? ORDER BY id", (patient_id,))]


def set_treatment_status(treatment_id, status):
    with conn() as c:
        done = _now() if status == "Completed" else None
        c.execute("UPDATE treatments SET status=?, completed_at=? WHERE id=?", (status, done, treatment_id))


# ---------- billing ----------
def add_payment(patient_id, amount, method, note=""):
    if amount <= 0:
        raise ValueError("Payment must be greater than zero")
    with conn() as c:
        cur = c.execute("INSERT INTO payments(patient_id,amount,method,note,at) VALUES(?,?,?,?,?)",
                        (patient_id, float(amount), method, note, _now()))
        return cur.lastrowid


def list_payments(patient_id):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM payments WHERE patient_id=? ORDER BY id", (patient_id,))]


def patient_balance(patient_id) -> dict:
    """Billed = completed treatments only. Planned work is a quote, not a charge."""
    with conn() as c:
        billed = c.execute("SELECT COALESCE(SUM(fee),0) FROM treatments WHERE patient_id=? AND status='Completed'",
                           (patient_id,)).fetchone()[0]
        paid = c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE patient_id=?", (patient_id,)).fetchone()[0]
    return {"billed": billed, "paid": paid, "balance": billed - paid}


def outstanding_total() -> float:
    with conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM patients")]
    return sum(max(patient_balance(i)["balance"], 0) for i in ids)


