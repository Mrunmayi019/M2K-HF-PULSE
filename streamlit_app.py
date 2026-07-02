import html
import os
import textwrap
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.analytics import analyze
from src.generator import create_scenario
from src.rules import detect_condition
from src.run import run_pulse


st.set_page_config(page_title="PulseDock Dashboard", layout="wide")

st.markdown("""
<style>
:root {
    --bg: #020617;
    --surface: #0f172a;
    --surface-2: #111827;
    --muted: #94a3b8;
    --text: #e2e8f0;
    --title: #f8fafc;
    --border: #1e293b;
    --shadow: 0 12px 32px rgba(2, 6, 23, 0.35);
    --teal: #14b8a6;
    --green: #22c55e;
    --yellow: #eab308;
    --orange: #f97316;
    --red: #ef4444;
    --blue: #3b82f6;
    --blue-soft: #93c5fd;
}

.stApp {
    background:
        radial-gradient(circle at top, rgba(20, 184, 166, 0.12), transparent 30%),
        linear-gradient(180deg, #020617 0%, #07111f 45%, #020617 100%);
}

[data-testid="stMainBlockContainer"], .block-container {
    max-width: 1100px;
    padding-top: 1.6rem;
    padding-bottom: 4rem;
    padding-left: 1.25rem;
    padding-right: 1.25rem;
}

h1, h2, h3, p, div, span, label {
    font-family: Inter, system-ui, sans-serif;
}

.dashboard-title {
    font-size: 28px;
    font-weight: 700;
    color: var(--title);
    margin-bottom: 0.4rem;
}

.dashboard-subtitle {
    font-size: 15px;
    color: var(--muted);
    margin-bottom: 1.5rem;
}

[data-testid="stForm"] {
    background: rgba(15, 23, 42, 0.92);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 1rem 1rem 0.4rem 1rem;
    box-shadow: var(--shadow);
}

.section-shell {
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.1rem 1.2rem 1.25rem 1.2rem;
    box-shadow: var(--shadow);
    position: relative;
    overflow: hidden;
    margin-top: 1.5rem;
    animation: fadeUp 0.4s ease both;
}

.section-shell::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--teal), rgba(20, 184, 166, 0.08));
}

.section-title {
    font-size: 20px;
    font-weight: 600;
    color: var(--title);
    margin-bottom: 0.25rem;
}

.section-subtitle {
    font-size: 14px;
    color: var(--muted);
    margin-bottom: 1rem;
}

.hero-card {
    border-radius: 20px;
    padding: 1.5rem;
    border: 1px solid rgba(255,255,255,0.06);
    border-left: 4px solid;
    box-shadow: 0 16px 40px rgba(0,0,0,0.24);
    animation: fadeUp 0.4s ease both;
}

.hero-low {
    background: linear-gradient(180deg, rgba(34, 197, 94, 0.16), rgba(15, 23, 42, 0.9));
    border-left-color: var(--green);
    box-shadow: 0 0 30px rgba(34, 197, 94, 0.18);
}

.hero-moderate {
    background: linear-gradient(180deg, rgba(234, 179, 8, 0.16), rgba(15, 23, 42, 0.9));
    border-left-color: var(--yellow);
    box-shadow: 0 0 30px rgba(234, 179, 8, 0.16);
}

.hero-high {
    background: linear-gradient(180deg, rgba(239, 68, 68, 0.2), rgba(15, 23, 42, 0.92));
    border-left-color: var(--red);
    box-shadow: 0 0 34px rgba(239, 68, 68, 0.24);
}

.pulse {
    animation: pulseGlow 1.8s ease-in-out infinite;
}

.hero-status {
    font-size: 48px;
    font-weight: 800;
    color: var(--title);
    line-height: 1.05;
    text-align: center;
}

.hero-summary {
    font-size: 15px;
    color: #cbd5e1;
    text-align: center;
    margin-top: 0.5rem;
}

.badge-row {
    display: flex;
    gap: 0.5rem;
    justify-content: center;
    flex-wrap: wrap;
    margin-top: 1rem;
}

.pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.8rem;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    border: 1px solid rgba(255,255,255,0.08);
}

.pill-low { background: rgba(34, 197, 94, 0.16); color: #bbf7d0; }
.pill-moderate { background: rgba(234, 179, 8, 0.16); color: #fde68a; }
.pill-high { background: rgba(239, 68, 68, 0.16); color: #fecaca; }
.pill-stage { background: rgba(59, 130, 246, 0.16); color: #bfdbfe; }

.info-card, .metric-card, .sub-card, .report-card {
    background: rgba(17, 24, 39, 0.85);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1rem;
    height: 100%;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.info-card:hover, .metric-card:hover, .sub-card:hover, .report-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.35);
}

.eyebrow {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 0.4rem;
}

.info-title {
    font-size: 18px;
    color: var(--title);
    font-weight: 700;
    margin-bottom: 0.35rem;
}

.info-copy {
    color: #cbd5e1;
    font-size: 14px;
    line-height: 1.55;
}

.metric-icon {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    margin-bottom: 0.75rem;
}

.metric-value {
    font-size: 42px;
    line-height: 1;
    font-weight: 800;
    color: var(--title);
}

.metric-label {
    font-size: 12px;
    color: var(--muted);
    margin-top: 0.25rem;
}

.metric-trend {
    font-size: 14px;
    font-weight: 700;
    margin-top: 0.6rem;
}

.trend-up { color: #fca5a5; }
.trend-flat { color: #cbd5e1; }
.trend-down { color: #86efac; }

.bullet-box {
    background: rgba(2, 6, 23, 0.45);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 0.85rem 1rem;
}

.bullet-box ul {
    margin: 0.4rem 0 0 1.1rem;
    color: #cbd5e1;
}

.bullet-box li {
    margin-bottom: 0.35rem;
}

.styled-table {
    width: 100%;
    border-collapse: collapse;
    overflow: hidden;
    border-radius: 14px;
    border: 1px solid var(--border);
}

.table-wrap {
    width: 100%;
    overflow-x: auto;
    border-radius: 14px;
}

.styled-table th {
    background: rgba(30, 41, 59, 0.92);
    color: var(--title);
    padding: 0.85rem;
    text-align: left;
    font-size: 13px;
}

.styled-table td {
    padding: 0.8rem 0.85rem;
    color: #dbeafe;
    border-top: 1px solid rgba(148, 163, 184, 0.08);
    font-size: 14px;
}

.styled-table tr:nth-child(even) td {
    background: rgba(15, 23, 42, 0.65);
}

.dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 0.45rem;
}

.progress-track {
    width: 100%;
    background: rgba(148, 163, 184, 0.18);
    border-radius: 999px;
    overflow: hidden;
    height: 14px;
    border: 1px solid rgba(148, 163, 184, 0.12);
}

.progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--green) 0%, var(--yellow) 60%, var(--red) 100%);
}

.recommendation {
    border-left: 4px solid;
    border-radius: 16px;
    padding: 1rem 1.1rem;
    background: rgba(2, 6, 23, 0.48);
    border: 1px solid var(--border);
}

.recommendation-low { border-left-color: var(--green); }
.recommendation-moderate { border-left-color: var(--yellow); }
.recommendation-high { border-left-color: var(--red); }

.report-pre {
    white-space: pre-wrap;
    color: #dbeafe;
    font-size: 13px;
    line-height: 1.6;
    margin: 0;
}

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes pulseGlow {
    0%, 100% { box-shadow: 0 0 22px rgba(239, 68, 68, 0.18); }
    50% { box-shadow: 0 0 40px rgba(239, 68, 68, 0.34); }
}

@media (max-width: 992px) {
    [data-testid="stMainBlockContainer"], .block-container {
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }
    .hero-status {
        font-size: 36px;
    }
    .metric-value {
        font-size: 34px;
    }
}
</style>
""", unsafe_allow_html=True)


