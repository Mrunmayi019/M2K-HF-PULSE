def detect_condition(hr, spo2, bp, rr, age):

    # Hypoxia
    if spo2 < 94:
        severity = min((94 - spo2) / 5, 1)
        return "hypoxia", severity

    # Heart failure (simple logic)
    elif hr > 110 and bp < 100:
        severity = min((hr - 100) / 40, 1)
        return "heart_failure", severity

    # HF + shock
    elif hr > 120 and bp < 85:
        severity = min((hr - 100) / 30, 1)
        return "hf_shock", severity

    # Low BP
    elif bp < 90:
        severity = min((90 - bp) / 40, 1)
        return "hypovolemia", severity

    # Cardiac stress
    elif hr > 100:
        severity = min((hr - 100) / 40, 1)
        return "cardiac_stress", severity

    # Respiratory stress
    elif rr > 20:
        severity = min((rr - 20) / 20, 1)
        return "respiratory_stress", severity

    else:
        return "normal", 0.0