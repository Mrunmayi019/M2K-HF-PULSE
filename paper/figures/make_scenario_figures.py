"""Scenario-test figures for paper/main.tex, drawn from the saved pre-registered runs.

Inputs:
  --results-dir  daily_results_P??_seed??.csv (from feature/scenario-testing)
  --dbs          per-patient-seed SQLite databases (results/scenario_tests/dbs, waveform_data column)
  results/scenario_tests/posthoc/ablation_eval.json and ablation_baselines.json (committed)

Run from the repo root:
  python3 paper/figures/make_scenario_figures.py --results-dir <dir> --dbs results/scenario_tests/dbs
"""
import argparse
import csv
import json
import os
import sqlite3

import matplotlib.pyplot as plt
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(OUT, "..", "..")
BLUE, RED, GREY, ORANGE, LIGHT = "#2a78d6", "#e34948", "#7a7a7a", "#eb6834", "#9cc3ec"
COL = 3.5
plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#dddddd", "grid.linewidth": 0.5, "savefig.dpi": 300, "savefig.bbox": "tight",
})
ap = argparse.ArgumentParser()
ap.add_argument("--results-dir", required=True)
ap.add_argument("--dbs", required=True)
a = ap.parse_args()
post = os.path.join(ROOT, "results", "scenario_tests", "posthoc")
abl = json.load(open(os.path.join(post, "ablation_eval.json")))["failed_as_alert"]["all"]
base = json.load(open(os.path.join(post, "ablation_baselines.json")))

# ---- 1. threshold sweep with the Pulse-based rules on the same axes ----
sw = base["severity_threshold_sweep"]
fig, ax = plt.subplots(figsize=(COL, 2.5))
x = [e["fa_per_100pd"][0] for e in sw]
y = [100 * e["sens"][0] / e["sens"][1] for e in sw]
ax.plot(x, y, "-", color=RED, lw=1.2, label="Classifier only, threshold swept")
ax.scatter(x, y, s=8, color=RED, zorder=3)
for e, xi, yi in zip(sw, x, y):
    if e["threshold"] in (0.15, 0.55, 0.65, 0.85):
        ax.annotate(f"{e['threshold']:.2f}", (xi, yi), textcoords="offset points", xytext=(3, 3), fontsize=6, color=RED)
pts = {"pulse_high": ("Pulse risk HIGH", ORANGE, "s"), "decide_alert": ("Deployed (C3 guard)", BLUE, "D"),
       "weight_rule": ("Weight rule", GREY, "^")}
for k, (lab, c, m) in pts.items():
    e = abl[k]
    xx, yy = e["false_alerts_per_100pd"][0], 100 * e["sensitivity_series"][0] / e["sensitivity_series"][1]
    ax.errorbar(xx, yy, xerr=[[xx - e["false_alerts_per_100pd"][1]], [e["false_alerts_per_100pd"][2] - xx]],
                fmt=m, color=c, ms=4.5, lw=0.8, capsize=2, label=lab, zorder=4)
lab_e = base["rules"]["label_exertion"]
ax.scatter(lab_e["fa_per_100pd"][0], 100 * lab_e["sens"][0] / lab_e["sens"][1], marker="x", color="#5a3e9b", s=22,
           label="Label only (exertion scenario)", zorder=4)
ax.set_xlabel("False alerts / 100 patient-days (stable stories)")
ax.set_ylabel("Deteriorating series detected (%)")
ax.set_xlim(-3, 66); ax.set_ylim(-5, 108)
ax.legend(frameon=False, loc="lower right")
fig.savefig(os.path.join(OUT, "fig_threshold_sweep.png")); plt.close(fig)

# ---- 2. confusion matrix (story label, all 1,260 patient-days), row-normalised ----
labs = ["stable", "fluid_overload", "cardiac_stress", "deconditioning", "acute_deterioration"]
short = ["stable", "fluid ovl.", "card. stress", "decond.", "acute det."]
cm = np.array([[base["confusion_story_label"][t][p] for p in labs] for t in labs], float)
rows_present = cm.sum(1) > 0
cmn = cm / np.where(cm.sum(1, keepdims=True) == 0, 1, cm.sum(1, keepdims=True))
fig, ax = plt.subplots(figsize=(COL, 2.6))
im = ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
for i in range(5):
    for j in range(5):
        if rows_present[i]:
            ax.text(j, i, f"{int(cm[i, j])}", ha="center", va="center", fontsize=6.5,
                    color="white" if cmn[i, j] > 0.55 else "black")
