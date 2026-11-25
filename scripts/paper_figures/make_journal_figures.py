"""Paper figures drawn from the saved pre-specified scenario-test runs (no new simulation):
engine output by story (fig_engine_output), risk-score breakdown (fig_risk_breakdown) and, with
--engine-dir, the state-resume figure (fig_resume_fidelity).

Inputs:
  results/scenario_tests/daily_results_P??_seed4[2-7].csv   per-day engine/wearable/risk values (committed)
  results/scenario_tests/dbs/P??_seed4[5-7].db              per-day risk components (optional, not committed:
                                                            if absent, the components are recomputed from the
                                                            daily CSVs with src.analytics.risk_score)
  results/paper_figures/engine_traces/*Results.csv          state-resume traces (committed; regenerate with
                                                            scripts/paper_figures/make_resume_traces.py)

Run from the repo root:
  python3 scripts/paper_figures/make_journal_figures.py --out <dir> \
      --engine-dir results/paper_figures/engine_traces
"""
import argparse
import csv
import json
import os
import sqlite3

import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
RES = os.path.join(ROOT, "results", "scenario_tests")
BLUE, RED, GREY, ORANGE, LIGHT, PURPLE, GREEN = "#2a78d6", "#e34948", "#7a7a7a", "#eb6834", "#9cc3ec", "#5a3e9b", "#3a9a5b"
COL, PAGE = 3.5, 7.16
plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#dddddd", "grid.linewidth": 0.5, "savefig.dpi": 300, "savefig.bbox": "tight",
})
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--engine-dir", help="optional: *Results.csv traces from the P4/P5 engine runs")
ARGS = ap.parse_args()
OUT = ARGS.out
os.makedirs(OUT, exist_ok=True)

SEEDS = (42, 43, 44, 45, 46, 47)
STORIES = [("P01", "P01\nstable", None), ("P04", "P04\nfluid overload", 4), ("P06", "P06\ncardiac stress", 6),
           ("P07", "P07\nsudden deterioration", 10), ("P08", "P08\nstress, healthy heart", 5)]


def daily(pid, col, scale=1.0):
    out = []
    for s in SEEDS:
        rows = sorted(csv.DictReader(open(os.path.join(RES, f"daily_results_{pid}_seed{s}.csv"))), key=lambda r: int(r["day"]))
        out.append([float(r[col]) * scale if r[col] not in ("", None) else np.nan for r in rows])
    return np.array(out)


def band(ax, arr, c, lab=None, ls="-"):
    d = np.arange(1, arr.shape[1] + 1)
    ax.fill_between(d, np.nanmin(arr, 0), np.nanmax(arr, 0), color=c, alpha=0.15, lw=0)
    ax.plot(d, np.nanmean(arr, 0), color=c, lw=1.2, ls=ls, label=lab)


def grid(rows, title_fn, fname, height, note=None):
    fig, axes = plt.subplots(len(rows), len(STORIES), figsize=(PAGE, height), sharex=True, sharey="row")
    for j, (pid, title, onset) in enumerate(STORIES):
        axes[0, j].set_title(title, fontsize=7)
        for i, (ylab, draw) in enumerate(rows):
            ax = axes[i, j]
            draw(ax, pid)
            if onset:
                ax.axvline(onset, color=GREY, ls="--", lw=0.7)
            if j == 0:
                ax.set_ylabel(ylab)
            ax.set_xlim(1, 21)
        axes[-1, j].set_xlabel("Monitored day")
        axes[-1, j].set_xticks([1, 7, 14, 21])
    if note:
        fig.text(0.01, -0.01, note, fontsize=6, color=GREY, ha="left", va="top")
    fig.savefig(os.path.join(OUT, fname)); plt.close(fig)


# ---- P2. Synthetic wearable inputs by story (what the classifier sees) ----
grid([
    ("Weight (kg)", lambda ax, p: band(ax, daily(p, "wearable_weight_kg"), PURPLE)),
    ("Steps / day (k)", lambda ax, p: band(ax, daily(p, "wearable_steps_per_day", 1e-3), GREEN)),
    ("HRV RMSSD (ms)", lambda ax, p: band(ax, daily(p, "wearable_hrv_rmssd_ms"), ORANGE)),
    ("Resting HR (bpm)", lambda ax, p: band(ax, daily(p, "wearable_resting_hr_bpm"), RED)),
], None, "P2_wearable_inputs_by_story.png", 5.0,
    "Mean and range over six seeds (42-47). Dashed line: designed onset of the story's change.")


