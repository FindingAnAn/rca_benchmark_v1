import argparse
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
from .io import read_json, read_jsonl, seal, write_json, write_jsonl, write_csv


def main():
    parser = argparse.ArgumentParser(description="Internal RCA benchmark: survey/raw/train/tune/evaluate/registry")
    sub = parser.add_subparsers(dest="command",required=True)
    for name in ["demo","prepare","benchmark","ablate"]:
        p = sub.add_parser(name)
        p.add_argument("--config",default="configs/demo.json")
        p.add_argument("--output",required=True)
        if name in ["prepare","ablate"]:
            p.add_argument("--raw",required=True)
        if name == "benchmark":
            p.add_argument("--prepared",required=True)
            p.add_argument("--external-predictions")
    p = sub.add_parser("ingest")
    p.add_argument("--sources",required=True)
    p.add_argument("--context",required=True)
    p.add_argument("--output",required=True)
    p = sub.add_parser("seal-raw")
    p.add_argument("--raw",required=True)
    p.add_argument("--dataset-version",required=True)
    p = sub.add_parser("import-rcaeval")
    p.add_argument("--catalog",required=True)
    p.add_argument("--output",required=True)
    p = sub.add_parser("registry")
    p.add_argument("--db",required=True)
    p = sub.add_parser("review")
    for key in ["db","run-id","decision","reviewer","reason"]:
        p.add_argument("--"+key,required=True)
    p = sub.add_parser("score")
    for key in ["model","features","output"]:
        p.add_argument("--"+key,required=True)
    p = sub.add_parser("drift")
    p.add_argument("--reference",required=True)
    p.add_argument("--current",required=True)
    p.add_argument("--output",required=True)
    args = parser.parse_args()
    if args.command in ["demo","prepare","benchmark","ablate"]:
        config = read_json(args.config)
        from .data import prepare
        from .runner import benchmark
        if args.command == "demo":
            from .synthetic import generate
            output = Path(args.output)
            output.mkdir(parents=True,exist_ok=False)
            generate(output/"raw",config)
            prepare(output/"raw",output/"prepared",config)
            benchmark(output/"prepared",output/"run",config)
            print(str((output/"run"/"report.html").resolve()))
        elif args.command == "prepare":
            prepare(args.raw,args.output,config)
        elif args.command == "benchmark":
            benchmark(args.prepared,args.output,config,args.external_predictions)
        else:
            output = Path(args.output)
            output.mkdir(parents=True,exist_ok=False)
            table = []
            for name,mods in [("metric",["metric"]),("log",["log"]),("metric_log",["metric","log"]),
                              ("plus_change",["metric","log","change"]),("full",["metric","log","change","topology"])]:
                variant = deepcopy(config)
                variant["modalities"] = mods
                prepare(args.raw,output/name/"prepared",variant)
                scores = benchmark(output/name/"prepared",output/name/"run",variant)
                table.extend(dict(ablation=name,algorithm=k,**v["aggregate"]) for k,v in scores.items())
            write_csv(output/"ablation.csv",table)
    elif args.command == "ingest":
        from .connectors import ingest
        ingest(read_json(args.sources),args.context,args.output)
    elif args.command == "seal-raw":
        if (Path(args.raw)/"manifest.json").exists():
            raise ValueError("Raw already sealed: create a new version instead of resealing")
        seal(args.raw,dict(stage="raw",synthetic=False,dataset_version=args.dataset_version))
    elif args.command == "import-rcaeval":
        from .adapters import import_rcaeval
        import_rcaeval(args.catalog,args.output)
    elif args.command == "registry":
        from .registry import list_runs
        print(json.dumps(list_runs(args.db),indent=2))
    elif args.command == "review":
        from .registry import review
        review(args.db,args.run_id,args.decision,args.reviewer,args.reason)
    elif args.command == "score":
        from .models import Baseline
        from collections import defaultdict
        model = Baseline.load(args.model)
        groups = defaultdict(list)
        for row in read_jsonl(args.features):
            groups[row["incident_id"]].append(row)
        output = []
        for incident_id,rows in groups.items():
            x = np.array([[r["features"][f] for f in model.feature_names] for r in rows])
            scores = model.score(x)
            if not np.isfinite(scores).all():
                raise ValueError("Nonfinite scores")
            order = sorted(range(len(rows)),key=lambda i:(-scores[i],rows[i]["entity_id"]))
            output.append(dict(incident_id=incident_id,algorithm=model.name,
                     ranks=[dict(entity_id=rows[i]["entity_id"],score=float(scores[i]),evidence=rows[i].get("evidence",[])) for i in order]))
        write_jsonl(args.output,output)
    elif args.command == "drift":
        from .monitoring import drift
        write_json(args.output,drift(args.reference,args.current))


if __name__ == "__main__":
    main()
