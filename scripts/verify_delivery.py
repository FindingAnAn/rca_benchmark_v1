"""Verify the shipped demo, ablations and notebook without mutating snapshots."""
from pathlib import Path
import contextlib
import csv
import io
import json
import os
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rca_bench.io import file_hash, read_json, stamp, verify, write_json

root=Path(__file__).resolve().parents[1]
os.chdir(root)
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(root/"tests"))
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
checks={"unit_and_integration_tests":result.wasSuccessful(),"tests_run":result.testsRun}
(root/"reports").mkdir(exist_ok=True)
(root/"reports/test_results.txt").write_text(stream.getvalue(),encoding="utf-8")
if not result.wasSuccessful():
    print(stream.getvalue())
    raise SystemExit(1)
snapshots=[root/"runs/demo_final/raw",root/"runs/demo_final/prepared",*list((root/"runs/ablation_final").glob("*/prepared"))]
for p in snapshots: verify(p)
checks["verified_snapshots"]=len(snapshots)
runs=[root/"runs/demo_final/run",*list((root/"runs/ablation_final").glob("*/run"))]
for p in runs:
    m=read_json(p/"run_manifest.json")
    assert m["status"]=="COMPLETED"
    assert all(file_hash(p/k)==v for k,v in m["artifact_hashes"].items())
    assert all(file_hash(root/"rca_bench"/k)==v for k,v in m["code_files"].items())
checks["verified_runs"]=len(runs)
nb=read_json(root/"notebooks/01_walkthrough.ipynb")
scope={}
with contextlib.redirect_stdout(io.StringIO()):
    for c in nb["cells"]:
        if c["cell_type"]=="code": exec(compile("".join(c["source"]),"walkthrough","exec"),scope)
checks["notebook_code_cells"]="PASS"
with (root/"runs/ablation_final/ablation.csv").open(encoding="utf-8-sig") as f:
    rows=list(csv.DictReader(f))
assert len(rows)==30
checks["ablation_rows"]=len(rows)
checks["verified_at"]=stamp()
checks["live_VM_ES_verified"]=False
checks["official_RCAEval_methods_executed"]=False
checks["production_readiness"]=False
write_json(root/"reports/validation.json",checks)
print(json.dumps(checks,indent=2))