# ---- P3. Pulse engine output by story, day by day (what the engine returns) ----
def map_panel(ax, p):
    band(ax, daily(p, "pulse_map_start"), BLUE, "start of run")
    band(ax, daily(p, "pulse_map_end"), RED, "end of run", ls="--")
    ax.axhline(92.5, color=GREY, lw=0.6, ls=":")
    ax.axhline(65, color=GREY, lw=0.6, ls=":")


def risk_panel(ax, p):
    band(ax, daily(p, "risk_score"), BLUE, "Pulse risk score")
    band(ax, daily(p, "predicted_severity"), RED, "Classifier severity", ls="--")
    ax.axhline(0.65, color=GREY, lw=0.6, ls=":")
    ax.set_ylim(-0.03, 1.05)


fig_rows = [
    ("Heart rate (bpm)", lambda ax, p: (band(ax, daily(p, "pulse_hr_start"), BLUE, "start of run"),
                                        band(ax, daily(p, "pulse_hr_end"), RED, "end of run", ls="--"))),
    ("MAP (mmHg)", map_panel),
    ("Cardiac output (L/min)", lambda ax, p: (band(ax, daily(p, "pulse_co_start", 1e-3), BLUE, "start of run"),
                                              band(ax, daily(p, "pulse_co_end", 1e-3), RED, "end of run", ls="--"))),
    ("Score (0-1)", risk_panel),
]
fig, axes = plt.subplots(4, len(STORIES), figsize=(PAGE, 5.4), sharex=True, sharey="row")
for j, (pid, title, onset) in enumerate(STORIES):
    axes[0, j].set_title(title, fontsize=7)
    for i, (ylab, draw) in enumerate(fig_rows):
        ax = axes[i, j]
        draw(ax, pid)
        if onset:
            ax.axvline(onset, color=GREY, ls="--", lw=0.7)
        if j == 0:
            ax.set_ylabel(ylab)
        ax.set_xlim(1, 21)
    axes[-1, j].set_xlabel("Monitored day")
    axes[-1, j].set_xticks([1, 7, 14, 21])
axes[0, 0].legend(frameon=False, loc="upper left", fontsize=5.5)
axes[3, 0].legend(frameon=False, loc="center left", fontsize=5.5)
fig.text(0.01, -0.01, "Each point is one day's Pulse run; mean and range over six seeds (42-47).\nMAP dotted lines: "
         "92.5 mmHg (healthy anchor) and 65 mmHg (instability threshold). Score dotted line: HIGH (0.65).\n"
         "Grey dashed line: designed onset.", fontsize=6, color=GREY, ha="left", va="top")
fig.savefig(os.path.join(OUT, "P3_engine_output_by_story.png")); plt.close(fig)


# ---- P6. What drives a HIGH risk score: component breakdown (held-out seeds 45-47, saved DBs) ----
DBS = os.path.join(RES, "dbs")
COMP = [("instability_flag", "Instability (MAP<65)", RED), ("map_drop", "MAP drop", ORANGE),
        ("co_drop_pct", "CO drop", PURPLE), ("hr_rise", "HR rise", BLUE), ("compensation_flag", "Failed compensation", GREY)]


def assessments(pid, seed):
    db = os.path.join(DBS, f"{pid}_seed{seed}.db")
    if not os.path.exists(db):
        return assessments_from_csv(pid, seed)
    c = sqlite3.connect(db)
    rows = c.execute("select s.id, r.risk_score, r.risk_bucket, r.dominant_mechanism, r.baseline_deficit_score, "
                     "r.component_scores, s.scenario_type from risk_assessments r join simulation_runs s "
                     "on s.id = r.simulation_run_id order by s.id").fetchall()
    return [dict(day=r[0], risk=r[1], bucket=r[2], mech=r[3], base=r[4] or 0.0, comp=json.loads(r[5]), label=r[6])
            for r in rows]


