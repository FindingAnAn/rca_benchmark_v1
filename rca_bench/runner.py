"""Train -> validation selection -> frozen test -> auditable report."""
from collections import defaultdict
import html
import platform
from pathlib import Path
import sys
import time
import traceback
import tracemalloc
import numpy as np
from .data import FEATURES
from .evaluation import (bootstrap_mrr, detection_metrics, mean_ranking, ranking_metrics, tune_threshold)
from .io import (digest, file_hash, new_directory, read_json, read_jsonl, stamp, verify,
                 write_csv, write_json, write_jsonl)
from .models import Baseline
from . import registry


def predict_cases(model, rows, cases, features):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["incident_id"]].append(row)
    results = []
    for c in cases:
        records = grouped[c["incident_id"]]
        start = time.perf_counter()
        error = None
        try:
            x = np.array([[r["features"][f] for f in features] for r in records])
            scores = model.score(x)
            if not np.isfinite(scores).all():
                raise ValueError("Nonfinite predictions")
            order = sorted(range(len(records)), key=lambda i: (-scores[i], records[i]["entity_id"]))
            ranking = [dict(entity_id=records[i]["entity_id"], score=float(scores[i]),
                            evidence=records[i]["evidence"]) for i in order]
        except Exception as exc:
            ranking, error = [], type(exc).__name__+": "+str(exc)
        elapsed = (time.perf_counter()-start)*1000
        results.append(dict(incident_id=c["incident_id"], group_id=c["group_id"],
                            domain=c.get("domain","unknown"), fault_type=c.get("fault_type","unknown"),
                            release=c.get("release","unknown"), is_incident=c["is_incident"],
                            root_entities=c["root_entities"], candidates=c["candidates"],
                            ranking=ranking, case_score=ranking[0]["score"] if ranking else -1e30,
                            latency_ms=elapsed, error=error,
                            ranking_metrics=ranking_metrics([r["entity_id"] for r in ranking],c["root_entities"],c["candidates"])))
    return results


def summarize(results, threshold, config):
    summary = mean_ranking(results)
    latencies = [r["latency_ms"] for r in results]
    summary.update(n_cases=len(results), n_incidents=sum(r["is_incident"] for r in results),
                   failures=sum(r["error"] is not None for r in results),
                   latency_ms={str(p):float(np.percentile(latencies,p)) for p in [50,95,99]},
                   evidence_coverage=sum(bool(r["ranking"] and r["ranking"][0]["evidence"]) for r in results)/max(1,len(results)),
                   mrr_ci95=bootstrap_mrr(results, config["seed"], config.get("bootstrap_samples",300)))
    summary["detection"] = detection_metrics([r["is_incident"] for r in results],
              [r["case_score"] for r in results],threshold) if threshold is not None else None
    summary["slices"] = {}
    for key in ["domain", "fault_type", "release"]:
        summary["slices"][key] = {v:{"n_cases":sum(r[key]==v for r in results),
                                      **mean_ranking([r for r in results if r[key]==v])}
                                  for v in sorted({r[key] for r in results})}
    return summary


