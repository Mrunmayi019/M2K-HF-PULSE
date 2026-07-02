import json

def create_scenario(condition, severity, hr, sex):

    # -------------------------
    # 1. Select patient
    # -------------------------
    if sex == "Female":
        patient_file = "StandardFemale.json"
    else:
        patient_file = "StandardMale.json"

    # -------------------------
    # 2. Safety limits (VERY IMPORTANT)
    # -------------------------
    # Keep everything in a stable range
    base_severity = float(severity)

    # General safe cap
    safe_severity = max(0.2, min(base_severity, 0.4))

    # Exercise-specific cap (Pulse hard limit = 0.5)
    exercise_severity = max(0.2, min(base_severity, 0.5))

    # -------------------------
    # 3. Choose action
    # -------------------------

    # HYPOXIA → use mild hemorrhage (clear effect, stable)
    if condition == "hypoxia":
        action = {
            "PatientAction": {
                "Hemorrhage": {
                    "Compartment": "Aorta",
                    "Severity": {
                        "Scalar0To1": {"Value": safe_severity}
                    }
                }
            }
        }

    # CARDIAC STRESS → exercise
    elif condition == "cardiac_stress":
        action = {
            "PatientAction": {
                "Exercise": {
                    "Intensity": {
                        "Scalar0To1": {"Value": exercise_severity}
                    }
                }
            }
        }

    # LOW BP / SHOCK → mild hemorrhage
    elif condition == "hypovolemia":
        action = {
            "PatientAction": {
                "Hemorrhage": {
                    "Compartment": "Aorta",
                    "Severity": {
                        "Scalar0To1": {"Value": safe_severity}
                    }
                }
            }
        }

    # RESPIRATORY STRESS → mild exercise
    elif condition == "respiratory_stress":
        action = {
            "PatientAction": {
                "Exercise": {
                    "Intensity": {
                        "Scalar0To1": {"Value": exercise_severity}
                    }
                }
            }
        }

    # ❤️ HEART FAILURE (simulate with controlled stress)
    elif condition == "heart_failure":
        action = {
            "PatientAction": {
                "Exercise": {
                    "Intensity": {
                        "Scalar0To1": {"Value": max(0.3, exercise_severity)}
                    }
                }
            }
        }

    # ❤️ HF + LOW PERFUSION (controlled, not extreme)
    elif condition == "hf_shock":
        action = {
            "PatientAction": {
                "Hemorrhage": {
                    "Compartment": "Aorta",
                    "Severity": {
                        "Scalar0To1": {"Value": max(0.3, safe_severity)}
                    }
                }
            }
        }

    # NORMAL
    else:
        action = {
            "AdvanceTime": {
                "Time": {
                    "ScalarTime": {"Value": 60, "Unit": "s"}
                }
            }
        }

    # -------------------------
    # 4. Build JSON
    # -------------------------

    scenario = {
        "PatientConfiguration": {
            "PatientFile": patient_file
        },

        "DataRequestManager": {
            "DataRequest": [
                {"Category": "Physiology", "PropertyName": "HeartRate"},
                {"Category": "Physiology", "PropertyName": "OxygenSaturation"},
                {"Category": "Physiology", "PropertyName": "MeanArterialPressure"},
                {"Category": "Physiology", "PropertyName": "CardiacOutput"}
            ]
        },

        "AnyAction": [
            {
                "AdvanceTime": {
                    "Time": {
                        "ScalarTime": {"Value": 60, "Unit": "s"}
                    }
                }
            },

            action,

            {
                "AdvanceTime": {
                    "Time": {
                        "ScalarTime": {"Value": 240, "Unit": "s"}
                    }
                }
            }
        ]
    }

    # -------------------------
    # 5. Save file
    # -------------------------

    file_path = "/workspace/scenarios/generated.json"

    with open(file_path, "w") as f:
        json.dump(scenario, f, indent=2)

    return file_path