CONDITION_LABELS = {
    "normal": "Stable Physiological State",
    "heart_failure": "Possible Heart Failure Pattern",
    "hypoxia": "Hypoxic Pattern",
}

CONDITION_DETAILS = {
    "normal": ("🫀", "Stable circulation with no strong signs of deterioration."),
    "heart_failure": ("🫀", "Fluid buildup pattern detected. Your heart is compensating."),
    "hypoxia": ("🫁", "Oxygen delivery is reduced and needs closer monitoring."),
}

STAGE_DESCRIPTIONS = {
    "A": "Risk factors present, but no clear structural heart failure pattern yet.",
    "B": "Early structural change or strain may be emerging.",
    "C": "Current physiology is consistent with symptomatic heart failure.",
    "D": "Advanced decompensation pattern with urgent attention needed.",
}

NYHA_DESCRIPTIONS = {
    "I": "No limitation of normal activity.",
    "II": "Slight limitation of activity.",
    "III": "Marked limitation with routine activity.",
    "IV": "Symptoms may occur even at rest.",
}

RISK_UI = {
    "LOW": {
        "class": "low",
        "label": "You're Healthy!",
        "emoji": "🟢",
        "summary": "Your heart is stable. No signs of deterioration detected.",
        "pill_class": "pill-low",
        "dot": "#22c55e",
        "card_class": "hero-low",
    },
    "MODERATE": {
        "class": "moderate",
        "label": "Watch Closely",
        "emoji": "🟡",
        "summary": "Early stress pattern detected. Closer monitoring is recommended.",
        "pill_class": "pill-moderate",
        "dot": "#eab308",
        "card_class": "hero-moderate",
    },
    "HIGH": {
        "class": "high",
        "label": "High Risk - Act Now",
        "emoji": "🔴",
        "summary": "Your body is showing a concerning deterioration pattern that needs attention.",
        "pill_class": "pill-high",
        "dot": "#ef4444",
        "card_class": "hero-high pulse",
    },
}


def clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def pick_column(df, options):
    for option in options:
        if option in df.columns:
            return option
    lowered = {col.lower(): col for col in df.columns}
    for option in options:
        for lowered_col, original in lowered.items():
            if option.lower() in lowered_col:
                return original
    return None


def load_simulation_snapshot(csv_path):
    if not os.path.exists(csv_path):
        return {}

    df = pd.read_csv(csv_path)
    if df.empty:
        return {}

    last = df.iloc[-1]

    co_col = pick_column(df, ["CardiacOutput(L/min)", "CardiacOutput"])
    sv_col = pick_column(df, ["StrokeVolume(mL)", "StrokeVolume"])

    cardiac_output = float(last[co_col]) if co_col else None
    stroke_volume = float(last[sv_col]) if sv_col else None

    hr_col = pick_column(df, ["HeartRate(1/min)", "HeartRate"])
    hr_value = float(last[hr_col]) if hr_col else None
    if stroke_volume is None and cardiac_output is not None and hr_value:
        stroke_volume = (cardiac_output * 1000.0) / hr_value

    return {
        "cardiac_output": cardiac_output,
        "stroke_volume": stroke_volume,
    }


def classify_nyha(features, risk):
    hr = features["hr"]
    o2 = features["o2"]
    map_val = features["map"]

    if risk == "HIGH" or hr >= 110 or o2 < 0.90 or map_val < 70:
        return "IV"
    if risk == "MODERATE" or hr >= 95 or o2 < 0.94 or map_val < 80:
        return "III"
    if hr >= 85 or o2 < 0.97:
        return "II"
    return "I"


def get_stage_color(stage):
    return {
        "A": "#22c55e",
        "B": "#eab308",
        "C": "#f97316",
        "D": "#ef4444",
    }.get(stage, "#94a3b8")


def risk_score_ratio(analysis):
    return clamp(float(analysis.get("score", 0)) / 12.0)


def hero_summary(condition, risk, driver):
    if risk == "LOW":
        return "Your heart is stable. No signs of deterioration detected."
    if condition == "heart_failure":
        return "Fluid buildup pattern detected. Your heart is compensating."
    if condition == "hypoxia":
        return "Lower oxygen delivery suggests your body is under stress."
    if driver != "Stable":
        return f"Most concern comes from {driver.lower()}."
    return RISK_UI[risk]["summary"]


def get_metric_direction(rate, metric_name):
    if abs(rate) < 0.01:
        return "→ Stable", "trend-flat"
    if metric_name == "SpO2":
        return ("↓ Falling", "trend-up") if rate < 0 else ("↑ Improving", "trend-down")
    return ("↑ Rising", "trend-up") if rate > 0 else ("↓ Falling", "trend-down")