def assessments_from_csv(pid, seed):
    """Same fields as assessments(), recomputed from the committed daily CSV with the production
    risk score (the per-day components are a pure function of the saved start/end HR, MAP, CO and
    the two flags)."""
    import sys
    sys.path.insert(0, ROOT)
    from src.analytics.risk_score import compute_risk_score
    out = []
    for r in csv.DictReader(open(os.path.join(RES, f"daily_results_{pid}_seed{seed}.csv"))):
        if r["run_status"] != "complete":
            continue
        co0 = float(r["pulse_co_start"])
        k = compute_risk_score(
            hr_rise=float(r["pulse_hr_end"]) - float(r["pulse_hr_start"]),
            map_drop=float(r["pulse_map_start"]) - float(r["pulse_map_end"]),
            co_drop_pct=(co0 - float(r["pulse_co_end"])) / co0 * 100 if co0 else 0.0,
            compensation_flag=int(float(r["pulse_compensation_flag"])),
            instability_flag=int(float(r["pulse_instability_flag"])),
            map_start=float(r["pulse_map_start"]))
        out.append(dict(day=int(r["day"]), risk=k["risk_score"], bucket=k["risk_bucket"], mech=k["dominant_mechanism"],
                        base=k["baseline_deficit_score"], comp=k["component_scores"], label=r.get("predicted_scenario")))
    return out


pids = [f"P{i:02d}" for i in range(1, 11)]
# (a) uses all six seeds from the daily CSVs: a HIGH day is "baseline" when its risk equals the
# baseline-deficit term computed from the saved start-of-run MAP (Eq. risk: r = max(A, s_baseline)).
hi_base, hi_acute, mod_any = [], [], []
for pid in pids:
    hb = ha = m = 0
    for s in SEEDS:
        for r in csv.DictReader(open(os.path.join(RES, f"daily_results_{pid}_seed{s}.csv"))):
            if r["risk_bucket"] == "HIGH":
                sb = min(max((92.5 - float(r["pulse_map_start"])) / 27.5, 0.0), 1.0)
                if sb > 0 and abs(sb - float(r["risk_score"])) < 6e-4:
                    hb += 1
                else:
                    ha += 1
            elif r["risk_bucket"] == "MODERATE":
                m += 1
    hi_base.append(hb); hi_acute.append(ha); mod_any.append(m)

examples = [("P07", 45, 4, "P07 day 4\n(before onset)"), ("P07", 45, 14, "P07 day 14\n(after onset)"),
            ("P08", 45, 13, "P08 day 13\n(healthy heart)"), ("P01", 45, 21, "P01 day 21\n(stable)"),
            ("P01", 45, 1, "P01 day 1\n(stable)")]
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(PAGE, 2.6), gridspec_kw={"width_ratios": [1, 1.35], "wspace": 0.42})
x = np.arange(len(pids))
ax1.bar(x, hi_base, color=BLUE, label="HIGH, baseline deficit dominant")
ax1.bar(x, hi_acute, bottom=hi_base, color=RED, label="HIGH, acute score dominant")
ax1.bar(x, mod_any, bottom=np.array(hi_base) + np.array(hi_acute), color=LIGHT, label="MODERATE (either)")
ax1.set_xticks(x, pids, rotation=0, fontsize=6)
ax1.set_ylabel("Patient-days (of 126)")
ax1.set_title(f"(a) Experiment 1, seeds 42-47: {sum(hi_base)} of {sum(hi_base) + sum(hi_acute)} HIGH days\n"
              "are decided by the baseline-deficit term", loc="left")
ax1.legend(frameon=False, loc="upper left", bbox_to_anchor=(-0.02, -0.11), ncol=1, fontsize=6)
ax1.set_ylim(0, 126)

y = np.arange(len(examples))[::-1]
for yi, (pid, s, day, lab) in zip(y, examples):
    a = next(e for e in assessments(pid, s) if e["day"] == day)
    left = 0.0
    for k, name, c in COMP:
        v = a["comp"][k]
        ax2.barh(yi + 0.18, v, left=left, height=0.32, color=c, label=name if yi == y[0] else None)
        left += v
    ax2.barh(yi - 0.18, a["base"], height=0.32, color=BLUE, alpha=0.45, hatch="////", edgecolor=BLUE, lw=0,
             label="Baseline deficit (start-of-run MAP)" if yi == y[0] else None)
    ax2.text(1.02, yi, f"risk {a['risk']:.2f}\n{a['bucket']}", va="center", fontsize=6.2,
             color=RED if a["bucket"] == "HIGH" else GREY)
