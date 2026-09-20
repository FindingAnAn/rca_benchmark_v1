import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from rca_bench.data import build_case, deduplicate, temporal_split, prepare
from rca_bench.evaluation import ranking_metrics, average_precision, tune_threshold
from rca_bench.models import Baseline
from rca_bench.io import read_json, read_jsonl, write_jsonl, write_json, verify, seal
from rca_bench.synthetic import generate
from rca_bench.runner import benchmark
from rca_bench.connectors import vm_extract, es_extract
from rca_bench.adapters import evaluate_external, import_rcaeval


CONFIG = Path(__file__).resolve().parents[1]/"configs/demo.json"


class MetricsTests(unittest.TestCase):
    def test_single_root_and_random_floor(self):
        m = ranking_metrics(["b","a","c"],["a"],["a","b","c"])
        self.assertEqual(m["hit1"],0)
        self.assertEqual(m["mrr"],0.5)
        self.assertAlmostEqual(m["avg5"],0.8)
        self.assertAlmostEqual(m["chance_avg5"],0.8)
        self.assertEqual(m["lift_avg5"],0)

    def test_multiroot_not_hit_equals_recall(self):
        m = ranking_metrics(["a","c","b"],["a","b"],["a","b","c"])
        self.assertEqual(m["hit1"],1)
        self.assertEqual(m["recall1"],0.5)
        self.assertAlmostEqual(m["map"],(1+2/3)/2)
        self.assertEqual(ranking_metrics([], ["x"], ["a","b"])["candidate_recall"],0)

    def test_tied_ap_is_not_order_dependent(self):
        self.assertEqual(average_precision([1,0],[0.5,0.5]),0.5)
        self.assertEqual(average_precision([0,1],[0.5,0.5]),0.5)
        self.assertIsNone(average_precision([0,0],[.1,.2]))

    def test_empty_failed_prediction_is_zero(self):
        self.assertEqual(ranking_metrics([], ["a"], ["a","b"])["mrr"],0)

    def test_threshold_requires_controls(self):
        threshold,_ = tune_threshold([dict(is_incident=True,case_score=1)])
        self.assertIsNone(threshold)


class DataTests(unittest.TestCase):
    def test_exact_duplicate_and_conflict(self):
        rows=[dict(id=1,value=4),dict(id=1,value=4)]
        self.assertEqual(deduplicate(rows,["id"])[1],1)
        with self.assertRaises(ValueError):
            deduplicate(rows+[dict(id=1,value=5)],["id"])

    def test_future_and_late_data_not_features(self):
        cfg=read_json(CONFIG)
        cfg.update(modalities=["metric","log","change"],pre_seconds=600,post_seconds=120,min_metric_coverage=.5)
        case=dict(incident_id="c",t0=600,detected_at=600,cutoff=720,candidates=["a"],root_entities=["a"],log_coverage_complete=True)
        metrics=[dict(entity_id="a",series_id="a_cpu",metric="cpu",timestamp=t,available_at=t,value=1+(t%7)) for t in range(0,721,60)]
        args=(case,metrics,[],[],[],cfg)
        first=build_case(*args)
        extra=metrics+[dict(entity_id="a",series_id="a_cpu",metric="cpu",timestamp=800,available_at=800,value=1e9),
                       dict(entity_id="a",series_id="a_cpu",metric="cpu",timestamp=690,available_at=900,value=1e9)]
        changes=[dict(entity_id="a",event_time=710,available_at=800,change_id="future",operation="rollback")]
        after=build_case(case,extra,[],changes,[],cfg)
        self.assertEqual(first,after)

    def test_split_rejects_overlap_and_delayed_labels(self):
        cfg=read_json(CONFIG)
        cfg.update(pre_seconds=100,embargo_seconds=1)
        cases=[dict(incident_id=str(i),group_id=str(i),t0=i*1000,cutoff=i*1000+100,label_available_at=i*1000+200) for i in range(10)]
        splits=temporal_split(cases,cfg)
        self.assertEqual(splits["0"],"train")
        cases[5]["cutoff"]=10000
        with self.assertRaises(ValueError): temporal_split(cases,cfg)
        cases[5]["cutoff"]=5100
        cases[5]["label_available_at"]=99999
        with self.assertRaises(ValueError): temporal_split(cases,cfg)

    def test_checksum_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d)/"x.json",{"x":1})
            seal(d,{"stage":"raw"})
            verify(d)
            write_json(Path(d)/"x.json",{"x":2})
            with self.assertRaises(ValueError): verify(d)

    def test_label_change_does_not_change_features(self):
        cfg=read_json(CONFIG)
        cfg["n_cases"]=15
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            generate(d/"raw",cfg)
            prepare(d/"raw",d/"prepared",cfg)
            cases=read_jsonl(d/"prepared"/"cases.jsonl")
            # Labels are used only after feature computation, not as model inputs.
            from rca_bench.io import read_csv
            c=cases[1]
            from collections import defaultdict
            args=[r for r in read_csv(d/"raw"/"metrics.csv") if r["incident_id"]==c["incident_id"]]
            logs=[r for r in read_jsonl(d/"raw"/"logs.jsonl") if r["incident_id"]==c["incident_id"]]
            changes=[r for r in read_jsonl(d/"raw"/"changes.jsonl") if r["incident_id"]==c["incident_id"]]
            topology=[r for r in read_jsonl(d/"raw"/"topology.jsonl") if r["incident_id"]==c["incident_id"]]
            a=build_case(c,args,logs,changes,topology,cfg)
            c=copy.deepcopy(c); c["root_entities"]=["different-root"]
            b=build_case(c,args,logs,changes,topology,cfg)
            self.assertEqual([r["features"] for r in a],[r["features"] for r in b])


