"""Generate editable examples, catalogs and a short analyst notebook."""
from pathlib import Path
import sys
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rca_bench.io import read_json, file_hash, write_json, write_jsonl, write_csv

ROOT=Path(__file__).resolve().parents[1]
workspace=ROOT.parent
catalog=ROOT/"catalog"
sources=[]
for p in sorted((workspace/"RCA").glob("*.docx")):
    sources.append(dict(path=str(p.relative_to(workspace)),sha256=file_hash(p)))
for p in [workspace/"structure_mau.txt",workspace/"Telecom_Abnormal_Detection_MLOps_Reference_Architecture.ipynb"]:
    sources.append(dict(path=p.name,sha256=file_hash(p)))
upstream=read_json(ROOT/"work/upstream/revision.json")
upstream["files"]={p.name:file_hash(p) for p in (ROOT/"work/upstream").iterdir() if p.is_file()}
write_json(catalog/"source_manifest.json",dict(review_date="2026-09-21",local_sources=sources,upstream=upstream,
    method="DOCX XML paragraph/table text extraction and direct source-code review; no original DOCX visual QA"))
write_csv(catalog/"datasets.csv",[
    dict(dataset="RCAEval RE1",modality="metric",target="service/indicator",status="metric importer",source="https://github.com/phamquiluan/RCAEval"),
    dict(dataset="RCAEval RE2/RE3",modality="metric/log/trace depending system",target="service/indicator",status="metric importer; log/trace roadmap",source="https://github.com/phamquiluan/RCAEval"),
    dict(dataset="AIOps 2020",modality="business/platform metrics, traces",target="fault time/type/location",status="survey",source="https://github.com/NetManAIOps/AIOps-Challenge-2020-Data"),
    dict(dataset="LogHub",modality="log",target="anomaly labels depend on subset",status="survey",source="https://github.com/logpai/loghub"),
    dict(dataset="Internal Gold",modality="VM/ES/LCM/topology",target="SME-confirmed root entity",status="contract ready; awaiting exports",source="local PL03 and operational tickets"),
    dict(dataset="Telecom synthetic",modality="metric/log/change/topology",target="injected entity",status="executed demo",source="rca_bench/synthetic.py"),
])
write_csv(catalog/"algorithms.csv",[
    dict(algorithm="stat_mad",family="Statistical",supervision="case pre-window",status="implemented",hyperparameters="context_weight"),
    dict(algorithm="stat_ewma",family="Statistical",supervision="case pre-window",status="implemented",hyperparameters="context_weight; alpha fixed in feature v1"),
    dict(algorithm="ml_logistic",family="ML",supervision="supervised candidate label",status="implemented",hyperparameters="lr,epochs,l2"),
    dict(algorithm="ml_pca",family="ML",supervision="normal-only",status="implemented",hyperparameters="components"),
    dict(algorithm="dl_mlp",family="DL",supervision="supervised candidate label",status="implemented",hyperparameters="hidden,lr,epochs,l2"),
    dict(algorithm="dl_autoencoder",family="DL",supervision="normal-only",status="implemented",hyperparameters="hidden,lr,epochs,l2"),
    dict(algorithm="MDA Drools",family="Product baseline",supervision="operator rules",status="external prediction adapter",hyperparameters="rule_version"),
    dict(algorithm="IF/LOF/RF/XGBoost",family="ML",supervision="method-dependent",status="survey only",hyperparameters="trees/depth/neighbors"),
    dict(algorithm="LSTM/TCN/GNN",family="DL",supervision="method-dependent",status="survey only",hyperparameters="sequence length/hidden/layers/edges"),
])
write_csv(catalog/"metrics.csv",[
    dict(metric="Hit/Recall@1,3,5; MRR; MAP; NDCG@5; Avg@5",unit="incident",implemented="yes",limitation="entity ranking only"),
    dict(metric="Chance Avg@5; Lift Avg@5",unit="fixed candidate universe",implemented="yes",limitation="uniform random rank reference"),
    dict(metric="Precision/Recall/F1/AP",unit="sampled window",implemented="yes",limitation="normal validation controls required"),
    dict(metric="p50/p95/p99",unit="milliseconds",implemented="yes",limitation="scoring and sorting only; profiler enabled"),
    dict(metric="CPU/wall time; Python traced memory",unit="seconds/bytes",implemented="yes",limitation="not total native RSS or GPU"),
    dict(metric="False alarms/hour; delay; MTTR",unit="continuous event / operations",implemented="no",limitation="requires continuous replay and human outcomes"),
])
case=dict(incident_id="incident-example",group_id="campaign-example",t0=1767225600,detected_at=1767225660,
          cutoff=1767226260,candidates=["ocs-service","aerospike-db","node-01"],root_entities=["aerospike-db"],
          is_incident=True,domain="OCS",fault_type="db",release="r1",label_tier="gold",label_source="REPLACE_WITH_TICKET",
          label_available_at=1767312000,availability_mode="retrospective",log_coverage_complete=False)
