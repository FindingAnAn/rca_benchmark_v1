"""Small, auditable storage primitives; JSON model files never execute code."""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def utc(value):
    if isinstance(value, (float, int)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        return dt.timestamp()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(canonical(row) + "\n")


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    rows = list(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def seal(folder, metadata):
    folder = Path(folder)
    hashes = {str(p.relative_to(folder)).replace("\\", "/"): file_hash(p)
              for p in sorted(folder.rglob("*")) if p.is_file() and p != folder / "manifest.json"}
    manifest = {**metadata, "files": hashes, "content_hash": digest(hashes), "created_at": stamp()}
    write_json(folder / "manifest.json", manifest)
    return manifest


def verify(folder):
    folder = Path(folder)
    m = read_json(folder / "manifest.json")
    current = {str(p.relative_to(folder)).replace("\\", "/"): file_hash(p)
               for p in sorted(folder.rglob("*")) if p.is_file() and p != folder / "manifest.json"}
    if current != m["files"] or digest(current) != m["content_hash"]:
        raise ValueError("Snapshot integrity failure: changed/missing/extra files")
    return m


def new_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path