def metric_status(metric_name, value):
    if metric_name == "Heart Rate":
        if value > 100:
            return "Compensating", "pill-high"
        if value >= 90:
            return "Elevated", "pill-moderate"
        return "Normal", "pill-low"
    if metric_name == "SpO2":
        if value < 94:
            return "Low", "pill-high"
        if value < 97:
            return "Borderline", "pill-moderate"
        return "Normal", "pill-low"
    if value < 70:
        return "Low Perfusion", "pill-high"
    if value < 80:
        return "Borderline", "pill-moderate"
    return "Normal", "pill-low"


def explain(features):
    hr = features["hr"]
    o2 = features["o2"]
    map_val = features["map"]
    msgs = []

    msgs.append("Heart rate is within target range." if 60 <= hr <= 100 else "Heart rate is elevated, suggesting compensation.")
    msgs.append("Oxygen saturation remains stable." if o2 >= 0.95 else "Oxygen saturation is reduced, suggesting lower reserve.")
    msgs.append("Mean arterial pressure is preserving organ perfusion." if 70 <= map_val <= 100 else "Perfusion pressure is outside the preferred range.")

    if features["hr_rate"] > 0.01:
        msgs.append("Heart rate is trending upward over the simulation window.")
    if features["o2_rate"] < -0.0005:
        msgs.append("Oxygen levels are drifting downward over time.")
    if features["map_rate"] < -0.01:
        msgs.append("Blood pressure support is slowly weakening.")

    if len(msgs) < 4:
        msgs.append("No strong signs of rapid deterioration were detected in the simulation output.")

    return msgs


def build_vitals_table(today_inputs, features, simulation, feature_rates):
    rows = [
        {
            "vital": "Heart Rate",
            "today": f"{today_inputs['hr']:.0f} bpm",
            "trend": trend_markup(feature_rates["hr_rate"], "Heart Rate"),
            "simulation": status_markup(f"{features['hr']:.1f} bpm", metric_status("Heart Rate", features["hr"])[0]),
        },
        {
            "vital": "SpO2",
            "today": f"{today_inputs['spo2']:.0f}%",
            "trend": trend_markup(feature_rates["o2_rate"], "SpO2"),
            "simulation": status_markup(f"{features['o2'] * 100:.1f}%", metric_status("SpO2", features["o2"] * 100)[0]),
        },
        {
            "vital": "MAP",
            "today": f"{today_inputs['bp'] * 0.78:.1f}",
            "trend": trend_markup(feature_rates["map_rate"], "MAP"),
            "simulation": status_markup(f"{features['map']:.1f}", metric_status("MAP", features["map"])[0]),
        },
        {
            "vital": "Cardiac Output",
            "today": "—",
            "trend": "—",
            "simulation": status_markup(value_or_dash(simulation.get("cardiac_output"), "L/min"), "Normal" if (simulation.get("cardiac_output") or 0) >= 4 else "Borderline"),
        },
        {
            "vital": "Stroke Volume",
            "today": "—",
            "trend": "—",
            "simulation": status_markup(value_or_dash(simulation.get("stroke_volume"), "mL"), "Normal" if (simulation.get("stroke_volume") or 0) >= 60 else "Borderline"),
        },
    ]

    html_rows = "".join(
        f"""
        <tr>
            <td>{row['vital']}</td>
            <td>{row['today']}</td>
            <td>{row['trend']}</td>
            <td>{row['simulation']}</td>
        </tr>
        """
        for row in rows
    )

    return textwrap.dedent(
        f"""
        <div class="table-wrap">
            <table class="styled-table">
                <thead>
                    <tr>
                        <th>Vital</th>
                        <th>Today (Input Value)</th>
                        <th>Trend</th>
                        <th>Simulation Output</th>
                    </tr>
                </thead>
                <tbody>{html_rows}</tbody>
            </table>
        </div>
        """
    ).strip()


def value_or_dash(value, suffix="", decimals=1):
    if value is None:
        return "—"
    return f"{value:.{decimals}f} {suffix}".strip()


def trend_markup(rate, metric_name):
    if rate == 0:
        return '<span class="trend-flat"><span class="dot" style="background:#94a3b8;"></span>→ Stable</span>'
    label, css_class = get_metric_direction(rate, metric_name)
    color = "#ef4444" if css_class == "trend-up" else "#22c55e" if css_class == "trend-down" else "#94a3b8"
    return f'<span class="{css_class}"><span class="dot" style="background:{color};"></span>{label}</span>'