def _html_report(out, manifest, summary):
    table = []
    for name, item in summary.items():
        row = item["aggregate"]
        table.append("<tr>"+"".join(f"<td>{html.escape(str(v))}</td>" for v in [name,
                     f"{row.get('hit1',0):.3f}", f"{row.get('hit3',0):.3f}", f"{row.get('mrr',0):.3f}",
                     f"{row.get('avg5',0):.3f}", f"{row.get('chance_avg5',0):.3f}",
                     (f"{row['latency_p95_ms']:.2f}" if row.get('latency_p95_ms') is not None else "N/A"), item["gate"]["decision"]])+"</tr>")
    body = f'''<!doctype html><html lang="vi"><meta charset="utf-8"><title>RCA benchmark</title>
<style>body{{font:16px/1.6 system-ui;color:#172536;background:#f5f7fb;max-width:1200px;margin:40px auto;padding:24px}}
h1{{font-size:32px}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #dce1e9}}
th{{background:#18364d;color:white}}.note{{background:#fff3cd;border-left:5px solid #b68000;padding:16px}}a{{color:#075b98}}
code{{background:#e5ebf3;padding:2px 5px}}details{{margin-top:24px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>Benchmark RCA nội bộ</h1><p>Run <code>{html.escape(manifest['run_id'])}</code> · {html.escape(manifest['created_at'])}</p>
<p class="note">{'DỮ LIỆU SYNTHETIC — chỉ kiểm tra pipeline, không chứng minh hiệu năng MANO/5G/OCS.' if manifest['synthetic'] else 'Kết quả offline trên dataset đã đóng băng; chưa phải nghiệm thu production.'}</p>
<p>So sánh trên cùng tập candidate và split theo thời gian. Hyperparameter chọn bằng MRR validation trung bình qua các seed. Điểm dưới đây là trung bình seed trên test.</p>
<table><thead><tr><th>Thuật toán</th><th>Hit@1</th><th>Hit@3</th><th>MRR</th><th>Avg@5</th><th>Chance@5</th><th>p95 ms*</th><th>Trạng thái</th></tr></thead><tbody>{''.join(table)}</tbody></table>
<p>* Trung bình p95 theo seed, chỉ đo dựng ma trận + scoring + sắp xếp candidate; chưa gồm query/feature build/network. Top-k biểu diễn nghi vấn cần kiểm chứng.</p>
<p><a href="summary.json">Metric, confidence interval và slice</a> · <a href="leaderboard.csv">Bảng CSV</a> · <a href="trials.csv">Hyperparameter trials</a> · <a href="run_manifest.json">Lineage</a></p>
<h2>Đọc kết quả</h2><p>Hit@k: tìm thấy ít nhất một nguyên nhân trong top-k. Với nhiều nguyên nhân, Recall@k và Avg@5 đo mức bao phủ. MRR thưởng đáp án đúng ở đầu danh sách. Lift@5 = Avg@5 − Chance@5.</p>
<p>Detection chỉ được đo trên các cửa sổ incident/control lấy mẫu. False alarms/hour, detection delay, MTTR, CPU/GPU peak và human acceptance chưa có phép đo phù hợp nên không suy diễn.</p>
<h2>Lifecycle</h2><p>Raw snapshot → kiểm tra dữ liệu → feature và split → train/tune → test → registry → review → shadow theo quy trình nội bộ. Bộ này không thực thi heal/rollback.</p>
<details><summary>Thông tin tài nguyên và giới hạn</summary><pre>{html.escape(str(manifest.get('resource',{})))}</pre></details></html>'''
    (out / "report.html").write_text(body, encoding="utf-8")