class ModelsTests(unittest.TestCase):
    def test_training_serialization_and_determinism(self):
        rng=np.random.default_rng(1)
        x=rng.normal(size=(120,4))
        y=(x[:,0]+x[:,1]>0).astype(float)
        normal=y==0
        for name,params in [("ml_logistic",{"epochs":100}), ("dl_mlp",{"hidden":[8,4],"epochs":100}),
                            ("dl_autoencoder",{"hidden":[8,2,8],"epochs":100}), ("ml_pca",{"components":2})]:
            model=Baseline(name,params,7).fit(x,y,normal,["a","b","c","d"])
            expected_center=(x[normal] if name in ["ml_pca","dl_autoencoder"] else x).mean(axis=0)
            np.testing.assert_allclose(model.state["center"],expected_center)
            if model.loss_history:
                self.assertLess(model.loss_history[-1],model.loss_history[0])
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/"model.json"
                model.save(path)
                np.testing.assert_allclose(model.score(x),Baseline.load(path).score(x))
            again=Baseline(name,params,7).fit(x,y,normal,["a","b","c","d"])
            np.testing.assert_allclose(model.score(x),again.score(x))


class ConnectorTests(unittest.TestCase):
    def test_vm_chunks_do_not_drop_or_duplicate_boundary(self):
        from urllib.parse import urlparse,parse_qs
        seen=[]
        def http(method,url,payload=None):
            q=parse_qs(urlparse(url).query)
            a,b,s=(int(float(q[k][0])) for k in ["start","end","step"])
            seen.append((a,b))
            return {"status":"success","data":{"resultType":"matrix","result":[{"metric":{"entity_id":"a"},
                    "values":[[t,"1"] for t in range(a,b+1,s)]}]}}
        cfg=dict(query_range_url="https://vm/api/v1/query_range",entity_label="entity_id",chunk_seconds=120,
                 queries=[dict(name="cpu",promql="cpu",kind="gauge")])
        with tempfile.TemporaryDirectory() as d:
            rows=vm_extract(cfg,{"incident_id":"c"},0,240,60,http,Path(d))
        self.assertEqual([r["timestamp"] for r in rows],[0,60,120,180,240])
        self.assertEqual(seen,[(0,60),(120,180),(240,240)])

    def test_es_pit_rotation_pagination_and_cleanup(self):
        calls=[]
        def http(method,url,payload=None):
            calls.append((method,url,copy.deepcopy(payload)))
            if "/_pit?" in url: return {"id":"p1"}
            if method=="DELETE": return {"succeeded":True}
            if "search_after" in payload:
                self.assertEqual(payload["pit"]["id"],"p2")
                self.assertEqual(payload["search_after"],[11])
                return {"pit_id":"p3","hits":{"hits":[]}}
            return {"pit_id":"p2","hits":{"hits":[{"_index":"logs","_id":"x","sort":[11],
                     "_source":{"@timestamp":"2026-01-01T00:00:00Z","entity":"a","level":"ERROR","template":"T1"}}]}}
        cfg=dict(base_url="https://es",index="logs",fields={"timestamp":"@timestamp","entity_id":"entity","level":"level","template_id":"template"})
        with tempfile.TemporaryDirectory() as d:
            rows=es_extract(cfg,{"incident_id":"c"},0,2000000000,http,Path(d))
        self.assertEqual(rows[0]["event_id"],"logs:x")
        self.assertEqual(calls[-1][0],"DELETE")
        self.assertEqual(calls[-1][2],{"id":"p3"})

    def test_es_partial_response_rejected_and_pit_closed(self):
        calls=[]
        def http(method,url,payload=None):
            calls.append(method)
            if "/_pit?" in url: return {"id":"p1"}
            if method=="DELETE": return {}
            return {"timed_out":True}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                es_extract(dict(base_url="https://es",index="logs",fields={"timestamp":"@timestamp"}),
                           {"incident_id":"c"},0,1,http,Path(d))
        self.assertEqual(calls[-1],"DELETE")