def status_markup(value_text, status):
    if status in {"Normal", "Stable"}:
        color = "#22c55e"
    elif status in {"Borderline", "Elevated"}:
        color = "#eab308"
    else:
        color = "#ef4444"
    return f'<span><span class="dot" style="background:{color};"></span>{value_text}</span>'


def current_value_color(features):
    if features["o2"] < 0.94 or features["map"] < 80 or features["hr"] > 100:
        return "#ef4444"
    if features["o2"] < 0.97 or features["map"] < 85 or features["hr"] > 90:
        return "#f97316"
    return "#ec4899"


def comparison_graph(features):
    metrics = ["HR", "SpO2", "MAP"]
    normal = [80, 98, 90]
    hf = [110, 92, 65]
    current = [features["hr"], features["o2"] * 100, features["map"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Normal Range", x=metrics, y=normal, marker_color="#3b82f6"))
    fig.add_trace(go.Bar(name="HF Patient Baseline", x=metrics, y=hf, marker_color="#93c5fd"))
    fig.add_trace(go.Bar(name="Your Current Value", x=metrics, y=current, marker_color=current_value_color(features)))

    fig.update_layout(
        barmode="group",
        height=380,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.65)",
        font=dict(color="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis=dict(gridcolor="rgba(148, 163, 184, 0.12)", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    return fig


def build_projection_table(features, analysis, severity, simulation):
    current_co = simulation.get("cardiac_output") or 5.0
    map_now = features["map"]
    hr_now = features["hr"]
    stage_order = ["A", "B", "C", "D"]

    hr_step = max(1.5, abs(features["hr_rate"]) * 70, severity * 7)
    map_step = max(1.0, abs(features["map_rate"]) * 85, severity * 5)
    co_step = max(0.15, severity * 0.45, map_step * 0.025)

    projections = [
        ("Now", current_co, hr_now, map_now),
        ("+7 days", max(0.1, current_co - co_step * 0.8), analysis["forecast"]["7d"]["hr"], max(40.0, map_now - map_step * 0.8)),
        ("+14 days", max(0.1, current_co - co_step * 1.5), analysis["forecast"]["14d"]["hr"], max(35.0, map_now - map_step * 1.4)),
        ("+30 days", max(0.1, current_co - co_step * 2.4), analysis["forecast"]["30d"]["hr"], max(30.0, map_now - map_step * 2.4)),
    ]

    rows = []
    for label, co_val, hr_val, map_val in projections:
        derived_features = {
            "hr": hr_val,
            "o2": features["o2"],
            "map": map_val,
            "hr_rate": features["hr_rate"],
            "o2_rate": features["o2_rate"],
            "map_rate": features["map_rate"],
        }
        risk_label = derive_risk_label(derived_features)
        rows.append(
            {
                "time": label,
                "co": f"{co_val:.1f} L/min",
                "hr": f"{hr_val:.1f}",
                "map": f"{map_val:.1f}",
                "risk": risk_label,
            }
        )

    current_stage = analysis["stage"]
    current_idx = stage_order.index(current_stage)
    next_stage = stage_order[min(current_idx + 1, len(stage_order) - 1)]

    transition_probability = clamp(
        (risk_score_ratio(analysis) * 0.55) +
        (severity * 0.25) +
        (max(0.0, features["hr_rate"]) * 0.1) +
        (max(0.0, -features["map_rate"]) * 0.02),
        0.04,
        0.95,
    )

    return {
        "rows": rows,
        "current_stage": current_stage,
        "next_stage": next_stage,
        "transition_probability": transition_probability,
    }


def derive_risk_label(features):
    score = 0
    if features["hr"] > 100:
        score += 2
    if features["map"] < 80:
        score += 3
    if features["o2"] < 0.94:
        score += 3
    if score <= 2:
        return "Low"
    if score <= 5:
        return "Low-Mod"
    if score <= 7:
        return "Moderate"
    return "High ⚠️"


def projection_warning_points(driver, today_inputs, features):
    notes = []
    if today_inputs["weight"] >= 80:
        notes.append("Weight is already elevated enough that continued gain would increase fluid burden.")
    if features["hr"] >= 90:
        notes.append("Heart rate is not fully returning to baseline.")
    if features["map"] < 85:
        notes.append("Mean arterial pressure is trending toward reduced perfusion reserve.")
    if driver != "Stable":
        notes.append(f"Primary concern remains {driver.lower()}.")
    return notes[:3] or [
        "Current physiology is stable, but continued worsening would move risk upward.",
        "Heart rate and perfusion should be watched for drift away from baseline.",
        "Repeat daily checks help catch early deterioration before symptoms worsen.",
    ]


def recommendation_copy(risk, features, simulation):
    if risk == "LOW":
        return "Keep monitoring daily. Next check-in recommended in 7 days."
    if risk == "MODERATE":
        return "Contact your cardiologist this week. Increase monitoring frequency."
    return (
        "Contact your cardiologist TODAY. Tell them: "
        f"HR {features['hr']:.1f}, SpO2 {features['o2'] * 100:.1f}%, MAP {features['map']:.1f}, "
        f"CO {value_or_dash(simulation.get('cardiac_output'), 'L/min')}."
    )


def interpretation_line(features):
    if features["hr"] > 100:
        return "Your heart rate is above the normal comparison band, which may reflect compensation for lower reserve."
    if features["o2"] < 0.95:
        return "Your oxygen saturation is below the normal comparison band, suggesting lower oxygen reserve."
    if features["map"] < 80:
        return "Your MAP is below the normal comparison band, which may reduce perfusion support."
    return "Your current values remain close to the healthy comparison range with no major deviation."


def build_report_text(name, age, sex, condition, analysis, nyha_class, projection, simulation):
    return f"""Patient: {name or 'N/A'} | Age: {int(age)} | Sex: {sex}
Simulation Date: {date.today().isoformat()}

Key Findings:
- Detected scenario: {CONDITION_LABELS.get(condition, condition)}
- Risk Score: {risk_score_ratio(analysis):.2f}
- NYHA Class: {nyha_class}
- HF Stage: {analysis['stage']}
- Primary concern: {analysis['driver']}
- Projected stage transition: ~{analysis['time_to_danger']} days

Vitals from Simulation:
HR: {analysis['features']['hr']:.1f}
SpO2: {analysis['features']['o2'] * 100:.1f}%
MAP: {analysis['features']['map']:.1f}
CO: {value_or_dash(simulation.get('cardiac_output'), 'L/min')}
SV: {value_or_dash(simulation.get('stroke_volume'), 'mL')}
Probability of next HF stage in 4 weeks: {projection['transition_probability'] * 100:.0f}%"""


st.markdown('<div class="dashboard-title">PulseDock Patient Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="dashboard-subtitle">Simulation-driven heart failure monitoring with a patient-friendly summary and clinical detail.</div>',
    unsafe_allow_html=True,
)

with st.form("input"):
    col1, col2 = st.columns(2)

    with col1:
        name = st.text_input("Name")
        sex = st.selectbox("Sex", ["Male", "Female"])
        age = st.number_input("Age", value=45.0)
        height = st.number_input("Height", value=170.0)
        weight = st.number_input("Weight", value=70.0)

    with col2:
        hr = st.number_input("Heart Rate", value=80.0)
        spo2 = st.number_input("SpO2", value=98.0)
        bp = st.number_input("BP", value=120.0)
        rr = st.number_input("RR", value=16.0)

    run = st.form_submit_button("Run Simulation")


if run:
    condition, severity = detect_condition(hr, spo2, bp, rr, age)
    scenario = create_scenario(condition, severity, hr, sex)
    csv = run_pulse(scenario)

    analysis = analyze(csv)
    features = analysis["features"]
    simulation = load_simulation_snapshot(csv)
    risk = analysis["risk"]
    risk_ui = RISK_UI[risk]
    nyha_class = classify_nyha(features, risk)
    risk_ratio = risk_score_ratio(analysis)
    projection = build_projection_table(features, analysis, severity, simulation)
    scenario_icon, scenario_text = CONDITION_DETAILS.get(condition, ("🩺", CONDITION_LABELS.get(condition, condition)))
    stage_color = get_stage_color(analysis["stage"])

    st.markdown(
        f"""
        <div class="hero-card {risk_ui['card_class']}">
            <div class="hero-status">{risk_ui['emoji']} {risk_ui['label']}</div>
            <div class="hero-summary">{hero_summary(condition, risk, analysis['driver'])}</div>
            <div class="badge-row">
                <span class="pill {risk_ui['pill_class']}">Risk {risk}</span>
                <span class="pill pill-stage">NYHA Class {nyha_class}</span>
                <span class="pill pill-stage">HF Stage {analysis['stage']}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Section 1 - What\'s Happening In Your Body Right Now</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Current simulation outputs translated into a patient-friendly summary.</div>', unsafe_allow_html=True)

    gauge_col, meta_col = st.columns([1, 2], gap="large")
    with gauge_col:
        gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=risk_ratio,
                number={"suffix": "", "font": {"size": 34, "color": "#f8fafc"}, "valueformat": ".2f"},
                title={"text": "Risk Score", "font": {"size": 16, "color": "#94a3b8"}},
                gauge={
                    "axis": {"range": [0, 1], "tickwidth": 0, "tickcolor": "rgba(0,0,0,0)"},
                    "bar": {"color": risk_ui["dot"], "thickness": 0.3},
                    "bgcolor": "rgba(148, 163, 184, 0.12)",
                    "borderwidth": 0,
                    "steps": [
                        {"range": [0, 0.33], "color": "rgba(34, 197, 94, 0.18)"},
                        {"range": [0.33, 0.66], "color": "rgba(234, 179, 8, 0.18)"},
                        {"range": [0.66, 1], "color": "rgba(239, 68, 68, 0.18)"},
                    ],
                },
            )
        )
        gauge.update_layout(height=250, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True)

    with meta_col:
        left_col, right_col = st.columns([1.2, 1.4])
        with left_col:
            st.markdown(
                f"""
                <div class="info-card">
                    <div class="eyebrow">Detected Scenario</div>
                    <div class="info-title">{scenario_icon} {CONDITION_LABELS.get(condition, condition)} | Severity {severity:.2f}</div>
                    <div class="info-copy">{scenario_text}</div>
                    <hr style="border:0;border-top:1px solid rgba(148,163,184,0.12);margin:1rem 0;">
                    <div class="eyebrow">HF Stage</div>
                    <div class="info-title" style="color:{stage_color};">Stage {analysis['stage']}</div>
                    <div class="info-copy">{STAGE_DESCRIPTIONS.get(analysis['stage'], '')}</div>
                    <hr style="border:0;border-top:1px solid rgba(148,163,184,0.12);margin:1rem 0;">
                    <div class="eyebrow">NYHA Class</div>
                    <div class="info-title">Class {nyha_class}</div>
                    <div class="info-copy">{NYHA_DESCRIPTIONS[nyha_class]}</div>
                    <hr style="border:0;border-top:1px solid rgba(148,163,184,0.12);margin:1rem 0;">
                    <div class="eyebrow">Primary Driver</div>
                    <div class="info-title">{analysis['driver']}</div>
                    <div class="info-copy">This is the strongest contributor to the current risk interpretation.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with right_col:
            metric_cols = st.columns(3)
            metric_specs = [
                ("Heart Rate", "❤", "#ef4444", features["hr"], "bpm", features["hr_rate"]),
                ("SpO2", "🫁", "#3b82f6", features["o2"] * 100, "%", features["o2_rate"]),
                ("MAP", "🩸", "#14b8a6", features["map"], "", features["map_rate"]),
            ]
            for col, (label, icon, color, value, unit, rate) in zip(metric_cols, metric_specs):
                status_text, status_class = metric_status(label, value)
                trend_text, trend_class = get_metric_direction(rate, label)
                with col:
                    st.markdown(
                        f"""
                        <div class="metric-card">
                            <div class="metric-icon" style="background:{color}22;color:{color};">{icon}</div>
                            <div class="eyebrow">{label}</div>
                            <div class="metric-value">{value:.1f}{unit}</div>
                            <div class="metric-trend {trend_class}">{trend_text}</div>
                            <div style="margin-top:0.8rem;">
                                <span class="pill {status_class}">{status_text}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            reasons = "".join(f"<li>{html.escape(msg)}</li>" for msg in explain(features))
            st.markdown(
                f"""
                <div style="margin-top:1rem;" class="bullet-box">
                    <div class="eyebrow">Why This Result</div>
                    <div class="info-title">Why this scenario was detected</div>
                    <ul>{reasons}</ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Section 2 - Your Vitals - Now vs Trend vs Simulation</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Compare today\'s entered values, observed trends, and Pulse simulation outputs.</div>', unsafe_allow_html=True)
    st.markdown(
        build_vitals_table(
            {"hr": hr, "spo2": spo2, "bp": bp, "weight": weight},
            features,
            simulation,
            features,
        ),
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Section 3 - How Do Your Values Compare?</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Your current vitals compared against a normal reference and a heart-failure baseline.</div>', unsafe_allow_html=True)
    st.plotly_chart(comparison_graph(features), use_container_width=True)
    st.markdown(f'<div class="info-copy">{interpretation_line(features)}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Section 4 - Where Is Your Body Heading?</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Based on current trajectory - simulated physiological forecast.</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="sub-card" style="margin-bottom:1rem;">
            <div class="eyebrow">Probability Card</div>
            <div class="info-title">Probability of reaching next HF stage in next 4 weeks: {projection['transition_probability'] * 100:.0f}%</div>
            <div class="progress-track" style="margin-top:0.85rem;">
                <div class="progress-fill" style="width:{projection['transition_probability'] * 100:.0f}%;"></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_proj, right_proj = st.columns([1.3, 1])
    with left_proj:
        trajectory_rows = "".join(
            f"""
            <tr>
                <td>{row['time']}</td>
                <td>{row['co']}</td>
                <td>{row['hr']}</td>
                <td>{row['map']}</td>
                <td>{row['risk']}</td>
            </tr>
            """
            for row in projection["rows"]
        )
        st.markdown(
            textwrap.dedent(
                f"""
                <div class="table-wrap">
                    <table class="styled-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Cardiac Output</th>
                                <th>HR</th>
                                <th>MAP</th>
                                <th>Risk</th>
                            </tr>
                        </thead>
                        <tbody>{trajectory_rows}</tbody>
                    </table>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )

    with right_proj:
        warning_points = "".join(f"<li>{html.escape(item)}</li>" for item in projection_warning_points(analysis["driver"], {"weight": weight}, features))
        st.markdown(
            f"""
            <div class="sub-card">
                <div class="eyebrow">Stage Transition Warning</div>
                <div class="info-copy"><b>Current Stage:</b> {analysis['stage']}</div>
                <div class="info-copy"><b>Next Stage:</b> {projection['next_stage']}</div>
                <div class="info-copy"><b>Estimated time:</b> ~{analysis['time_to_danger']} days at current rate</div>
                <div class="info-copy" style="margin-top:0.9rem;"><b>What pushes you there:</b></div>
                <ul style="color:#cbd5e1; margin-top:0.5rem;">{warning_points}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="recommendation recommendation-{risk_ui['class']}" style="margin-top:1rem;">
            <div class="eyebrow">Action Recommendation</div>
            <div class="info-title">{risk_ui['emoji']} {risk_ui['label']}</div>
            <div class="info-copy">{recommendation_copy(risk, features, simulation)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Section 5 - Share With Your Doctor</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">A compact simulation summary designed to share quickly during triage or follow-up.</div>', unsafe_allow_html=True)

    report_text = build_report_text(name, age, sex, condition, analysis, nyha_class, projection, simulation)
    escaped_report = html.escape(report_text)
    report_html = f"""
    <div id="doctor-report" class="report-card">
        <div class="eyebrow">Doctor Report Summary</div>
        <pre class="report-pre">{escaped_report}</pre>
        <div style="display:flex; gap:0.75rem; flex-wrap:wrap; margin-top:1rem;">
            <button onclick="navigator.clipboard.writeText(document.getElementById('report-text').textContent)"
                style="background:#14b8a6;color:white;border:none;border-radius:10px;padding:0.7rem 1rem;font-weight:700;cursor:pointer;">
                Copy Report
            </button>
            <button onclick="window.print()"
                style="background:transparent;color:#14b8a6;border:1px solid #14b8a6;border-radius:10px;padding:0.7rem 1rem;font-weight:700;cursor:pointer;">
                Download PDF
            </button>
        </div>
    </div>
    <pre id="report-text" style="display:none;">{escaped_report}</pre>
    """
    components.html(report_html, height=460)
    st.download_button("Download Report Text", report_text, file_name="pulsedock_report.txt")
    st.markdown("</div>", unsafe_allow_html=True)