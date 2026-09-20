"""Synthetic integration fixture with controls, propagation and distractors."""
import numpy as np
from .io import new_directory, seal, write_csv, write_json, write_jsonl


def generate(folder, config):
    out = new_directory(folder)
    rng = np.random.default_rng(config["seed"])
    entities = ["amf", "smf", "upf", "pcf", "chf", "ocs", "aerospike", "worker-node"]
    domains = ["Core"] * 5 + ["OCS", "OCS", "MANO"]
    metrics, logs, cases, changes, topology = [], [], [], [], []
    start = 1756684800
    step = config["step_seconds"]
    pre, post = config["pre_seconds"], config["post_seconds"]
    for i in range(config["n_cases"]):
        t0 = start + i * 3 * 3600
        case_id = f"demo-{i:03d}"
        normal = i % 5 == 0
        root = int(rng.integers(len(entities)))
        fault = ["cpu", "network", "config"][i % 3] if not normal else "normal"
        causes = [] if normal else [entities[root]]
        if not normal and i % 13 == 0:
            causes.append(entities[(root + 3) % len(entities)])
        symptom = entities[(root + 1) % len(entities)]
        cases.append(dict(incident_id=case_id, group_id=case_id, t0=t0, detected_at=t0,
                          cutoff=t0 + post, root_entities=causes, is_incident=not normal,
                          candidates=entities, symptom_entity=symptom, domain=domains[root],
                          fault_type=fault, release=f"r{1 + i // 30}", label_tier="synthetic",
                          label_source="seeded_injection", label_available_at=t0 + 3600,
                          availability_mode="recorded", log_coverage_complete=True))
        for j, entity in enumerate(entities):
            changed = rng.random() < (0.8 if entity in causes and fault == "config" else 0.16)
            if changed:
                changes.append(dict(incident_id=case_id, entity_id=entity, event_time=t0 - 180,
                                    available_at=t0 - 170, operation="upgrade", change_id=f"chg-{i}-{j}"))
            topology.append(dict(incident_id=case_id, source=entity, target=symptom,
                                 valid_from=t0-pre, valid_to=t0+post+1, available_at=t0-pre,
                                 relation="depends_on", version=f"topology-{i}"))
            for t in range(t0-pre, t0+post+step, step):
                active = t >= t0 and entity in causes
                propagated = not normal and entity == symptom and t >= t0+120
                for name, base, sigma in [("cpu", 40, 4), ("latency_ms", 30, 3)]:
                    shift = (rng.uniform(15, 30) if active else 0)
                    if fault == "config" and name == "cpu":
                        shift *= 0.15
                    if fault == "network" and name == "latency_ms":
                        shift *= -0.8 if i % 2 else 1.5
                    if propagated:
                        shift += 20  # symptom can exceed the root metric
                    value = base + rng.normal(0, sigma) + shift
                    if rng.random() < 0.012 and t < t0:
                        continue
                    metrics.append(dict(incident_id=case_id, entity_id=entity, metric=name,
                                        series_id=entity+":"+name, timestamp=t, available_at=t+5,
                                        value=round(float(value), 5), kind="gauge"))
                n_logs = int(rng.poisson(0.18 + 1.0*active + 0.65*propagated))
                for k in range(n_logs):
                    level = "ERROR" if rng.random() < (0.85 if active else 0.1) else "INFO"
                    logs.append(dict(incident_id=case_id, entity_id=entity, timestamp=t,
                                     available_at=t+3, event_id=f"{case_id}-{j}-{t}-{k}",
                                     level=level, template_id="request_failed" if level=="ERROR" else "request_ok"))
    write_csv(out / "metrics.csv", metrics)
    write_jsonl(out / "logs.jsonl", logs)
    write_jsonl(out / "incidents.jsonl", cases)
    write_jsonl(out / "changes.jsonl", changes)
    write_jsonl(out / "topology.jsonl", topology)
    write_json(out / "source.json", {"kind": "synthetic", "seed": config["seed"],
                                    "warning": "Integration demo only; not production or RCAEval performance"})
    return seal(out, {"stage": "raw", "dataset_version": config["dataset_version"], "synthetic": True})
