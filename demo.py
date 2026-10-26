"""Synthetic demo data so you can see the charts and layout straight away. Run: python demo.py
Every demo patient is named '[Demo] ...' and can be removed from Admin > Clinic settings."""
import random
from datetime import datetime, timedelta

import db

PEOPLE = [
    # name, sex, age, blood group, trend profile
    ("[Demo] Asha Rao", "Female", 58, "B+", "hypertensive"),
    ("[Demo] Mohammed Irfan", "Male", 46, "O+", "diabetic"),
    ("[Demo] Priya Nair", "Female", 31, "A+", "fever"),
    ("[Demo] Suresh Kumar", "Male", 67, "AB+", "cardiac"),
    ("[Demo] Kavya Reddy", "Female", 29, "O-", "healthy"),
    ("[Demo] Arjun (child)", "Male", 9, "B+", "child"),
]


def _series(profile, i, n, rng):
    f = i / max(n - 1, 1)  # 0 -> 1 across the period
    if profile == "hypertensive":
        sys, dia = 158 - 26 * f + rng.gauss(0, 4), 98 - 14 * f + rng.gauss(0, 3)
        return dict(bp_sys=round(sys), bp_dia=round(dia), pulse=round(84 - 8 * f + rng.gauss(0, 3)),
                    spo2=rng.choice([97, 98, 98, 99]), weight_kg=round(78 - 2.5 * f + rng.gauss(0, .3), 1))
    if profile == "diabetic":
        g = 210 - 70 * f + rng.gauss(0, 14)
        return dict(glucose=round(g), glucose_type=rng.choice(["Fasting", "Post-meal (2h)", "Random"]),
                    bp_sys=round(132 + rng.gauss(0, 5)), bp_dia=round(84 + rng.gauss(0, 3)),
                    weight_kg=round(88 - 3 * f + rng.gauss(0, .3), 1), pulse=round(78 + rng.gauss(0, 4)))
    if profile == "fever":
        t = 39.6 - 2.6 * f + rng.gauss(0, .25) if f < .85 else 36.8 + rng.gauss(0, .15)
        return dict(temp_c=round(t, 1), pulse=round(72 + (t - 36.8) * 14 + rng.gauss(0, 3)),
                    spo2=rng.choice([96, 97, 98]), resp_rate=round(16 + (t - 36.8) * 1.6))
    if profile == "cardiac":
        return dict(bp_sys=round(148 + rng.gauss(0, 7)), bp_dia=round(90 + rng.gauss(0, 4)),
                    pulse=round(96 + 10 * (1 - f) + rng.gauss(0, 5)), spo2=round(94 + 3 * f + rng.gauss(0, 1)),
                    resp_rate=round(21 - 3 * f + rng.gauss(0, 1)))
    if profile == "child":
        return dict(temp_c=round(37.2 + rng.gauss(0, .3), 1), pulse=round(92 + rng.gauss(0, 6)),
                    weight_kg=round(27 + 0.15 * f * 5 + rng.gauss(0, .1), 1), spo2=rng.choice([98, 99]))
    return dict(bp_sys=round(116 + rng.gauss(0, 4)), bp_dia=round(74 + rng.gauss(0, 3)), pulse=round(70 + rng.gauss(0, 4)),
                spo2=rng.choice([98, 99, 99]), weight_kg=round(58 + rng.gauss(0, .3), 1), pain=rng.choice([0, 0, 1]))


def seed(days=30, readings=9, actor="demo"):
    rng = random.Random(7)
    db.init_db()
    now = datetime.now()
    for name, sex, age, bg, profile in PEOPLE:
        dob = (now - timedelta(days=age * 365 + 120)).date().isoformat()
        pid = db.add_patient(name, "9000000000", dob, "", sex, bg, "Penicillin" if profile == "cardiac" else "")
        height = 128 if profile == "child" else rng.choice([158, 164, 171, 176])
        n = 3 if profile == "child" else readings
        for i in range(n):
            when = (now - timedelta(days=days * (1 - i / max(n - 1, 1)), hours=rng.randint(0, 3))).replace(microsecond=0)
            if i == n - 1:
                when = now - timedelta(minutes=25)
            vals = _series(profile, i, n, rng)
            if i == 0:
                vals["height_cm"] = height
                vals.setdefault("weight_kg", 70)
            db.add_vitals(pid, actor, when.isoformat(timespec="seconds"), vals.pop("glucose_type", ""), "", **vals)
    return len(PEOPLE)


if __name__ == "__main__":
    print(f"Seeded {seed()} demo patients.")
