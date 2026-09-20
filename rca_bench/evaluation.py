"""Incident ranking metrics; control-window detection is reported separately."""
import math
import numpy as np


def ranking_metrics(ranking, roots, candidates):
    ranking = list(dict.fromkeys(ranking))
    roots, universe = set(roots), set(candidates)
    if not roots:
        return None
    if not set(ranking) <= universe:
        raise ValueError("Ranking has candidates outside the fixed universe")
    hits = [int(c in roots) for c in ranking]
    first = next((i+1 for i,v in enumerate(hits) if v), None)
    n, m = len(universe), len(roots & universe)
    ac = [sum(hits[:k])/len(roots) for k in range(1,6)]
    dcg = sum(v/math.log2(i+2) for i,v in enumerate(hits[:5]))
    idcg = sum(1/math.log2(i+2) for i in range(min(5,len(roots))))
    average_precision = sum(sum(hits[:i+1])/(i+1) for i,v in enumerate(hits) if v)/len(roots)
    chance_ac = [min(k,n)/n*m/len(roots) if n else 0 for k in range(1,6)]
    return {"hit1": float(any(hits[:1])), "hit3": float(any(hits[:3])), "hit5": float(any(hits[:5])),
            "recall1": ac[0], "recall3": ac[2], "recall5": ac[4], "avg5": float(np.mean(ac)),
            "mrr": 1/first if first else 0.0, "map": average_precision, "ndcg5": dcg/idcg,
            "chance_avg5": float(np.mean(chance_ac)), "lift_avg5": float(np.mean(ac)-np.mean(chance_ac)),
            "candidate_recall": m/len(roots)}


def mean_ranking(results):
    values = [r["ranking_metrics"] for r in results if r["ranking_metrics"] is not None]
    return {k:float(np.mean([v[k] for v in values])) for k in values[0]} if values else {}


def average_precision(y, scores):
    """Non-interpolated PR area (AP), grouping tied scores together."""
    y, scores = np.asarray(y, dtype=int), np.asarray(scores)
    if sum(y) == 0:
        return None
    order = np.argsort(-scores, kind="stable")
    ys, ss = y[order], scores[order]
    total, tp, ap = 0, 0, 0.0
    for score in np.unique(ss)[::-1]:
        group = ys[ss == score]
        old_tp = tp
        total += len(group)
        tp += int(sum(group))
        ap += (tp-old_tp)/sum(y)*tp/total
    return float(ap)


def detection_metrics(y, scores, threshold):
    y, p = np.asarray(y, dtype=bool), np.asarray(scores) >= threshold
    tp, fp, fn = int(sum(y&p)), int(sum(~y&p)), int(sum(y&~p))
    precision = tp/(tp+fp) if tp+fp else 0.0
    recall = tp/(tp+fn) if tp+fn else 0.0
    return dict(precision=precision, recall=recall, f1=2*precision*recall/(precision+recall) if precision+recall else 0.0,
                ap=average_precision(y,scores), tp=tp, fp=fp, fn=fn, n_windows=len(y),
                scope="sampled incident/control windows; not continuous event detection",
                false_alarms_per_hour=None, detection_delay_seconds=None)


def tune_threshold(results):
    y = [r["is_incident"] for r in results]
    scores = np.array([r["case_score"] for r in results])
    if len(set(y)) < 2:
        return None, {"status": "unavailable: validation needs normal controls and incidents"}
    thresholds = [float(np.nextafter(max(scores), np.inf)), *map(float, sorted(set(scores), reverse=True))]
    best = max(thresholds, key=lambda t: (detection_metrics(y,scores,t)["f1"], t))
    return best, detection_metrics(y,scores,best)


def bootstrap_mrr(results, seed=42, samples=300):
    # Resample groups, not candidate rows; handles multiple windows of the same incident.
    groups = {}
    for r in results:
        if r["ranking_metrics"] is not None:
            groups.setdefault(r["group_id"], []).append(r["ranking_metrics"]["mrr"])
    if len(groups) < 2:
        return None
    values = list(groups.values())
    rng = np.random.default_rng(seed)
    means = [np.mean([v for i in rng.integers(0,len(values),len(values)) for v in values[i]]) for _ in range(samples)]
    return {"lower": float(np.quantile(means, .025)), "upper": float(np.quantile(means, .975)),
            "method": "percentile group bootstrap", "n_groups": len(groups)}
