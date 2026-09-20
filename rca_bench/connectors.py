"""Bounded, read-only telemetry extraction. Transport is injectable for tests."""
import json
import math
import os
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from .io import (canonical, digest, new_directory, read_jsonl, seal, utc, write_csv,
                 write_json, write_jsonl)


class HTTP:
    def __init__(self, authorization_env=None, timeout=30, retries=2):
        self.timeout, self.retries = timeout, retries
        token = os.environ.get(authorization_env) if authorization_env else None
        if authorization_env and not token:
            raise ValueError(f"Set credential environment variable {authorization_env}")
        self.headers = {"Content-Type":"application/json"}
        if token:
            self.headers["Authorization"] = token

    def __call__(self, method, url, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url,data=data,headers=self.headers,method=method)
        for attempt in range(self.retries+1):
            try:
                with urllib.request.urlopen(request,timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as e:
                if e.code not in [429,500,502,503,504] or attempt == self.retries:
                    raise RuntimeError(f"Telemetry HTTP status {e.code}") from None
            except urllib.error.URLError:
                if attempt == self.retries:
                    raise RuntimeError("Telemetry transport failure (URL/credentials omitted)") from None
            time.sleep(min(2**attempt,4))


def vm_extract(settings, case, start, end, step, transport, archive):
    if step <= 0 or settings.get("chunk_seconds",3600) < step:
        raise ValueError("Invalid step/chunk size")
    endpoint = settings["query_range_url"]
    output = []
    for query_index, query in enumerate(settings["queries"]):
        if query["kind"] not in ["gauge","rate"]:
            raise ValueError("Use rate()/increase() explicitly for counter metrics")
        cursor, chunk_id = start, 0
        while cursor <= end:
            stop = min(end,cursor + (settings.get("chunk_seconds",3600)//step-1)*step)
            args = urllib.parse.urlencode(dict(query=query["promql"],start=cursor,end=stop,step=step))
            result = transport("GET",endpoint+"?"+args)
            if result.get("status") != "success" or result.get("data",{}).get("resultType") != "matrix":
                raise ValueError("VictoriaMetrics did not return a successful range matrix")
            write_json(archive/f"vm-{case['incident_id']}-{query_index}-{chunk_id}.json",result)
            for series in result["data"]["result"]:
                labels = series["metric"]
                entity = labels.get(settings["entity_label"])
                if not entity:
                    raise ValueError("VM series missing canonical entity label; configure a mapping upstream")
                for timestamp,value in series["values"]:
                    if not math.isfinite(float(value)):
                        raise ValueError("Nonfinite VM sample: quarantine/fix raw export before benchmark")
                    output.append(dict(incident_id=case["incident_id"],entity_id=entity,metric=query["name"],
                               series_id=digest({"labels":labels,"query_name":query["name"]}),
                               timestamp=utc(timestamp),available_at=utc(timestamp),value=float(value),kind=query["kind"]))
            cursor, chunk_id = stop+step, chunk_id+1
    return output


def field(source, path):
    if path in source:
        return source[path]
    for part in path.split("."):
        source = source[part]
    return source


def es_extract(settings, case, start, end, transport, archive):
    base = settings["base_url"].rstrip("/")
    index = urllib.parse.quote(settings["index"],safe="*,-_")
    pit = transport("POST",base+f"/{index}/_pit?keep_alive=2m")["id"]
    after, rows, page = None, [], 0
    time_field = settings["fields"]["timestamp"]
    try:
        while True:
            query = {"size":settings.get("page_size",1000),"pit":{"id":pit,"keep_alive":"2m"},
                     "sort":[{"_shard_doc":"asc"}],"track_total_hits":False,
                     "query":{"bool":{"filter":[{"range":{time_field:{"gte":int(start*1000),"lte":int(end*1000),"format":"epoch_millis"}}},
                                                     settings.get("filter",{"match_all":{}})]}}}
            if after is not None:
                query["search_after"] = after
            response = transport("POST",base+"/_search",query)
            if response.get("timed_out") or response.get("_shards",{}).get("failed",0):
                raise ValueError("ES partial/timed-out response; refusing incomplete snapshot")
            pit = response.get("pit_id",pit)
            write_json(archive/f"es-{case['incident_id']}-{page}.json",response)
            hits = response["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                src = hit["_source"]
                normalized = {target:field(src,origin) for target,origin in settings["fields"].items()}
                normalized.update(incident_id=case["incident_id"],event_id=hit["_index"]+":"+hit["_id"])
                normalized["timestamp"] = utc(normalized["timestamp"])
                normalized["available_at"] = utc(normalized.get("available_at",normalized["timestamp"]))
                rows.append(normalized)
            token = hits[-1]["sort"]
            if token == after:
                raise ValueError("ES search_after made no progress")
            after, page = token, page+1
            if page >= settings.get("max_pages",10000):
                raise ValueError("ES max_pages reached; reduce export window")
    finally:
        transport("DELETE",base+"/_pit",{"id":pit})
    return rows


def ingest(settings, context, output):
    from .data import normalize_cases
    context = Path(context)
    out = new_directory(output)
    archive = out/"responses"
    archive.mkdir()
    cases = normalize_cases(read_jsonl(context/"incidents.jsonl"))
    if not cases:
        raise ValueError("Provide annotated incident/control catalog first")
    metrics, logs = [], []
    for case in cases:
        if case["availability_mode"] != "retrospective":
            raise ValueError("Historical VM query_range cannot prove arrival time: declare retrospective mode")
        # Only successfully exported, complete windows receive this assertion below.
        start, end = utc(case["detected_at"])-settings["pre_seconds"], utc(case["cutoff"])
        for name in ["victoriametrics","elasticsearch"]:
            cfg = settings.get(name)
            if not cfg:
                continue
            http = HTTP(cfg.get("authorization_env"),cfg.get("timeout_seconds",30))
            if name == "victoriametrics":
                metrics.extend(vm_extract(cfg,case,start,end,settings["step_seconds"],http,archive))
            else:
                logs.extend(es_extract(cfg,case,start,end,http,archive))
        case["log_coverage_complete"] = bool(settings.get("elasticsearch"))
    write_csv(out/"metrics.csv",metrics,fields=["incident_id","entity_id","metric","series_id","timestamp","available_at","value","kind"])
    write_jsonl(out/"logs.jsonl",logs)
    write_jsonl(out/"incidents.jsonl",cases)
    for name in ["changes.jsonl","topology.jsonl"]:
        if (context/name).exists():
            shutil.copyfile(context/name,out/name)
    write_json(out/"source.json",dict(kind="internal",queries=settings,availability="retrospective",
                                    note="VM sample timestamps are NOT ingestion timestamps"))
    return seal(out,dict(stage="raw",synthetic=False,dataset_version=settings["dataset_version"]))
