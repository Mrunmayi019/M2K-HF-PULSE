from flask import Flask, request, render_template_string
from src.rules import detect_condition
from src.generator import create_scenario
from src.run import run_pulse
from src.analytics import analyze

import pandas as pd
import os

app = Flask(__name__)

HTML = """
<h2>Patient Input</h2>
<form method="post">

    Name: <input name="name"><br><br>

    Sex:
    <select name="sex">
        <option value="Male">Male</option>
        <option value="Female">Female</option>
    </select><br><br>

    Age: <input name="age"><br><br>
    Height (cm): <input name="height"><br><br>
    Weight (kg): <input name="weight"><br><br>

    Heart Rate: <input name="hr"><br><br>
    SpO2: <input name="spo2"><br><br>
    Blood Pressure (Systolic): <input name="bp"><br><br>
    Respiration Rate: <input name="rr"><br><br>

    <input type="submit">

</form>

{% if result %}
<h3>Result:</h3>
<div style="border:1px solid #ccc; padding:15px;">
{{ result|safe }}
</div>
{% endif %}
"""

@app.route("/", methods=["GET", "POST"])
def index():
    result = None

    if request.method == "POST":
        try:
            # --------------------------
            # 1. Read inputs
            # --------------------------
            name = request.form["name"]
            sex = request.form["sex"]

            age = float(request.form["age"])
            height = float(request.form["height"])
            weight = float(request.form["weight"])

            hr = float(request.form["hr"])
            spo2 = float(request.form["spo2"])
            bp = float(request.form["bp"])
            rr = float(request.form["rr"])

            # --------------------------
            # 2. Detect condition
            # --------------------------
            condition, severity = detect_condition(hr, spo2, bp, rr, age)

            # --------------------------
            # 3. Generate scenario
            # --------------------------
            scenario_path = create_scenario(condition, severity, hr, sex)

            # --------------------------
            # 4. Run Pulse
            # --------------------------
            csv_path = run_pulse(scenario_path)

            if not os.path.exists(csv_path):
                result = "Simulation ran but CSV not found ❌"
            else:
                # --------------------------
                # 5. Run analytics engine
                # --------------------------
                analysis = analyze(csv_path)

                # --------------------------
                # 6. Build dashboard output
                # --------------------------
                result = f"""
                <b>Patient:</b> {name} ({sex})<br>
                Age: {age} | Height: {height} cm | Weight: {weight} kg<br><br>

                <b>Condition:</b> {condition}<br>
                Severity: {round(severity, 2)}<br><br>

                <hr>

                <b>📊 CURRENT STATUS</b><br>
                HR: {analysis['features']['hr']}<br>
                SpO2: {analysis['features']['o2']}<br>
                MAP: {analysis['features']['map']}<br><br>

                <b>Stage:</b> {analysis['stage']}<br>
                <b>Risk Level:</b> {analysis['risk']}<br>
                <b>Primary Driver:</b> {analysis['driver']}<br>
                <b>Time to Danger:</b> {analysis['time_to_danger']} days<br><br>

                <hr>

                <b>📈 PROJECTION</b><br>
                7 days → HR {analysis['forecast']['7d']['hr']}, O2 {analysis['forecast']['7d']['o2']}<br>
                14 days → HR {analysis['forecast']['14d']['hr']}, O2 {analysis['forecast']['14d']['o2']}<br>
                30 days → HR {analysis['forecast']['30d']['hr']}, O2 {analysis['forecast']['30d']['o2']}<br>
                """

        except Exception as e:
            result = f"Error: {str(e)}"

    return render_template_string(HTML, result=result)


app.run(host="0.0.0.0", port=5000)