write_jsonl(ROOT/"examples/context/incidents.jsonl",[case])
write_jsonl(ROOT/"examples/context/changes.jsonl",[dict(incident_id=case["incident_id"],entity_id="aerospike-db",
          event_time=1767225300,available_at=1767225310,change_id="change-example",operation="upgrade")])
write_jsonl(ROOT/"examples/context/topology.jsonl",[dict(incident_id=case["incident_id"],source="aerospike-db",target="ocs-service",
          valid_from=1767000000,valid_to=1768000000,available_at=1767000000,relation="serves",version="topology-example")])
write_jsonl(ROOT/"examples/mda_predictions.example.jsonl",[dict(incident_id=case["incident_id"],observation_cutoff=case["cutoff"],
          ranks=["aerospike-db","ocs-service","node-01"],evidence=["REPLACE_WITH_ALARM_REF"],rule_version="REPLACE_WITH_RULE_VERSION")])
write_jsonl(ROOT/"examples/feedback.example.jsonl",[dict(incident_id=case["incident_id"],reviewer="REPLACE_WITH_REVIEWER",
          verdict="confirmed",root_entities=["aerospike-db"],evidence_refs=["REPLACE_WITH_TICKET"],label_available_at=1767312000,
          next_dataset_version="internal-gold-0.2.0")])
public_case={**case,"incident_id":"re1-example","group_id":"REPLACE_WITH_REPETITION_CAMPAIGN","candidates":["service_a","service_b"],
             "root_entities":["service_a"],"label_source":"REPLACE_WITH_PUBLIC_GROUND_TRUTH","domain":"public-microservice"}
write_json(ROOT/"examples/rcaeval_catalog.example.json",dict(dataset_version="rcaeval-metric-subset-0.1.0",
          upstream_ref=upstream["sha"],cases=[dict(metrics_file="REPLACE_WITH_DOWNLOADED_METRICS.csv",time_column="time",
          column_to_entity={"service_a_cpu":"service_a","service_b_cpu":"service_b"},case=public_case)]))
config=read_json(ROOT/"configs/demo.json")
config.update(dataset_version="internal-gold-0.1.0",label_tiers=["gold"])
write_json(ROOT/"configs/internal.example.json",config)

def md(text): return {"cell_type":"markdown","metadata":{},"source":text.splitlines(keepends=True)}
def code(text): return {"cell_type":"code","metadata":{},"source":text.splitlines(keepends=True),"execution_count":None,"outputs":[]}
cells=[
md("# Làm quen với benchmark RCA\n\nNotebook đọc kết quả đã chạy. Theo thứ tự: case → feature → split → trial → ranking → metric. Synthetic chỉ kiểm tra pipeline, chưa phản ánh mạng thật."),
code("from pathlib import Path\nimport json, csv\nroot = Path.cwd()\nif root.name == 'notebooks':\n    root = root.parent\nrun = root / 'runs/demo_final/run'\nprepared = root / 'runs/demo_final/prepared'\ndef read_json(path):\n    return json.loads(path.read_text(encoding='utf-8-sig'))\ndef read_jsonl(path):\n    return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s]\n"),
md("## 1 Một case gồm những gì\n`candidates` là tập cần xếp hạng. `root_entities` chỉ dùng làm nhãn; cutoff chốt thời điểm được nhìn thấy dữ liệu."),
code("cases = read_jsonl(prepared / 'cases.jsonl')\nprint(cases[-1])\nprint({s: sum(c['split']==s for c in cases) for s in ['train','validation','test']})\n"),
md("## 2 Feature và evidence\nMỗi row là một candidate trong một case; feature không chứa root label, fault type hoặc kết quả recovery."),
code("features = read_jsonl(prepared / 'features.jsonl')\nprint(features[-1])\n"),
md("## 3 Training và hyperparameter\nSo sánh validation trước; không dùng test để chọn cấu hình."),
code("with (run / 'trials.csv').open(encoding='utf-8-sig', newline='') as f:\n    trials = list(csv.DictReader(f))\nprint('Trials:', len(trials))\nprint(trials[:2])\n"),
md("## 4 Đọc ranking và kết quả\nScore cao chỉ là nghi vấn. Xem evidence trước khi kết luận nguyên nhân."),
code("pred = read_jsonl(run / 'predictions/ml_logistic-s42.jsonl')\nprint(pred[0])\nsummary = read_json(run / 'summary.json')\nfor algorithm, result in summary.items():\n    print(algorithm, result['aggregate']['mrr'], result['gate']['decision'])\n"),
md("## 5 Thử experiment mới\nDùng terminal chạy `python -m rca_bench demo --config configs/demo.json --output runs/new_demo`. Muốn thay modality, chạy `ablate`. Khi thay dữ liệu thật, đọc `docs/03_data_contract.md` và `docs/05_runbook.md` trước."),
]
for i,cell in enumerate(cells): cell["id"]=f"rca-cell-{i:02d}"
write_json(ROOT/"notebooks/01_walkthrough.ipynb",dict(cells=cells,metadata={"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python","version":"3.12"}},nbformat=4,nbformat_minor=5))
print("Catalogs, examples and notebook generated")
