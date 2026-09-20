"""Explicit mapping avoids guessing service names from underscore-delimited columns."""
from pathlib import Path
import time
import numpy as np
from .io import (file_hash, new_directory, read_csv, read_json, read_jsonl, seal, utc,
                 write_csv, write_json, write_jsonl)
from .evaluation import ranking_metrics, mean_ranking


def import_rcaeval(catalog_file, output):
    from .data import normalize_cases
    catalog = read_json(catalog_file)
    base, out = Path(catalog_file).parent, new_directory(output)
    metrics, cases, sources = [], [], []
    for item in catalog["cases"]:
        path = (base/item["metrics_file"]).resolve()
        if path.suffix == ".csv":
            records = read_csv(path)
        elif path.suffix == ".parquet":
            import pandas as pd
            records = pd.read_parquet(path).to_dict("records")
        else:
            raise ValueError("Use upstream preprocessed metrics CSV or Parquet; raw metrics.json needs upstream conversion")
        case = normalize_cases([item["case"]])[0]
        if case["availability_mode"] != "retrospective":
            raise ValueError("RCAEval metric timestamps do not prove ingestion time; use retrospective")
        mapping = item["column_to_entity"]
        if not mapping or not set(mapping) <= set(records[0]):
            raise ValueError("Explicit column_to_entity must match the source columns")
        if not set(mapping.values()) <= set(case["candidates"]):
            raise ValueError("Mapped entities must be in the predeclared candidate inventory")
        for r in records:
            for column, entity in mapping.items():
                value = float(r[column])
                if not np.isfinite(value):
                    continue  # missing retained through coverage, never filled with zero
                timestamp = utc(r[item.get("time_column","time")])
                metrics.append(dict(incident_id=case["incident_id"],entity_id=entity,metric=column,series_id=column,
                                    timestamp=timestamp,available_at=timestamp,value=value,
                                    kind=item.get("column_kinds",{}).get(column,"gauge")))
        cases.append(case)
        sources.append({"file":str(path),"sha256":file_hash(path),"column_to_entity":mapping})
    write_csv(out/"metrics.csv",metrics)
    write_jsonl(out/"incidents.jsonl",cases)
    for name in ["logs","changes","topology"]:
        write_jsonl(out/f"{name}.jsonl",[])
    write_json(out/"source.json",dict(kind="rcaeval-import",upstream_ref=catalog["upstream_ref"],sources=sources,
                                    protocol="internal temporal entity-ranking; not paper reproduction"))
    return seal(out,dict(stage="raw",dataset_version=catalog["dataset_version"],synthetic=False))


def evaluate_external(predictions_file, cases, config):
    """Missing product baseline cases count as failures, never silently disappear."""
    supplied = read_jsonl(predictions_file)
    ids = [p["incident_id"] for p in supplied]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate external predictions")
    by_id = {p["incident_id"]:p for p in supplied}
    if not set(by_id) <= {c["incident_id"] for c in cases}:
        raise ValueError("External results must contain test cases only")
    results = []
    for c in cases:
        p = by_id.get(c["incident_id"],{})
        ranking = p.get("ranks",[])
        if len(ranking) != len(set(ranking)):
            raise ValueError("Duplicate external candidates")
        if p and utc(p["observation_cutoff"]) != c["cutoff"]:
            raise ValueError("External baseline observation budget differs")
        results.append(dict(ranking_metrics=ranking_metrics(ranking,c["root_entities"],c["candidates"])))
    aggregate = mean_ranking(results)
    aggregate.update(evidence_coverage=sum(bool(p.get("evidence")) for p in supplied)/len(cases),
                     mrr_seed_std=0.0,latency_p95_ms=None)
    # Timing is optional and may come from a different machine: do not compare as native timing.
    return dict(aggregate=aggregate,coverage=len(supplied)/len(cases),missing_cases=len(cases)-len(supplied),
                prediction_file_hash=file_hash(predictions_file),gate=dict(decision="EXTERNAL_REVIEW",production_allowed=False))
