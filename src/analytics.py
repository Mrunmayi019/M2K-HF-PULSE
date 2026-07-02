import pandas as pd

# -------------------------
# 1. Extract features
# -------------------------
def extract_features(csv_path):
    df = pd.read_csv(csv_path)

    first = df.iloc[0]
    last = df.iloc[-1]

    hr_start = first["HeartRate(1/min)"]
    hr_end = last["HeartRate(1/min)"]

    o2_start = first["OxygenSaturation"]
    o2_end = last["OxygenSaturation"]

    map_start = first.get("MeanArterialPressure(mmHg)", 90)
    map_end = last.get("MeanArterialPressure(mmHg)", 90)

    # Rate of change (simple slope)
    hr_rate = (hr_end - hr_start) / len(df)
    o2_rate = (o2_end - o2_start) / len(df)
    map_rate = (map_end - map_start) / len(df)

    return {
        "hr": hr_end,
        "o2": o2_end,
        "map": map_end,
        "hr_rate": hr_rate,
        "o2_rate": o2_rate,
        "map_rate": map_rate
    }

# -------------------------
# 2. Classify NYHA stage
# -------------------------
def classify_stage(features):
    hr = features["hr"]
    o2 = features["o2"]
    map_val = features["map"]

    if hr < 80 and o2 > 0.96:
        return "A"
    elif hr < 95 and o2 > 0.94:
        return "B"
    elif hr < 110 and o2 > 0.90:
        return "C"
    else:
        return "D"

# -------------------------
# 3. Risk scoring (ML replacement)
# -------------------------
def compute_risk(features):
    score = 0

    if features["hr"] > 100:
        score += 2
    if features["o2"] < 0.94:
        score += 3
    if features["map"] < 80:
        score += 3

    if features["hr_rate"] > 0.5:
        score += 2
    if features["o2_rate"] < -0.001:
        score += 2

    if score <= 3:
        return "LOW", score
    elif score <= 6:
        return "MODERATE", score
    else:
        return "HIGH", score

# -------------------------
# 4. Primary driver
# -------------------------
def find_driver(features):
    if features["o2"] < 0.94:
        return "Oxygen decline"
    elif features["map"] < 80:
        return "Low perfusion"
    elif features["hr"] > 100:
        return "Cardiac stress"
    else:
        return "Stable"

# -------------------------
# 5. Time to danger
# -------------------------
def estimate_time(features):
    hr = features["hr"]
    hr_rate = max(features["hr_rate"], 0.1)

    # crude projection
    days = (120 - hr) / (hr_rate * 10)

    return max(1, int(days))

# -------------------------
# 6. Projection engine
# -------------------------
def project(features):
    hr = features["hr"]
    o2 = features["o2"]

    projections = {
        "7d": {
            "hr": round(hr + 5, 1),
            "o2": round(o2 - 0.01, 3)
        },
        "14d": {
            "hr": round(hr + 10, 1),
            "o2": round(o2 - 0.03, 3)
        },
        "30d": {
            "hr": round(hr + 20, 1),
            "o2": round(o2 - 0.05, 3)
        }
    }

    return projections

# -------------------------
# 7. Main pipeline
# -------------------------
def analyze(csv_path):
    features = extract_features(csv_path)

    stage = classify_stage(features)
    risk, score = compute_risk(features)
    driver = find_driver(features)
    time = estimate_time(features)
    forecast = project(features)

    return {
        "features": features,
        "stage": stage,
        "risk": risk,
        "score": score,
        "driver": driver,
        "time_to_danger": time,
        "forecast": forecast
    }