"""Vitals logic: reference-range flags (adult screening aids, not diagnoses) and Altair charts."""
import altair as alt
import pandas as pd

# ---- palette shared with ui.py -------------------------------------------------
TEAL, INDIGO, OK, WARN, ALERT = "#0F766E", "#6366F1", "#16A34A", "#D97706", "#DC2626"
MUTED, GRID = "#64748B", "#E2E8F0"

LEVEL_RANK = {"na": -1, "ok": 0, "warn": 1, "alert": 2}


def _has(x) -> bool:
    return x is not None and x == x  # excludes None and NaN


# ---- classification (adult ranges; BP per ACC/AHA 2017, BMI per Asian-Indian cut-offs) --------
def classify_bp(sys, dia):
    if sys >= 180 or dia >= 120:
        return "alert", "Crisis range"
    if sys < 90 or dia < 60:
        return ("alert", "Very low") if (sys < 80 or dia < 50) else ("warn", "Low")
    if sys >= 140 or dia >= 90:
        return "alert", "Stage 2 range"
    if sys >= 130 or dia >= 80:
        return "warn", "Stage 1 range"
    if sys >= 120:
        return "warn", "Elevated"
    return "ok", "Normal"


def classify_pulse(v):
    if v < 50 or v > 120:
        return "alert", "Abnormal"
    if v < 60:
        return "warn", "Low"
    if v > 100:
        return "warn", "High"
    return "ok", "Normal"


def classify_temp(c):
    if c >= 39.5:
        return "alert", "High fever"
    if c >= 38.0:
        return "warn", "Fever"
    if c >= 37.6:
        return "warn", "Low-grade"
    if c < 35.0:
        return "alert", "Hypothermia range"
    if c < 36.0:
        return "warn", "Low"
    return "ok", "Normal"


def classify_spo2(v):
    if v < 92:
        return "alert", "Low"
    if v < 95:
        return "warn", "Borderline"
    return "ok", "Normal"


def classify_rr(v):
    if v > 24 or v < 10:
        return "alert", "Abnormal"
    if v > 20 or v < 12:
        return "warn", "Borderline"
    return "ok", "Normal"


def classify_glucose(v, gtype):
    if v < 70:
        return "alert", "Low"
    if gtype == "Fasting":
        if v >= 126:
            return "alert", "Diabetic range"
        if v >= 100:
            return "warn", "Pre-diabetic range"
        return "ok", "Normal"
    if v >= 200:
        return "alert", "Diabetic range"
    if v >= 140:
        return "warn", "Raised"
    return "ok", "Normal"


def classify_bmi(b):
    if b < 18.5:
        return "warn", "Underweight"
    if b < 23:
        return "ok", "Healthy"
    if b < 25:
        return "warn", "Overweight"
    return "warn", "Obese range"


def classify_pain(v):
    if v >= 7:
        return "alert", "Severe"
    if v >= 4:
        return "warn", "Moderate"
    return "ok", "Mild/none"


def assess(row, age=None, bmi=None) -> dict:
    """metric -> (level, label). Under-18s get no flags: adult ranges do not apply to children."""
    if age is not None and age < 18:
        return {}
    out = {}
    if _has(row.get("bp_sys")) and _has(row.get("bp_dia")):
        out["bp"] = classify_bp(row["bp_sys"], row["bp_dia"])
    if _has(row.get("pulse")):
        out["pulse"] = classify_pulse(row["pulse"])
    if _has(row.get("temp_c")):
        out["temp_c"] = classify_temp(row["temp_c"])
    if _has(row.get("spo2")):
        out["spo2"] = classify_spo2(row["spo2"])
    if _has(row.get("resp_rate")):
        out["resp_rate"] = classify_rr(row["resp_rate"])
    if _has(row.get("glucose")):
        out["glucose"] = classify_glucose(row["glucose"], row.get("glucose_type") or "Random")
    if _has(bmi):
        out["bmi"] = classify_bmi(bmi)
    if _has(row.get("pain")):
        out["pain"] = classify_pain(row["pain"])
    return out


def worst(assessment: dict) -> str:
    if not assessment:
        return "na"
    return max((lvl for lvl, _ in assessment.values()), key=lambda l: LEVEL_RANK[l])


def bmi_value(weight_kg, height_cm):
    if _has(weight_kg) and _has(height_cm) and height_cm > 0:
        return round(weight_kg / (height_cm / 100) ** 2, 1)
    return None


def delta_text(cur, prev, decimals=0):
    if not (_has(cur) and _has(prev)):
        return ""
    d = round(cur - prev, decimals)
    if d == 0:
        return "no change"
    arrow = "▲" if d > 0 else "▼"
    return f"{arrow} {abs(d):.{decimals}f}"


