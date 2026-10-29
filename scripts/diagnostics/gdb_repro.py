import sys; sys.path.insert(0,'/workspace')
from pulse.engine.PulseEngine import PulseEngine, eModelType
from pulse.cdm.patient import SEPatientConfiguration
from src.pulse_runner.sdk_runner import default_data_request_mgr
print("about to construct engine", flush=True)
engine = PulseEngine(eModelType.HumanAdultWholeBody, '/pulse/bin/')
print("constructed, about to init", flush=True)
pc = SEPatientConfiguration()
pc.set_patient_file('/workspace/scenarios/sdk_runner_verify/patient.json')
ok = engine.initialize_engine(pc, default_data_request_mgr())
print('OK', ok, flush=True)