def benchmark(prepared, output, config, external_predictions=None):
    source_manifest = verify(prepared)
    prepared = Path(prepared)
    prepared_config = read_json(prepared / "config.json")
    for field in ["dataset_version", "feature_version", "modalities", "pre_seconds", "post_seconds", "step_seconds"]:
        if prepared_config[field] != config[field]:
            raise ValueError(f"Prepared data/config mismatch: {field}")
    out = new_directory(output)
    db = out.parent / "registry.sqlite"
    run_id = out.name
    source_root = Path(__file__).parent
    code_files = {p.name:file_hash(p) for p in source_root.glob("*.py")}
    manifest = dict(run_id=run_id, status="RUNNING", created_at=stamp(), dataset_hash=source_manifest["content_hash"],
                    raw_hash=source_manifest["parent_hash"], synthetic=source_manifest.get("synthetic",False),
                    code_hash=digest(code_files), code_files=code_files, config_hash=digest(config), config=config,
                    environment={"python":sys.version,"numpy":np.__version__,"platform":platform.platform()},
                    selection="highest mean validation MRR across configured seeds; tie: first config",
                    test_usage="all algorithms evaluated once per selected config/seed; no refit on validation")
    write_json(out / "run_manifest.json", manifest)
    registry.record(db,run_id,"RUNNING",manifest)
    tracemalloc.start()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    try:
        cases = read_jsonl(prepared / "cases.jsonl")
        rows = read_jsonl(prepared / "features.jsonl")
        features = source_manifest["feature_names"]
        train_cases = {c["incident_id"]:c for c in cases if c["split"]=="train"}
        train = [r for r in rows if r["split"]=="train"]
        x = np.array([[r["features"][f] for f in features] for r in train])
        y = np.array([r["label"] for r in train],dtype=float)
        normal = np.array([not train_cases[r["incident_id"]]["is_incident"] for r in train])
        val_cases, test_cases = ([c for c in cases if c["split"]==s] for s in ["validation","test"])
        val_rows, test_rows = ([r for r in rows if r["split"]==s] for s in ["validation","test"])
        if not any(c["is_incident"] for c in val_cases) or not any(c["is_incident"] for c in test_cases):
            raise ValueError("Validation/test require incident labels for RCA evaluation")
        trials, summary = [], {}
        for name, grid in config["algorithms"].items():
            options = []
            for index, params in enumerate(grid):
                per_seed = []
                for seed in config.get("seeds",[config["seed"]]):
                    model_path = out / "models" / f"{name}-c{index}-s{seed}.json"
                    began = time.perf_counter()
                    model = Baseline(name, params, seed).fit(x,y,normal,features)
                    fit_seconds = time.perf_counter()-began
                    val = predict_cases(model,val_rows,val_cases,features)
                    threshold, detection = tune_threshold(val)
                    score = mean_ranking(val)["mrr"]
                    if any(r["error"] for r in val):
                        raise ValueError(f"Validation inference failed: {name}")
                    model.save(model_path)
                    per_seed.append(dict(seed=seed, path=str(model_path.relative_to(out)),
                                         validation_mrr=score, threshold=threshold, fit_seconds=fit_seconds))
                    trials.append(dict(algorithm=name,config_index=index,seed=seed,params=str(params),
                                       validation_mrr=score,threshold=threshold,fit_seconds=fit_seconds,status="SUCCESS"))
                options.append(dict(index=index,params=params,seeds=per_seed,
                                    validation_mrr=float(np.mean([p["validation_mrr"] for p in per_seed]))))
            winner = max(options,key=lambda v:v["validation_mrr"])
            metrics, all_predictions = [], []
            for selected in winner["seeds"]:
                model = Baseline.load(out/selected["path"])
                # Verify persisted model is the one used for final evaluation.
                predictions = predict_cases(model,test_rows,test_cases,features)
                for p in predictions:
                    p["seed"] = selected["seed"]
                write_jsonl(out/"predictions"/f"{name}-s{selected['seed']}.jsonl",predictions)
                measured = summarize(predictions,selected["threshold"],config)
                measured.update(seed=selected["seed"],threshold=selected["threshold"],fit_seconds=selected["fit_seconds"])
                metrics.append(measured)
                all_predictions.extend(predictions)
            keys = ["hit1","hit3","hit5","recall1","recall3","recall5","avg5","mrr","map","ndcg5","chance_avg5","lift_avg5","candidate_recall","evidence_coverage"]
            aggregate = {k:float(np.mean([m[k] for m in metrics])) for k in keys}
            aggregate["mrr_seed_std"] = float(np.std([m["mrr"] for m in metrics]))
            aggregate["latency_p95_ms"] = float(np.mean([m["latency_ms"]["95"] for m in metrics]))
            gates = config["gates"]
            checks = dict(hit3=aggregate["hit3"]>=gates["min_hit3"],mrr=aggregate["mrr"]>=gates["min_mrr"],
                          candidate_coverage=aggregate["candidate_recall"]==1.0,
                          latency=all(m["latency_ms"]["95"]<=gates["max_p95_ms"] for m in metrics),
                          evidence=aggregate["evidence_coverage"]>=gates["min_evidence_coverage"],
                          failures=all(m["failures"]==0 for m in metrics))
            summary[name] = dict(selected=winner,aggregate=aggregate,per_seed=metrics,
                                 gate=dict(checks=checks,decision="DEMO_ONLY" if manifest["synthetic"] else
                                 ("REVIEW_REQUIRED" if all(checks.values()) else "RESEARCH_ONLY"),
                                 production_allowed=False, reason="Offline gates do not authorize production promotion"))
            write_json(out/"model_cards"/f"{name}.json",dict(algorithm=name,task="candidate entity ranking",
                       dataset_hash=manifest["dataset_hash"],feature_names=features,selected=winner,
                       intended_use="offline/shadow support",limitations=["ranking is not causal proof",
                       "statistical/unsupervised models rank abnormal entities, which can be downstream symptoms",
                       "evidence is supporting telemetry, not a neural attribution or calibrated causal probability"],
                       lifecycle=summary[name]["gate"]))
        if external_predictions:
            from .adapters import evaluate_external
            summary["mda_external"] = evaluate_external(external_predictions,test_cases,config)
        write_json(out/"summary.json",summary)
        write_csv(out/"leaderboard.csv",[dict(algorithm=k,**v["aggregate"],decision=v["gate"]["decision"]) for k,v in summary.items()],
                  fields=["algorithm",*next(iter(summary.values()))["aggregate"],"decision"])
        write_csv(out/"trials.csv",trials)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        manifest.update(status="COMPLETED",finished_at=stamp(),resource=dict(
                         wall_seconds=time.perf_counter()-wall_start,cpu_seconds=time.process_time()-cpu_start,
                         python_traced_peak_bytes=peak,rss_peak_bytes=None,gpu_peak_bytes=None,
                         note="tracemalloc is Python allocator tracing; not total process/native/GPU memory"))
        manifest["artifact_hashes"] = {str(p.relative_to(out)).replace("\\","/"):file_hash(p)
                                        for p in out.rglob("*") if p.is_file() and p.name != "run_manifest.json"}
        write_json(out/"run_manifest.json",manifest)
        _html_report(out,manifest,summary)
        registry.record(db,run_id,"COMPLETED",manifest)
        return summary
    except Exception:
        tracemalloc.stop()
        manifest.update(status="FAILED",finished_at=stamp(),error=traceback.format_exc())
        write_json(out/"run_manifest.json",manifest)
        registry.record(db,run_id,"FAILED",manifest)
        raise