def c_to_f(c):
    return c * 9 / 5 + 32


# ---- dataframe -----------------------------------------------------------------
def to_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["recorded_at"] = pd.to_datetime(df["recorded_at"])
    df = df.sort_values(["recorded_at", "id"]).reset_index(drop=True)
    df["height_used"] = df["height_cm"].ffill()  # height carried forward so BMI works on later readings
    df["bmi"] = (df["weight_kg"] / (df["height_used"] / 100) ** 2).round(1)
    df["glucose_type"] = df["glucose_type"].replace("", "Random").fillna("Random")
    return df


# ---- charts --------------------------------------------------------------------
def _x():
    return alt.X("recorded_at:T", axis=alt.Axis(title=None, format="%d %b", labelColor=MUTED, tickColor=GRID,
                                                domainColor=GRID, grid=False, labelOverlap=True))


def _yaxis(unit):
    return alt.Axis(title=unit, grid=True, gridColor=GRID, labelColor=MUTED, titleColor=MUTED, domain=False,
                    tickCount=5, titleFontWeight="normal")


def _domain(values, extras, pad_min=1.0):
    pts = list(values) + list(extras)
    lo, hi = min(pts), max(pts)
    pad = max((hi - lo) * 0.15, pad_min)
    return [lo - pad, hi + pad]


def _style(chart):
    return (chart.properties(height=215)
            .configure(font="Inter, Segoe UI, sans-serif")
            .configure_view(stroke=None)
            .configure_legend(orient="top", title=None, labelColor=MUTED, symbolType="circle")
            .configure_axis(labelFontSize=11, titleFontSize=11))


def _band(ysc, lo, hi, unit):
    """lo/hi may be scalars or lists (several shaded zones from one layer)."""
    lo, hi = (lo if isinstance(lo, list) else [lo]), (hi if isinstance(hi, list) else [hi])
    return (alt.Chart(pd.DataFrame({"lo": lo, "hi": hi}))
            .mark_rect(color=OK, opacity=0.11)
            .encode(y=alt.Y("lo:Q", scale=ysc, axis=_yaxis(unit)), y2="hi:Q"))


def _rule(ysc, v, unit):
    return (alt.Chart(pd.DataFrame({"v": [v]}))
            .mark_rule(color=ALERT, strokeDash=[5, 4], opacity=0.55)
            .encode(y=alt.Y("v:Q", scale=ysc, axis=_yaxis(unit))))


def _line(df, col, unit, bands=(), rules=(), color=TEAL, fixed_domain=None, decimals=0):
    d = df.dropna(subset=[col])
    if d.empty:
        return None
    extras = [b for band in bands for b in band] + list(rules)
    domain = fixed_domain or _domain(d[col], extras, pad_min=1.0)
    ysc = alt.Scale(domain=domain, nice=False, clamp=True)
    fmt = f".{decimals}f"
    base = alt.Chart(d[["recorded_at", col]])
    tip = [alt.Tooltip("recorded_at:T", title="When", format="%d %b %Y, %H:%M"),
           alt.Tooltip(f"{col}:Q", title=unit, format=fmt)]
    line = base.mark_line(color=color, strokeWidth=2.6, interpolate="monotone").encode(
        x=_x(), y=alt.Y(f"{col}:Q", scale=ysc, axis=_yaxis(unit)))
    pts = base.mark_point(filled=True, size=75, color=color, opacity=1, stroke="white", strokeWidth=1.5).encode(
        x=_x(), y=alt.Y(f"{col}:Q", scale=ysc, axis=_yaxis(unit)), tooltip=tip)
    layers = [_band(ysc, lo, hi, unit) for lo, hi in bands] + [_rule(ysc, r, unit) for r in rules] + [line, pts]
    return _style(alt.layer(*layers))


def _bp(df):
    d = df.dropna(subset=["bp_sys", "bp_dia"])
    if d.empty:
        return None
    long = d.melt(id_vars=["recorded_at"], value_vars=["bp_sys", "bp_dia"], var_name="s", value_name="mmHg")
    long["Series"] = long["s"].map({"bp_sys": "Systolic", "bp_dia": "Diastolic"})
    long = long[["recorded_at", "Series", "mmHg"]]
    domain = _domain(long["mmHg"], [60, 140], pad_min=5)
    ysc = alt.Scale(domain=domain, nice=False, clamp=True)
    cscale = alt.Scale(domain=["Systolic", "Diastolic"], range=[TEAL, INDIGO])
    base = alt.Chart(long)
    line = base.mark_line(strokeWidth=2.6, interpolate="monotone").encode(
        x=_x(), y=alt.Y("mmHg:Q", scale=ysc, axis=_yaxis("mmHg")), color=alt.Color("Series:N", scale=cscale))
    pts = base.mark_point(filled=True, size=75, opacity=1, stroke="white", strokeWidth=1.5).encode(
        x=_x(), y=alt.Y("mmHg:Q", scale=ysc, axis=_yaxis("mmHg")), color=alt.Color("Series:N", scale=cscale),
        tooltip=[alt.Tooltip("recorded_at:T", title="When", format="%d %b %Y, %H:%M"), "Series:N",
                 alt.Tooltip("mmHg:Q", format=".0f")])
    layers = [_band(ysc, [90, 60], [120, 80], "mmHg"), _rule(ysc, 140, "mmHg"), _rule(ysc, 90, "mmHg"), line, pts]
    return _style(alt.layer(*layers))


