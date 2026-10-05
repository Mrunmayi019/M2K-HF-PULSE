"""
Figures for paper/main.tex. Every number is copied from the project's own documented results
(source file noted next to each block) -- nothing is recomputed or estimated here.

Run from the repo root:  python3 paper/figures/make_figures.py
"""
import os

import matplotlib.pyplot as plt
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
BLUE, RED, GREY, ORANGE = "#2a78d6", "#e34948", "#7a7a7a", "#eb6834"
COL = 3.5
plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#dddddd", "grid.linewidth": 0.5, "savefig.dpi": 300, "savefig.bbox": "tight",
})

# 1. Pulse batch success by scenario (docs/methodology.md, Phase 4 table + missingness section)
scen = ["stable", "decond.", "fluid\noverload", "cardiac\nstress", "acute\ndeter."]
ok = np.array([30, 30, 30, 15, 12])
fig, ax = plt.subplots(figsize=(COL, 1.9))
ax.bar(scen, ok, color=BLUE, width=0.6, label="completed")
ax.bar(scen, 30 - ok, bottom=ok, color=RED, width=0.6, label="crashed / timed out")
for i, v in enumerate(ok):
    ax.text(i, 31, f"{v}/30", ha="center", fontsize=7)
ax.set_ylim(0, 36)
ax.set_ylabel("Pulse runs")
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, loc="lower left", ncol=2, bbox_to_anchor=(0, 1.0))
fig.savefig(os.path.join(OUT, "fig_batch_success.png"))
plt.close(fig)

# 2. Alert candidates: false alerts per 100 patient-days in the should-stay-quiet group
#    (results/scenario_tests/alert_fix_results.md and alert_fix_results_heldout.md)
cands = ["Baseline", "C1:\npersistence", "C2:\ntwo-level", "C3:\nguard"]
dev = [17.99, 13.76, 17.99, 5.82]
held = [30.16, 25.40, 30.16, 11.64]
x = np.arange(len(cands))
fig, ax = plt.subplots(figsize=(COL, 2.0))
ax.bar(x - 0.18, dev, 0.34, color=BLUE, label="Development seeds (42-44)")
ax.bar(x + 0.18, held, 0.34, color=ORANGE, label="Held-out seeds (45-47)")
for xi, d, h in zip(x, dev, held):
    ax.text(xi - 0.18, d + 0.6, f"{d:.1f}", ha="center", fontsize=6)
    ax.text(xi + 0.18, h + 0.6, f"{h:.1f}", ha="center", fontsize=6)
ax.set_xticks(x, cands)
ax.set_ylabel("False alerts / 100 patient-days")
ax.set_ylim(0, 35)
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, loc="lower left", ncol=2, bbox_to_anchor=(0, 1.0))
fig.savefig(os.path.join(OUT, "fig_alert_candidates.png"))
plt.close(fig)

# 3. Real-outcome discrimination, AUC with 95% CI (docs/methodology.md 7.X-7.CC, docs/claims_methodology.md)
rows = [
    ("Baseline-deficit score, MIMIC-IV (n=17,129)", 0.596, 0.585, 0.608, BLUE),
    ("Baseline-deficit score, Zigong (n=625)", 0.533, 0.490, 0.575, BLUE),
    ("Baseline-deficit score, Zigong (n=2,001)", 0.548, 0.525, 0.573, BLUE),
    ("Clinical-only Model 1 variant, Zigong (n=625)", 0.517, 0.473, 0.562, BLUE),
    ("MAGGIC-11 (external), Zigong (n=622)", 0.604, 0.559, 0.649, GREY),
    ("Zigong-native lab model (external), test n=401", 0.667, 0.611, 0.721, GREY),
]
fig, ax = plt.subplots(figsize=(COL, 2.3))
for i, (lab, a, lo, hi, c) in enumerate(rows[::-1]):
    ax.plot([lo, hi], [i, i], color=c, lw=1.4)
    ax.plot(a, i, "o", color=c, ms=4)
ax.axvline(0.5, color=RED, ls="--", lw=0.8)
ax.text(0.502, len(rows) - 0.45, "chance", color=RED, fontsize=6)
ax.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]])
ax.set_xlabel("AUC (95% bootstrap CI)")
ax.set_xlim(0.45, 0.75)
ax.grid(axis="y", visible=False)
fig.savefig(os.path.join(OUT, "fig_auc_forest.png"))
plt.close(fig)

# 4. PerHeart real-patient replay, risk-bucket distribution pre vs post severity-model fix
#    (docs/real_world_data_integration.md 8.1 and 8.4)
labels = ["Post-fix\n(13 completed)", "Pre-fix\n(16 completed)"]
low, mod, high = np.array([4, 4]), np.array([4, 12]), np.array([5, 0])
fig, ax = plt.subplots(figsize=(COL, 1.7))
ax.barh(labels, low, color="#9cc3ec", label="LOW")
ax.barh(labels, mod, left=low, color=BLUE, label="MODERATE")
ax.barh(labels, high, left=low + mod, color=RED, label="HIGH")
ax.set_xlabel("Patients")
ax.grid(axis="y", visible=False)
ax.legend(frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0))
fig.savefig(os.path.join(OUT, "fig_perheart_buckets.png"))
plt.close(fig)
print("figures written to", OUT)