ax2.axvline(0.35, color=GREY, ls=":", lw=0.7)
ax2.axvline(0.65, color=GREY, ls=":", lw=0.7)
ax2.set_yticks(y, [e[3] for e in examples], fontsize=6.5)
ax2.set_xlim(0, 1.0)
ax2.set_xlabel("Contribution to the score (top: acute sub-score; bottom: baseline deficit)")
ax2.set_title("(b) Single days (seed 45): risk = max(acute sub-score, baseline deficit)", loc="left")
ax2.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.24), ncol=3, fontsize=6)
ax2.grid(axis="y", visible=False)
fig.savefig(os.path.join(OUT, "P6_risk_score_breakdown.png")); plt.close(fig)
print("HIGH baseline/acute:", sum(hi_base), sum(hi_acute), "MODERATE:", sum(mod_any))


# ---- P4/P5. Engine time series (only when --engine-dir is given; needs new Pulse runs) ----
def trace(name):
    import pandas as pd
    f = os.path.join(ARGS.engine_dir, f"{name}Results.csv")
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f)
    df.columns = [c.strip() for c in df.columns]
    pick = lambda key: next(c for c in df.columns if key.lower() in c.lower().replace(" ", ""))
    return {"t": df[pick("time")].values, "hr": df[pick("heartrate")].values, "map": df[pick("meanarterialpressure")].values,
            "co": df[pick("cardiacoutput")].values / 1000.0, "sv": df[pick("heartstrokevolume")].values}


if ARGS.engine_dir:
    ctl, half = trace("crash_control"), trace("crash_half_intensity")
    if ctl is not None and half is not None:
        fig, axes = plt.subplots(1, 3, figsize=(PAGE, 2.1), sharex=True)
        for ax, k, lab in zip(axes, ("map", "hr", "co"), ("MAP (mmHg)", "Heart rate (bpm)", "Cardiac output (L/min)")):
            ax.plot(half["t"], half[k], color=BLUE, lw=1.1, label=f"Exertion halved: completes ({half['t'][-1]:.0f} s)")
            ax.plot(ctl["t"], ctl[k], color=RED, lw=1.1, label=f"Control: engine stops at {ctl['t'][-1]:.1f} s")
            ax.axvline(60, color=GREY, ls="--", lw=0.7)
            ax.set_ylabel(lab); ax.set_xlabel("Simulated time (s)")
        axes[0].axhline(65, color=GREY, ls=":", lw=0.6)
        axes[0].text(62, axes[0].get_ylim()[1] * 0.97, "modifiers + exercise", fontsize=6, color=GREY, va="top")
        axes[0].legend(frameon=False, loc="lower left", fontsize=6)
        fig.savefig(os.path.join(OUT, "P4_crash_reconstruction.png")); plt.close(fig)

    cont, noreq, req = trace("resume_continuous"), trace("resume_no_reissue"), trace("resume_with_reissue")
    if cont is not None and noreq is not None and req is not None:
        fig, axes = plt.subplots(2, 2, figsize=(PAGE, 3.4), sharex=True)
        for ax, k, lab in zip(axes.flat, ("hr", "map", "co", "sv"),
                              ("Heart rate (bpm)", "MAP (mmHg)", "Cardiac output (L/min)", "Stroke volume (mL)")):
            ax.plot(cont["t"], cont[k], color=GREY, lw=2.4, alpha=0.6, label="Continuous run (reference)")
            ax.plot(noreq["t"], noreq[k], color=RED, lw=1.0, ls="--", label="Resumed, modifier not re-issued")
            ax.plot(req["t"], req[k], color=BLUE, lw=1.0, label="Resumed, modifier re-issued")
            ax.axvline(150, color=GREY, ls=":", lw=0.7)
            ax.set_ylabel(lab)
            ax.set_xlim(100, 242)
        for ax in axes[1]:
            ax.set_xlabel("Simulated time (s)")
        axes[0, 0].legend(frameon=False, fontsize=6, loc="lower left")
        axes[0, 0].text(151, axes[0, 0].get_ylim()[1], "state saved and reloaded", fontsize=6, color=GREY, va="top")
        fig.savefig(os.path.join(OUT, "P5_state_resume_fidelity.png")); plt.close(fig)
print("journal figures written to", OUT)
