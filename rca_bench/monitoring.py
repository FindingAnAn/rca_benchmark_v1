from .io import read_jsonl, file_hash
import numpy as np


def drift(reference, current):
    old, new = read_jsonl(reference), read_jsonl(current)
    if not old or not new:
        raise ValueError("Drift needs nonempty feature files")
    features = sorted(old[0]["features"])
    if any(sorted(r["features"]) != features for r in old+new):
        raise ValueError("Feature schema mismatch")
    results = {}
    for f in features:
        a,b = (np.array([r["features"][f] for r in rows]) for rows in [old,new])
        cuts = np.unique(np.quantile(a,np.linspace(0,1,11)))
        edges = np.concatenate(([-np.inf],cuts,[np.inf]))
        pa = np.histogram(a,edges)[0].astype(float)+0.5
        pb = np.histogram(b,edges)[0].astype(float)+0.5
        pa, pb = pa/sum(pa), pb/sum(pb)
        results[f] = dict(psi=float(sum((pb-pa)*np.log(pb/pa))),reference_mean=float(a.mean()),current_mean=float(b.mean()))
    return dict(reference_hash=file_hash(reference),current_hash=file_hash(current),features=results,
                action="REVIEW_DATA" if any(v["psi"]>.2 for v in results.values()) else "NO_DRIFT_FLAG",
                threshold_note="PSI 0.2 is illustrative; validate per population and window. No automatic retraining/promotion.")
