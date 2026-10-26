from datetime import datetime, timedelta
from datetime import time as dtime

import pandas as pd
import streamlit as st

import auth
import db

st.set_page_config(page_title="Clinic Manager", page_icon="🦷", layout="wide")
db.init_db()

SESSION_TIMEOUT_MIN = 30


# =============================== authentication ===============================
def setup_screen():
    st.title("🦷 First-time setup")
    st.write("Create the administrator (dentist) account. You can add staff afterwards.")
    with st.form("setup"):
        full = st.text_input("Full name")
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        pw2 = st.text_input("Confirm password", type="password")
        if st.form_submit_button("Create admin account"):
            problem = auth.password_problem(pw)
            if not (full.strip() and user.strip()):
                st.error("Name and username are required.")
            elif pw != pw2:
                st.error("Passwords do not match.")
            elif problem:
                st.error(problem)
            else:
                db.create_user(user, full, "admin", auth.hash_password(pw))
                db.log(user.strip().lower(), "setup_admin", "user")
                st.success("Admin created. Log in to continue.")
                st.rerun()


def login_screen():
    st.title("🦷 Clinic Manager")
    if st.session_state.pop("timed_out", False):
        st.info("Logged out after inactivity.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if not submitted:
        return
    user = db.get_user(username)
    generic = "Invalid username or password."
    if not user or not user["active"]:
        st.error(generic)
        db.log(username.strip().lower(), "login_failed", "user", detail="unknown or inactive")
        return
    if user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > datetime.now():
        st.error(f"Account locked until {user['locked_until']} after repeated failures.")
        return
    if auth.verify_password(password, user["pw_hash"]):
        db.reset_login_failures(user["username"])
        st.session_state["user"] = {"username": user["username"], "full_name": user["full_name"],
                                    "role": user["role"], "id": user["id"]}
        st.session_state["last_active"] = datetime.now()
        db.log(user["username"], "login", "user", user["id"])
        st.rerun()
    else:
        db.record_login_failure(user["username"], auth.MAX_FAILED, auth.LOCK_MINUTES)
        db.log(user["username"], "login_failed", "user", user["id"], "bad password")
        st.error(generic)


def require_login() -> dict:
    if db.count_users() == 0:
        setup_screen()
        st.stop()
    user = st.session_state.get("user")
    if user:
        idle = datetime.now() - st.session_state.get("last_active", datetime.now())
        if idle > timedelta(minutes=SESSION_TIMEOUT_MIN):
            db.log(user["username"], "session_timeout", "user", user["id"])
            st.session_state.clear()
            st.session_state["timed_out"] = True
            st.rerun()
        st.session_state["last_active"] = datetime.now()
        return user
    login_screen()
    st.stop()


user = require_login()
actor = user["username"]

st.sidebar.markdown(f"**{user['full_name']}**  \n`{user['role']}`")
page = st.sidebar.radio("Go to", auth.pages_for(user["role"]))
if st.sidebar.button("Log out"):
    db.log(actor, "logout", "user", user["id"])
    st.session_state.clear()
    st.rerun()


# =============================== helpers ===============================
def patient_picker(key):
    patients = db.list_patients()
    if not patients:
        st.info("Add a patient first.")
        return None
    labels = {f"{p['name']} (#{p['id']})": p["id"] for p in patients}
    return labels[st.selectbox("Patient", list(labels), key=key)]


def money(x: float) -> str:
    return f"₹{x:,.2f}"


# =============================== pages ===============================
def page_dashboard():
    st.title("Dashboard")
    cols = st.columns(4)
    if user["role"] in ("admin", "assistant"):
        orders = db.list_orders()
        waiting = [o for o in orders if o["status"] in ("Ordered", "Sent to lab", "In progress")]
        to_review = [o for o in orders if o["status"] == "Result received"]
        cols[0].metric("Awaiting results", len(waiting))
        cols[1].metric("Results to review", len(to_review))
        if to_review:
            st.subheader("Results waiting for your review")
            st.dataframe(pd.DataFrame(to_review)[["id", "patient", "test_type", "lab_name", "urgency"]],
                         hide_index=True, width='stretch')
    if user["role"] in ("admin", "frontdesk"):
        cols[2].metric("Outstanding balances", money(db.outstanding_total()))
    today = datetime.now().date().isoformat()
    todays = [a for a in db.list_appointments() if a["start_at"].startswith(today)]
    cols[3].metric("Appointments today", len(todays))
    st.subheader("Today's appointments")
    if todays:
        st.dataframe(pd.DataFrame(todays), hide_index=True, width='stretch')
    else:
        st.caption("Nothing scheduled today.")


def page_patients():
    st.title("Patients")
    with st.expander("Add patient"):
        with st.form("add_patient", clear_on_submit=True):
            name = st.text_input("Full name *")
            phone = st.text_input("Phone")
            dob = st.date_input("Date of birth", value=None, min_value=datetime(1900, 1, 1))
            notes = st.text_area("Notes (allergies, medical flags)")
            if st.form_submit_button("Save") and name.strip():
                db.add_patient(name, phone, dob.isoformat() if dob else "", notes)
                db.log(actor, "create", "patient", detail=name.strip())
                st.success("Patient added")
                st.rerun()
    rows = db.list_patients(st.text_input("Search name or phone"))
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["created_at"]), hide_index=True, width='stretch')
    else:
        st.caption("No patients yet.")


