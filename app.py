import hmac
from datetime import datetime, time

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Clinic Manager", page_icon="🦷", layout="wide")
db.init_db()


# ---------- simple password gate (set APP_PASSWORD in .streamlit/secrets.toml) ----------
def check_password() -> bool:
    expected = st.secrets.get("APP_PASSWORD", "")
    if not expected:
        st.warning("No APP_PASSWORD set in secrets - running open (demo mode, use dummy data only).")
        return True
    if st.session_state.get("auth"):
        return True
    pw = st.text_input("Password", type="password")
    if pw and hmac.compare_digest(pw, expected):
        st.session_state["auth"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password")
    return False


if not check_password():
    st.stop()

page = st.sidebar.radio("Go to", ["Dashboard", "Patients", "Appointments", "Lab & Imaging Orders"])


def patient_picker(key):
    patients = db.list_patients()
    if not patients:
        st.info("Add a patient first.")
        return None
    labels = {f"{p['name']} (#{p['id']})": p["id"] for p in patients}
    return labels[st.selectbox("Patient", list(labels), key=key)]


# ---------- Dashboard ----------
if page == "Dashboard":
    st.title("Dashboard")
    orders = db.list_orders()
    open_orders = [o for o in orders if o["status"] != "Reviewed with patient"]
    waiting = [o for o in orders if o["status"] in ("Ordered", "Sent to lab", "In progress")]
    to_review = [o for o in orders if o["status"] == "Result received"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Open orders", len(open_orders))
    c2.metric("Awaiting results", len(waiting))
    c3.metric("Results to review", len(to_review))
    if to_review:
        st.subheader("Results waiting for your review")
        st.dataframe(pd.DataFrame(to_review)[["id", "patient", "test_type", "lab_name", "urgency"]],
                     hide_index=True, use_container_width=True)
    today = datetime.now().date().isoformat()
    todays = [a for a in db.list_appointments() if a["start_at"].startswith(today)]
    st.subheader("Today's appointments")
    if todays:
        st.dataframe(pd.DataFrame(todays), hide_index=True, use_container_width=True)
    else:
        st.caption("Nothing scheduled today.")

# ---------- Patients ----------
elif page == "Patients":
    st.title("Patients")
    with st.expander("Add patient", expanded=False):
        with st.form("add_patient", clear_on_submit=True):
            name = st.text_input("Full name *")
            phone = st.text_input("Phone")
            dob = st.date_input("Date of birth", value=None, min_value=datetime(1900, 1, 1))
            notes = st.text_area("Notes (allergies, medical flags)")
            if st.form_submit_button("Save") and name.strip():
                db.add_patient(name, phone, dob.isoformat() if dob else "", notes)
                st.success("Patient added")
                st.rerun()
    q = st.text_input("Search name or phone")
    rows = db.list_patients(q)
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["created_at"]), hide_index=True, use_container_width=True)
    else:
        st.caption("No patients yet.")

# ---------- Appointments ----------
elif page == "Appointments":
    st.title("Appointments")
    with st.expander("Book appointment"):
        pid = patient_picker("appt_patient")
        if pid:
            d = st.date_input("Date")
            t = st.time_input("Time", value=time(10, 0))
            proc = st.text_input("Procedure")
            notes = st.text_input("Notes")
            if st.button("Book"):
                db.add_appointment(pid, datetime.combine(d, t).isoformat(timespec="minutes"), proc, notes)
                st.success("Booked")
                st.rerun()
    appts = db.list_appointments()
    if appts:
        st.dataframe(pd.DataFrame(appts), hide_index=True, use_container_width=True)
        c1, c2, c3 = st.columns([1, 2, 1])
        aid = c1.number_input("Appointment #", min_value=1, step=1)
        new = c2.selectbox("New status", db.APPT_STATUSES)
        if c3.button("Update"):
            db.set_appointment_status(int(aid), new)
            st.rerun()

# ---------- Lab & Imaging Orders ----------
else:
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
                                           key=f"dl{o['id']}")
                st.dataframe(pd.DataFrame(db.order_history(o["id"])), hide_index=True)
                with st.form(f"upd{o['id']}"):
                    cur = db.STATUSES.index(o["status"])
                    new = st.selectbox("Update status", db.STATUSES, index=min(cur + 1, len(db.STATUSES) - 1))
                    note = st.text_input("Note")
                    summ = st.text_area("Result summary / findings (optional)")
                    up = st.file_uploader("Attach result (PDF/image)", type=["pdf", "png", "jpg", "jpeg"])
                    if st.form_submit_button("Save update"):
                        db.update_order(o["id"], new, note, up, summ)
                        st.rerun()
