import subprocess

def run_pulse(scenario_path):
    cmd = [
        "/pulse/bin/PulseScenarioDriver",
        scenario_path
    ]

    subprocess.run(cmd, cwd="/pulse/bin")  # VERY IMPORTANT

    return "/workspace/scenarios/generatedResults.csv"