def page_appointments():
    st.title("Appointments")
    with st.expander("Book appointment"):
        pid = patient_picker("appt_patient")
        if pid:
            d = st.date_input("Date")
            t = st.time_input("Time", value=dtime(10, 0))
            proc = st.text_input("Procedure")
            notes = st.text_input("Notes")
            if st.button("Book"):
                db.add_appointment(pid, datetime.combine(d, t).isoformat(timespec="minutes"), proc, notes)
                db.log(actor, "create", "appointment", pid)
                st.success("Booked")
                st.rerun()
    appts = db.list_appointments()
    if appts:
        st.dataframe(pd.DataFrame(appts), hide_index=True, width='stretch')
        c1, c2, c3 = st.columns([1, 2, 1])
        aid = c1.number_input("Appointment #", min_value=1, step=1)
        new = c2.selectbox("New status", db.APPT_STATUSES)
        if c3.button("Update"):
            db.set_appointment_status(int(aid), new)
            db.log(actor, "status", "appointment", int(aid), new)
            st.rerun()


def page_treatment():
    st.title("Treatment plans")
    pid = patient_picker("tx_patient")
    if not pid:
        return
    with st.expander("Add treatment item", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        proc = c1.selectbox("Procedure", db.COMMON_PROCEDURES)
        if proc == "Other":
            proc = c1.text_input("Describe procedure")
        tooth = c2.text_input("Tooth (FDI, e.g. 36 or 11,12; blank = general)")
        fee = c3.number_input("Fee (₹)", min_value=0.0, step=100.0)
        c4.write("")
        if c4.button("Add"):
            try:
                tid = db.add_treatment(pid, tooth, proc, fee)
                db.log(actor, "create", "treatment", tid, f"patient {pid}: {proc} {tooth}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    items = db.list_treatments(pid)
    if not items:
        st.caption("No treatments planned yet.")
        return
    total = sum(i["fee"] for i in items if i["status"] != "Declined")
    st.metric("Plan total (excluding declined)", money(total))
    for i in items:
        c1, c2, c3, c4 = st.columns([3, 1, 2, 1])
        c1.write(f"**{i['procedure']}**  \nTooth: {i['tooth'] or 'General'}")
        c2.write(money(i["fee"]))
        new = c3.selectbox("Status", db.TREATMENT_STATUSES, index=db.TREATMENT_STATUSES.index(i["status"]),
                           key=f"ts{i['id']}", label_visibility="collapsed")
        if c4.button("Save", key=f"tb{i['id']}") and new != i["status"]:
            db.set_treatment_status(i["id"], new)
            db.log(actor, "status", "treatment", i["id"], new)
            st.rerun()


def page_billing():
    st.title("Billing")
    pid = patient_picker("bill_patient")
    if not pid:
        return
    bal = db.patient_balance(pid)
    c1, c2, c3 = st.columns(3)
    c1.metric("Billed (completed work)", money(bal["billed"]))
    c2.metric("Paid", money(bal["paid"]))
    c3.metric("Balance due", money(bal["balance"]))
    with st.form("pay", clear_on_submit=True):
        a, b, n = st.columns([1, 1, 2])
        amount = a.number_input("Amount (₹)", min_value=0.0, step=100.0)
        method = b.selectbox("Method", db.PAY_METHODS)
        note = n.text_input("Note / reference")
        if st.form_submit_button("Record payment"):
            try:
                payid = db.add_payment(pid, amount, method, note)
                db.log(actor, "create", "payment", payid, f"patient {pid}: {amount} {method}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    done = [t for t in db.list_treatments(pid) if t["status"] == "Completed"]
    pays = db.list_payments(pid)
    ledger = ([{"date": t["completed_at"], "type": "Charge", "description": f"{t['procedure']} {t['tooth'] or ''}".strip(),
                "amount": t["fee"]} for t in done]
              + [{"date": p["at"], "type": "Payment", "description": f"{p['method']} {p['note'] or ''}".strip(),
                  "amount": -p["amount"]} for p in pays])
    if ledger:
        df = pd.DataFrame(sorted(ledger, key=lambda r: r["date"]))
        df["running balance"] = df["amount"].cumsum()
        st.dataframe(df, hide_index=True, width='stretch')
        st.download_button("Download statement (CSV)", df.to_csv(index=False), file_name=f"statement_{pid}.csv")


def page_orders():
    st.title("Diagnostic orders")
    tab_new, tab_track = st.tabs(["New order", "Track & receive results"])
    with tab_new:
        pid = patient_picker("order_patient")
        if pid:
            c1, c2, c3 = st.columns(3)
            test = c1.selectbox("Test", db.TEST_TYPES)
            lab = c2.text_input("Lab / imaging centre")
            urg = c3.selectbox("Urgency", db.URGENCY)
            notes = st.text_area("Clinical notes / reason for test")
            if st.button("Place order"):
                oid = db.create_order(pid, test, lab, urg, notes)
                db.log(actor, "create", "lab_order", oid, f"{test} urgency={urg}")
                st.success(f"Order #{oid} created")
                st.rerun()
    with tab_track:
        flt = st.selectbox("Filter by status", ["All"] + db.STATUSES)
        orders = db.list_orders(None if flt == "All" else flt)
        if not orders:
            st.caption("No orders.")
        for o in orders:
            flag = "🔴" if o["urgency"] == "Urgent" else "⚪"
            with st.expander(f"{flag} #{o['id']} - {o['patient']} - {o['test_type']} - {o['status']}"):
                st.write(f"**Lab:** {o['lab_name'] or '-'}  |  **Ordered:** {o['ordered_at']}")
                if o["result_summary"]:
                    st.info(o["result_summary"])
                if o["result_path"]:
                    with open(o["result_path"], "rb") as f:
                        st.download_button("Download result", f, file_name=o["result_path"].split("/")[-1],
                                           key=f"dl{o['id']}", on_click=db.log,
                                           args=(actor, "download_result", "lab_order", o["id"]))
                st.dataframe(pd.DataFrame(db.order_history(o["id"])), hide_index=True)
                with st.form(f"upd{o['id']}"):
                    cur = db.STATUSES.index(o["status"])
                    new = st.selectbox("Update status", db.STATUSES, index=min(cur + 1, len(db.STATUSES) - 1))
                    note = st.text_input("Note")
                    summ = st.text_area("Result summary / findings (optional)")
                    up = st.file_uploader("Attach result (PDF/image)", type=["pdf", "png", "jpg", "jpeg"])
                    if st.form_submit_button("Save update"):
                        db.update_order(o["id"], new, note, up, summ)
                        db.log(actor, "status", "lab_order", o["id"], new)
                        st.rerun()


def page_admin():
    st.title("Users & audit")
    tab_users, tab_audit = st.tabs(["Users", "Audit log"])
    with tab_users:
        st.dataframe(pd.DataFrame(db.list_users()), hide_index=True, width='stretch')
        with st.expander("Add staff member"):
            with st.form("add_user", clear_on_submit=True):
                full = st.text_input("Full name")
                uname = st.text_input("Username")
                role = st.selectbox("Role", auth.ROLES, index=1)
                pw = st.text_input("Temporary password", type="password")
                if st.form_submit_button("Create"):
                    problem = auth.password_problem(pw)
                    if not (full.strip() and uname.strip()):
                        st.error("Name and username required.")
                    elif problem:
                        st.error(problem)
                    elif db.get_user(uname):
                        st.error("Username already exists.")
                    else:
                        db.create_user(uname, full, role, auth.hash_password(pw))
                        db.log(actor, "create", "user", detail=f"{uname.strip().lower()} ({role})")
                        st.rerun()
        with st.expander("Reset password / deactivate"):
            users = {f"{u['username']} ({u['role']})": u for u in db.list_users()}
            sel = users[st.selectbox("User", list(users))]
            new_pw = st.text_input("New password", type="password", key="rp")
            c1, c2 = st.columns(2)
            if c1.button("Reset password"):
                problem = auth.password_problem(new_pw)
                if problem:
                    st.error(problem)
                else:
                    db.set_password(sel["id"], auth.hash_password(new_pw))
                    db.log(actor, "reset_password", "user", sel["id"])
                    st.success("Password reset.")
            label = "Deactivate" if sel["active"] else "Reactivate"
            if c2.button(label):
                if sel["id"] == user["id"]:
                    st.error("You cannot deactivate your own account.")
                else:
                    db.set_user_active(sel["id"], not sel["active"])
                    db.log(actor, label.lower(), "user", sel["id"])
                    st.rerun()
    with tab_audit:
        st.caption("Most recent 500 events. Records are append-only from the app.")
        st.dataframe(pd.DataFrame(db.list_audit()), hide_index=True, width='stretch')


PAGES = {
    "Dashboard": page_dashboard,
    "Patients": page_patients,
    "Appointments": page_appointments,
    "Treatment Plans": page_treatment,
    "Diagnostic Orders": page_orders,
    "Billing": page_billing,
    "Users & Audit": page_admin,
}
PAGES[page]()