def _glucose(df):
    d = df.dropna(subset=["glucose"])
    if d.empty:
        return None
    d = d[["recorded_at", "glucose", "glucose_type"]]
    domain = _domain(d["glucose"], [70, 140], pad_min=10)
    ysc = alt.Scale(domain=domain, nice=False, clamp=True)
    sscale = alt.Scale(domain=["Random", "Fasting", "Post-meal (2h)"], range=["circle", "diamond", "square"])
    base = alt.Chart(d)
    line = base.mark_line(color=TEAL, strokeWidth=2.2, interpolate="monotone", opacity=0.7).encode(
        x=_x(), y=alt.Y("glucose:Q", scale=ysc, axis=_yaxis("mg/dL")))
    pts = base.mark_point(filled=True, size=95, color=TEAL, opacity=1, stroke="white", strokeWidth=1.5).encode(
        x=_x(), y=alt.Y("glucose:Q", scale=ysc, axis=_yaxis("mg/dL")), shape=alt.Shape("glucose_type:N", scale=sscale),
        tooltip=[alt.Tooltip("recorded_at:T", title="When", format="%d %b %Y, %H:%M"),
                 alt.Tooltip("glucose:Q", title="mg/dL", format=".0f"), alt.Tooltip("glucose_type:N", title="Type")])
    return _style(alt.layer(_band(ysc, 70, 140, "mg/dL"), line, pts))


def _pain(df):
    d = df.dropna(subset=["pain"])
    if d.empty:
        return None
    d = d[["recorded_at", "pain"]]
    ysc = alt.Scale(domain=[0, 10], nice=False)
    col = alt.Color("pain:Q", legend=None, scale=alt.Scale(domain=[0, 3, 6, 10], range=[OK, OK, WARN, ALERT]))
    bars = alt.Chart(d).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=22).encode(
        x=_x(), y=alt.Y("pain:Q", scale=ysc, axis=_yaxis("score /10")), color=col,
        tooltip=[alt.Tooltip("recorded_at:T", title="When", format="%d %b %Y, %H:%M"),
                 alt.Tooltip("pain:Q", title="Pain", format=".0f")])
    return _style(bars)


def build_charts(df: pd.DataFrame, temp_unit="C"):
    """Return [(key, title, chart)] for every measurement that has data."""
    if df.empty:
        return []
    d = df.copy()
    if temp_unit == "F":
        d["temp"] = c_to_f(d["temp_c"])
        tband, trules, tunit = [(c_to_f(36.0), c_to_f(37.5))], [c_to_f(38.0)], "°F"
    else:
        d["temp"] = d["temp_c"]
        tband, trules, tunit = [(36.0, 37.5)], [38.0], "°C"
    specs = [
        ("bp", "Blood pressure", _bp(d)),
        ("pulse", "Pulse", _line(d, "pulse", "beats/min", bands=[(60, 100)], color="#E11D48")),
        ("spo2", "Oxygen saturation (SpO₂)", _line(d, "spo2", "%", bands=[(95, 100)], color="#0284C7",
                                                    fixed_domain=[min(88, d["spo2"].min() - 2) if d["spo2"].notna().any() else 88, 101])),
        ("temp", "Temperature", _line(d, "temp", tunit, bands=tband, rules=trules, color="#EA580C", decimals=1)),
        ("resp", "Respiratory rate", _line(d, "resp_rate", "breaths/min", bands=[(12, 20)], color="#7C3AED")),
        ("glucose", "Blood glucose", _glucose(d)),
        ("weight", "Weight", _line(d, "weight_kg", "kg", color="#0D9488", decimals=1)),
        ("bmi", "BMI (Asian-Indian cut-offs)", _line(d, "bmi", "kg/m²", bands=[(18.5, 22.9)], rules=[25], color="#0F766E", decimals=1)),
        ("pain", "Pain score", _pain(d)),
    ]
    return [(k, t, c) for k, t, c in specs if c is not None]
