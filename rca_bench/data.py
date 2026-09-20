"""Incident windows and temporal, group-disjoint dataset preparation."""
from collections import defaultdict
from pathlib import Path
import math
import re
import numpy as np
from .io import (canonical, new_directory, read_csv, read_jsonl, seal, utc, verify,
                 write_csv, write_json, write_jsonl)

FEATURES = {
    "metric": ["metric_max_abs_z", "metric_mean_abs_z", "metric_ewma_z", "metric_missing"],
    "log": ["log_error_burst", "log_error_rate", "log_new_template", "log_missing"],
    "change": ["recent_change"],
    "topology": ["neighbor_evidence"],
}


def deduplicate(rows, keys):
    """Only exact payload duplicates are removed; conflicting values fail DQ."""
    unique, seen, duplicates = [], {}, 0
    for row in rows:
        key, payload = tuple(row[k] for k in keys), canonical(row)
        if key in seen:
            if seen[key] != payload:
                raise ValueError(f"Conflicting payload for key {key}")
            duplicates += 1
            continue
        seen[key] = payload
        unique.append(row)
    return unique, duplicates


def temporal_split(cases, config):
    groups = defaultdict(list)
    for case in cases:
        groups[case["group_id"]].append(case)
    ordered = sorted(groups.values(), key=lambda g: min(c["t0"] for c in g))
    n = len(ordered)
    a, b = int(n*config["train_fraction"]), int(n*(config["train_fraction"]+config["validation_fraction"]))
    if not 0 < a < b < n:
        raise ValueError("Need nonempty train/validation/test groups")
    blocks = [sum(ordered[:a], []), sum(ordered[a:b], []), sum(ordered[b:], [])]
    pre, embargo = config["pre_seconds"], config.get("embargo_seconds", 0)
    for left, right in zip(blocks, blocks[1:]):
        if max(c["cutoff"] for c in left) + embargo >= min(c.get("detected_at",c["t0"])-pre for c in right):
            raise ValueError("Temporal split overlaps or repetition group crosses boundary; revise groups/cutoffs")
    # Labels must have been available by the start of the next evaluation period.
    for left, right in zip(blocks, blocks[1:]):
        if max(c["label_available_at"] for c in left) >= min(c["t0"] for c in right):
            raise ValueError("Delayed labels unavailable before next split")
    return {c["incident_id"]: name for name, block in zip(["train", "validation", "test"], blocks) for c in block}


