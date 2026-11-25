import sqlite3, re, csv, glob, os, statistics as st
R = re.compile(r'"MeanArterialPressureBaseline"\s*:\s*\{\s*"ScalarPressure"\s*:\s*\{\s*"Value"\s*:\s*([-0-9.eE]+)')
def baselines(db):
    out = []
    for t, s in sqlite3.connect(db).execute("select simulation_time_s, state_json from pulse_states order by simulation_time_s"):
        i = s.find('"CurrentPatient"'); out.append((t, float(R.search(s, i).group(1))))
    return out
# Repo-relative paths. The state databases (dbs/) are not in git; see README.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # results/scenario_tests
sets = [("exp1 held-out", f"{ROOT}/dbs/P??_seed4[5-7].db", f"{ROOT}/daily_results_{{}}_seed{{}}.csv", 660),
        ("exp2", f"{ROOT}/exp2/dbs/P??_seed*.db", f"{ROOT}/exp2/daily_results_{{}}_seed{{}}.csv", 1260)]
for name, dbpat, csvpat, day1_end in sets:
    hb, nb, ser_drop, ser_n = [], [], 0, 0
    for db in sorted(glob.glob(dbpat)):
        pid, seed = re.search(r"(P\d\d)_seed(\d+)", db).groups()
        b = baselines(db); ser_n += 1
        init = b[0][1] if day1_end == 660 else b[0][1]
        if min(v for _, v in b) < 85: ser_drop += 1
        for r in csv.DictReader(open(csvpat.format(pid, seed))):
            d = int(r["day"]); start_t = day1_end + 600 * (d - 1) - 600
            prev = [v for t, v in b if t <= start_t + 1e-6]
            if not prev or r["run_status"] != "complete": continue
            (hb if r["risk_bucket"] == "HIGH" else nb).append(prev[-1])
    print(f"{name}: series {ser_n}, series whose MAP baseline fell below 85: {ser_drop}")
    print(f"  HIGH days n={len(hb)} median start baseline {st.median(hb):.1f}, share <85: {sum(v<85 for v in hb)/len(hb):.1%}")
    print(f"  other days n={len(nb)} median start baseline {st.median(nb):.1f}, share <85: {sum(v<85 for v in nb)/len(nb):.1%}")