ax.set_xticks(range(5), short, rotation=30, ha="right")
ax.set_yticks(range(5), short)
ax.set_xlabel("Predicted scenario (daily)")
ax.set_ylabel("Story's intended scenario")
ax.grid(False)
cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label("Row share", fontsize=7); cb.ax.tick_params(labelsize=6)
fig.savefig(os.path.join(OUT, "fig_confusion.png")); plt.close(fig)

# ---- 3. daily timelines, one deteriorating and one stable story, all six seeds ----
def daily(pid):
    sev, risk = [], []
    for s in (42, 43, 44, 45, 46, 47):
        rows = sorted(csv.DictReader(open(os.path.join(a.results_dir, f"daily_results_{pid}_seed{s}.csv"))), key=lambda r: int(r["day"]))
        sev.append([float(r["predicted_severity"]) if r["predicted_severity"] else np.nan for r in rows])
        risk.append([float(r["risk_score"]) if r["risk_score"] else np.nan for r in rows])
    return np.array(sev), np.array(risk)

fig, axes = plt.subplots(1, 2, figsize=(2 * COL, 2.1), sharey=True)
for ax, pid, title, onset in [(axes[0], "P07", "P07: sudden deterioration (onset day 10)", 10),
                              (axes[1], "P08", "P08: stressful fortnight, healthy heart", 5)]:
    sev, risk = daily(pid)
    d = np.arange(1, sev.shape[1] + 1)
    for arr, c, lab in [(sev, RED, "Classifier severity"), (risk, BLUE, "Pulse risk score")]:
        ax.fill_between(d, np.nanmin(arr, 0), np.nanmax(arr, 0), color=c, alpha=0.15, lw=0)
        ax.plot(d, np.nanmean(arr, 0), color=c, lw=1.4, label=lab)
    ax.axhline(0.65, color=BLUE, ls=":", lw=0.8)
    ax.axhline(0.55, color=RED, ls=":", lw=0.8)
    ax.axvline(onset, color=GREY, ls="--", lw=0.8)
    ax.set_title(title)
    ax.set_xlabel("Monitored day")
    ax.set_xlim(1, 21); ax.set_ylim(-0.03, 1.05)
axes[0].set_ylabel("Score (mean, seed range)")
axes[0].text(1.3, 0.67, "risk HIGH (0.65)", fontsize=6, color=BLUE)
axes[0].text(1.3, 0.49, "severity 0.55", fontsize=6, color=RED)
axes[1].text(5.3, 0.02, "story starts", fontsize=6, color=GREY)
axes[0].legend(frameon=False, loc="lower right")
fig.savefig(os.path.join(OUT, "fig_timelines.png")); plt.close(fig)

# ---- 4. Pulse pressure-volume loops and ECG reference trace from the saved runs ----
def wave(pid, seed, day):
    c = sqlite3.connect(os.path.join(a.dbs, f"{pid}_seed{seed}.db"))
    r = c.execute("select s.waveform_data, s.scenario_type, r.risk_bucket from simulation_runs s join risk_assessments r "
                  "on r.simulation_run_id = s.id where s.id = ?", (day,)).fetchone()
    return json.loads(r[0]), r[1], r[2]

cases = [("P07", 45, 1, BLUE), ("P07", 45, 14, RED)]
fig, axes = plt.subplots(1, 2, figsize=(2 * COL, 2.1), gridspec_kw={"width_ratios": [1.15, 1]})
for pid, seed, day, c in cases:
    w, scen, bucket = wave(pid, seed, day)
    v = [p["volume_ml"] for p in w["pv_loop"]] + [w["pv_loop"][0]["volume_ml"]]
    p = [p["pressure_mmhg"] for p in w["pv_loop"]] + [w["pv_loop"][0]["pressure_mmhg"]]
    axes[0].plot(v, p, color=c, lw=1.3, label=f"{pid} day {day}: {scen.replace('_', ' ')}, {bucket}")
    if day == 1:
        t = [e["t_s"] for e in w["ecg"]]; mv = [e["mv"] for e in w["ecg"]]
        axes[1].plot(t, mv, color=GREY, lw=1.0)
axes[0].set_xlabel("Left-heart volume (mL)"); axes[0].set_ylabel("Left-heart pressure (mmHg)")
axes[0].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.28), fontsize=6, ncol=1)
axes[0].set_title("Pressure-volume loops (one steady-state cycle)")
axes[1].set_xlabel("Time (s)"); axes[1].set_ylabel("Lead III (mV)")
axes[1].set_title("ECG reference trace (stored template, scales with HR)")
fig.savefig(os.path.join(OUT, "fig_pv_ecg.png")); plt.close(fig)
print("scenario figures written")