def normalize_cases(cases):
    ids = set()
    for c in cases:
        for field in ["incident_id", "group_id", "t0", "detected_at", "cutoff", "root_entities",
                      "candidates", "is_incident", "label_tier", "label_source", "label_available_at",
                      "availability_mode", "log_coverage_complete"]:
            if field not in c:
                raise ValueError(f"Missing case field: {field}")
        if c["incident_id"] in ids:
            raise ValueError("Duplicate incident ID")
        ids.add(c["incident_id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", c["incident_id"]) or c["incident_id"] in [".", ".."]:
            raise ValueError("incident_id must be a safe stable identifier")
        for key in ["t0", "detected_at", "cutoff", "label_available_at"]:
            c[key] = utc(c[key])
            if not math.isfinite(c[key]):
                raise ValueError("Nonfinite case timestamp")
        if not c["t0"] <= c["detected_at"] < c["cutoff"]:
            raise ValueError("Require t0 <= detected_at < cutoff")
        if not isinstance(c["is_incident"], bool) or bool(c["root_entities"]) != c["is_incident"]:
            raise ValueError("Incident labels inconsistent")
        if not c["candidates"] or len(set(c["candidates"])) != len(c["candidates"]):
            raise ValueError("Empty or duplicate candidates")
        if c["availability_mode"] not in ["recorded", "retrospective"]:
            raise ValueError("Declare recorded/retrospective telemetry availability")
    return cases


def build_case(case, metrics, logs, changes, topology, config):
    t0, cutoff = case["detected_at"], case["cutoff"]
    pre = config["pre_seconds"]
    step = config["step_seconds"]
    mods = config["modalities"]
    rows = []
    def in_window(r, time_key="timestamp"):
        return t0-pre <= utc(r[time_key]) <= cutoff and utc(r["available_at"]) <= cutoff
    metrics = [r for r in metrics if in_window(r)]
    logs = [r for r in logs if in_window(r)]
    for entity in case["candidates"]:
        features = {f: 0.0 for fs in FEATURES.values() for f in fs}
        evidence, series = [], defaultdict(list)
        for r in metrics:
            if r["entity_id"] == entity:
                series[r["series_id"]].append(r)
        maxzs, means, ewmas, coverage = [], [], [], []
        for name, values in series.items():
            values.sort(key=lambda r: utc(r["timestamp"]))
            before = [r for r in values if utc(r["timestamp"]) < t0]
            after = [r for r in values if utc(r["timestamp"]) >= t0]
            expected_pre = max(1, int(pre/step))
            expected_post = max(1, int((cutoff-t0)/step)+1)
            cov = min(1, len(before)/expected_pre, len(after)/expected_post)
            coverage.append(cov)
            if len(before) < 5 or not after:
                continue
            a = np.array([float(r["value"]) for r in before])
            b = np.array([float(r["value"]) for r in after])
            center = np.median(a)
            scale = max(1.4826*np.median(np.abs(a-center)), abs(center)*0.01, 1e-6)
            z = np.clip((b-center)/scale, -100, 100)
            maxzs.append(float(np.max(np.abs(z))))
            means.append(float(np.mean(np.abs(z))))
            ewma, highest = 0.0, 0.0
            for v in z:
                ewma = 0.3*v + 0.7*ewma
                highest = max(highest, abs(ewma))
            ewmas.append(highest)
            if "metric" in mods:
                idx = int(np.argmax(np.abs(z)))
                evidence.append(dict(source="metric", ref=name, timestamp=utc(after[idx]["timestamp"]),
                                     value=float(b[idx]), baseline=float(center), abs_z=maxzs[-1]))
        features.update(metric_max_abs_z=max(maxzs, default=0), metric_mean_abs_z=max(means, default=0),
                        metric_ewma_z=max(ewmas, default=0), metric_missing=1-min(coverage, default=0))
        if "metric" in mods and (not maxzs or min(coverage, default=0) < config["min_metric_coverage"]):
            raise ValueError(f"Metric coverage failed: {case['incident_id']}/{entity}")
        elogs = [r for r in logs if r["entity_id"] == entity]
        old = [r for r in elogs if utc(r["timestamp"]) < t0]
        new = [r for r in elogs if utc(r["timestamp"]) >= t0]
        err_old = sum(r["level"].upper() in ["ERROR", "FATAL", "CRITICAL"] for r in old)
        errors = [r for r in new if r["level"].upper() in ["ERROR", "FATAL", "CRITICAL"]]
        old_templates = {r["template_id"] for r in old}
        duration = max(1, cutoff-t0)
        features.update(log_error_burst=float(np.log1p(len(errors)/max(1, err_old*duration/pre))),
                        log_error_rate=len(errors)/max(1, len(new)),
                        log_new_template=sum(r["template_id"] not in old_templates for r in new)/max(1, len(new)),
                        log_missing=float(not case["log_coverage_complete"]))
        if "log" in mods and not case["log_coverage_complete"]:
            raise ValueError("Log completeness unknown; do not treat missing logs as zero errors")
        if "log" in mods:
            evidence.extend(dict(source="log", ref=r["event_id"], timestamp=utc(r["timestamp"]),
                                 template=r["template_id"]) for r in errors[:3])
        relevant = [r for r in changes if r["entity_id"] == entity and
                    t0-86400 <= utc(r["event_time"]) <= cutoff and utc(r["available_at"]) <= cutoff]
        if relevant:
            latest = max(relevant, key=lambda r: utc(r["event_time"]))
            features["recent_change"] = math.exp(-(cutoff-utc(latest["event_time"]))/3600)
            if "change" in mods:
                evidence.append(dict(source="change", ref=latest["change_id"], timestamp=utc(latest["event_time"]),
                                     operation=latest["operation"]))
        rows.append(dict(incident_id=case["incident_id"], entity_id=entity, features=features,
                         label=int(entity in case["root_entities"]), evidence=evidence))
    # A topology heuristic, not a learned causal graph. Edge is source -> affected dependent.
    by_entity = {r["entity_id"]: r for r in rows}
    for row in rows:
        edges = [e for e in topology if e["source"] == row["entity_id"] and
                 utc(e["valid_from"]) <= t0 < utc(e["valid_to"]) and utc(e["available_at"]) <= cutoff]
        strengths = []
        for edge in edges:
            neighbor = by_entity.get(edge["target"])
            if neighbor:
                f = neighbor["features"]
                strengths.append((f["metric_mean_abs_z"] if "metric" in mods else 0) +
                                 (f["log_error_burst"] if "log" in mods else 0))
        row["features"]["neighbor_evidence"] = max(strengths, default=0)
        row["features"] = {f: row["features"][f] for mod in mods for f in FEATURES[mod]}
        if "topology" in mods:
            row["evidence"].extend(dict(source="topology", ref=e["version"], target=e["target"],
                                        timestamp=utc(e["valid_from"])) for e in edges[:3])
    return rows


def prepare(raw, output, config):
    manifest = verify(raw)
    if manifest["dataset_version"] != config["dataset_version"]:
        raise ValueError("Raw dataset version differs from config")
    raw = Path(raw)
    cases = normalize_cases(read_jsonl(raw / "incidents.jsonl"))
    if any(c["label_tier"] not in config["label_tiers"] for c in cases):
        raise ValueError("Label tiers differ from configured benchmark; split gold/silver/synthetic explicitly")
    if any(abs(c["cutoff"]-c["detected_at"]-config["post_seconds"]) > 1e-6 for c in cases):
        raise ValueError("Case cutoff must match the declared observation budget post_seconds")
    if not set(config["modalities"]) <= set(FEATURES) or not config["modalities"]:
        raise ValueError("Unknown/empty modality")
    data, dq = {}, {}
    for kind, filename, keys in [
        ("metric", "metrics.csv", ["incident_id", "series_id", "timestamp"]),
        ("log", "logs.jsonl", ["incident_id", "event_id"]),
        ("change", "changes.jsonl", ["incident_id", "change_id"]),
        ("topology", "topology.jsonl", ["incident_id", "source", "target", "valid_from"]),
    ]:
        if kind not in config["modalities"]:
            data[kind] = defaultdict(list)
            continue
        path = raw / filename
        if not path.exists():
            raise ValueError(f"Missing modality file {filename}")
        values = read_csv(path) if kind == "metric" else read_jsonl(path)
        for r in values:
            for key in ["timestamp", "available_at", "event_time", "valid_from", "valid_to"]:
                if key in r:
                    r[key] = utc(r[key])
                    if not math.isfinite(r[key]):
                        raise ValueError("Nonfinite telemetry timestamp")
            if kind == "metric":
                r["value"] = float(r["value"])
                if not math.isfinite(r["value"]) or r["kind"] not in ["gauge", "rate"]:
                    raise ValueError("Metric values must be finite gauges/rates; convert counters first")
        values, dup = deduplicate(values, keys)
        dq[kind] = {"input_rows": len(values)+dup, "exact_duplicates": dup, "accepted_rows": len(values)}
        groups = defaultdict(list)
        for r in values:
            if r["incident_id"] not in {c["incident_id"] for c in cases}:
                raise ValueError("Orphan telemetry incident_id")
            groups[r["incident_id"]].append(r)
        data[kind] = groups
    splits = temporal_split(cases, config)
    rows = []
    for c in cases:
        c["split"] = splits[c["incident_id"]]
        built = build_case(c, *[data[k][c["incident_id"]] for k in FEATURES], config)
        for r in built:
            r["split"] = c["split"]
        rows.extend(built)
    out = new_directory(output)
    write_jsonl(out / "cases.jsonl", cases)
    write_jsonl(out / "features.jsonl", rows)
    write_json(out / "config.json", config)
    write_json(out / "dq_report.json", {"status": "PASS", "sources": dq, "n_cases": len(cases),
               "candidate_label_coverage": sum(set(c["root_entities"]) <= set(c["candidates"]) for c in cases)/len(cases)})
    write_csv(out / "splits.csv", [dict(incident_id=c["incident_id"], group_id=c["group_id"], split=c["split"],
                                        t0=c["t0"], cutoff=c["cutoff"], release=c.get("release", "unknown")) for c in cases])
    return seal(out, dict(stage="prepared", parent_hash=manifest["content_hash"],
                         dataset_version=config["dataset_version"], feature_version=config["feature_version"],
                         synthetic=manifest.get("synthetic", False), feature_names=list(rows[0]["features"])))