class EndToEndTests(unittest.TestCase):
    def test_external_baseline_in_full_report(self):
        cfg=read_json(CONFIG)
        cfg.update(n_cases=15,seeds=[42],bootstrap_samples=10)
        cfg["algorithms"]={"stat_mad":[{"context_weight":0}]}
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            generate(d/"raw",cfg)
            prepare(d/"raw",d/"prepared",cfg)
            cases=[c for c in read_jsonl(d/"prepared"/"cases.jsonl") if c["split"]=="test"]
            write_jsonl(d/"external.jsonl",[dict(incident_id=c["incident_id"],observation_cutoff=c["cutoff"],ranks=c["candidates"],evidence=[]) for c in cases])
            result=benchmark(d/"prepared",d/"run",cfg,d/"external.jsonl")
            self.assertEqual(result["mda_external"]["coverage"],1)
            self.assertIn("mda_external",(d/"run/report.html").read_text(encoding="utf-8"))

    def test_drift_identical_data_is_zero(self):
        from rca_bench.monitoring import drift
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"features.jsonl"
            write_jsonl(path,[dict(features={"x":float(i)}) for i in range(20)])
            report=drift(path,path)
            self.assertEqual(report["features"]["x"]["psi"],0)
            self.assertEqual(report["action"],"NO_DRIFT_FLAG")

    def test_rcaeval_import_keeps_explicit_entity_mapping(self):
        from rca_bench.io import write_csv
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            write_csv(d/"metric.csv",[{"time":100,"service_with_underscore_cpu":2},{"time":160,"service_with_underscore_cpu":3}])
            case=dict(incident_id="rcaeval-case",group_id="campaign",t0=130,detected_at=130,cutoff=160,
                      candidates=["service_with_underscore"],root_entities=["service_with_underscore"],is_incident=True,
                      label_tier="gold",label_source="injection",label_available_at=170,
                      availability_mode="retrospective",log_coverage_complete=False)
            write_json(d/"catalog.json",dict(dataset_version="public-test",upstream_ref="pinned",
                cases=[dict(metrics_file="metric.csv",case=case,column_to_entity={"service_with_underscore_cpu":"service_with_underscore"})]))
            import_rcaeval(d/"catalog.json",d/"raw")
            verify(d/"raw")
            from rca_bench.io import read_csv
            self.assertEqual(read_csv(d/"raw"/"metrics.csv")[0]["entity_id"],"service_with_underscore")

    def test_pipeline_all_tracks_and_external_failures(self):
        cfg=read_json(CONFIG)
        cfg.update(n_cases=30,seeds=[42],bootstrap_samples=20)
        cfg["algorithms"]={k:[{**v[0],"epochs":25}] for k,v in cfg["algorithms"].items()}
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            generate(d/"raw",cfg)
            prepare(d/"raw",d/"prepared",cfg)
            result=benchmark(d/"prepared",d/"run",cfg)
            self.assertEqual(len(result),6)
            self.assertTrue((d/"run"/"report.html").exists())
            self.assertEqual(read_json(d/"run"/"run_manifest.json")["status"],"COMPLETED")
            self.assertTrue(all(x["gate"]["decision"]=="DEMO_ONLY" for x in result.values()))
            cases=[c for c in read_jsonl(d/"prepared"/"cases.jsonl") if c["split"]=="test"]
            write_jsonl(d/"external.jsonl",[])
            external=evaluate_external(d/"external.jsonl",cases,cfg)
            self.assertEqual(external["aggregate"]["mrr"],0)
            self.assertEqual(external["missing_cases"],len(cases))

    def test_failed_training_persists_status(self):
        cfg=read_json(CONFIG)
        cfg.update(n_cases=15,seeds=[42])
        cfg["algorithms"]={"unknown":[{}]}
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            generate(d/"raw",cfg)
            prepare(d/"raw",d/"prepared",cfg)
            with self.assertRaises(ValueError): benchmark(d/"prepared",d/"failed",cfg)
            self.assertEqual(read_json(d/"failed"/"run_manifest.json")["status"],"FAILED")


if __name__ == "__main__":
    unittest.main()
