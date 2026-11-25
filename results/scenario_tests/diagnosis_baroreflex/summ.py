import csv, glob, os, re, sys
D = sys.argv[1] if len(sys.argv) > 1 else "out"  # the out/ folder the Docker runs wrote to
for f in sorted(glob.glob(f"{D}/*Results.csv")):
    rows = list(csv.reader(open(f))); h = rows[0]; data = rows[1:]
    t0 = float(data[0][0]); idx = {k: h.index(k) for k in ["HeartRate(1/min)", "MeanArterialPressure(mmHg)", "CardiacOutput(mL/min)", "HeartStrokeVolume(mL)"]}
    name = os.path.basename(f).replace("Results.csv", "")
    print(name)
    for off in (0, 300, 600, 1200, 1800):
        r = [x for x in data if float(x[0]) - t0 >= off - 1e-6][:1]
        if r: print(f"  +{off:5d}s HR {float(r[0][idx['HeartRate(1/min)']]):6.1f}  MAP {float(r[0][idx['MeanArterialPressure(mmHg)']]):6.1f}  CO {float(r[0][idx['CardiacOutput(mL/min)']])/1000:5.2f}  SV {float(r[0][idx['HeartStrokeVolume(mL)']]):6.1f}")
    log = open(f.replace("Results.csv", ".log"), errors="ignore").read()
    ups = re.findall(r"\[(\d+(?:\.\d+)?)\(s\)\].*Baroreceptor MAP Baseline updated to ([0-9.]+)", log)
    if ups: print("  baseline updates:", ", ".join(f"{float(t)-t0:.0f}s->{float(v):.1f}" for t, v in ups))
