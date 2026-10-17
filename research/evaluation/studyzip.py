"""studyzip.py - read exported study zips safely and (for DRY RUNS ONLY) build a labelled
dry-run study folder from the P00/P01 test zips (2026-10-15).

Used by rescore_study.py (--zip), make_blind_packs.py and analysis_study.py. Only entries named
study_log.jsonl or study/photos/<participant>_<condition>/<64 hex>.jpg are read, and every file
written is named by THIS code (<sha256>.jpg), so nothing inside a zip can choose a path.
Changes no framework code.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ENTRY = re.compile(r"^study/photos/[A-Za-z0-9_-]+/([0-9a-f]{64})\.jpg$")
EVENT_HASH_FIELDS = ("photo_hashes",)          # lists
RETAKE_PROMPTS = ("help_card_shown", "setup_check_shown", "restart")


def read_zip(path: Path) -> dict:
    """{'log': [events], 'photos': {sha256: bytes}, 'bad_crc': bool, 'name_mismatch': [..]}."""
    z = zipfile.ZipFile(path)
    bad = z.testzip() is not None
    log = [json.loads(l) for l in z.read("study_log.jsonl").decode("utf-8").splitlines() if l.strip()]
    photos, mismatch = {}, []
    for n in z.namelist():
        m = ENTRY.match(n)
        if not m:
            continue
        data = z.read(n)
        if hashlib.sha256(data).hexdigest() != m.group(1):
            mismatch.append(n)
        photos[m.group(1)] = data
    return {"log": log, "photos": photos, "bad_crc": bad, "name_mismatch": mismatch}


def logged_hashes(log: list) -> dict:
    """event kind -> set of photo hashes the log mentions."""
    out = defaultdict(set)
    for e in log:
        for h in e.get("photo_hashes", []) or []:
            out["capture_end.photo_hashes"].add(h)
        for p in e.get("photos", []) or []:
            out["batch_result.photos"].add(p["hash"])
        for h in (e.get("own_picks") or {}).values():
            out["own_picks"].add(h)
        if e.get("event") == "photo_captured" and e.get("hash"):
            out["photo_captured.hash"].add(e["hash"])
    return out


def schema_check(log: list) -> tuple:
    """(n_accepted, [(index, event, error)]) using the server's own validator."""
    from backend.api import study_api
    errs, ok = [], 0
    for i, e in enumerate(log):
        try:
            study_api.validate(e)
            ok += 1
        except ValueError as ex:
            errs.append((i, e.get("event"), str(ex)))
    return ok, errs


def merge_logs(logs: list) -> list:
    """Concatenate logs, drop exact duplicate entries (a phone log is cumulative)."""
    seen, out = set(), []
    for log in logs:
        for e in log:
            k = json.dumps(e, sort_keys=True)
            if k not in seen:
                seen.add(k)
                out.append(e)
    out.sort(key=lambda e: e.get("timestamp", ""))
    return out


def run_id(e: dict) -> str:
    return (e.get("times") or {}).get("session_start") or ""


def runs(log: list) -> dict:
    """(participant, product, session_start) -> events of that run, in time order."""
    by = defaultdict(list)
    for e in log:
        by[(e["participant"], e["product"], run_id(e))].append(e)
    return dict(by)


def first_prompt_time(events: list) -> str | None:
    t = [e["timestamp"] for e in events if e["event"] in RETAKE_PROMPTS]
    return min(t) if t else None


def build_dryrun(merged: list, assign: dict) -> list:
    """A DRYRUN study log from real test-session events.

    assign: (participant, product, nth run of that pair, 0-based) -> (condition, session no.).
    Runs not listed are dropped. The condition is RELABELLED (the real runs were all GUIDED),
    so the output exists only to exercise the analysis chain. Help cards are removed from a
    run relabelled UNGUIDED (that condition never shows one)."""
    out = []
    count = defaultdict(int)
    by = runs(merged)
    for key in sorted(by, key=lambda k: (k[0], k[1], k[2])):
        p, prod, _ = key
        n = count[(p, prod)]
        count[(p, prod)] += 1
        if (p, prod, n) not in assign:
            continue
        cond, sess = assign[(p, prod, n)]
        for e in by[key]:
            if cond == "UNGUIDED" and e["event"] in ("help_card_shown", "setup_check_shown", "restart"):
                continue
            e2 = dict(e)
            e2["condition"] = cond
            e2["session"] = sess
            if cond == "UNGUIDED":
                e2.pop("guidance_ms", None)
            out.append(e2)
    return out


# --------------------------------------------------------------------------- dry run CLI
DRYRUN_ASSIGN = {            # (participant, product, nth run) -> (condition, session)
    ("P00", "DQREF", 0): ("GUIDED", 1),      # 2026-10-15 04:37  (real condition: GUIDED)
    ("P00", "DQREF", 1): ("UNGUIDED", 2),    # 2026-10-15 06:18  RELABELLED, test data only
    ("P01", "DQREF", 0): ("GUIDED", 1),      # P01 has ONE run: a deliberate partial participant
}


def main_dryrun(zips: list, out: Path) -> dict:
    """Build out/study_dir (study_log.jsonl + photos/<sha>.jpg) and out/DRYRUN.txt."""
    study = out / "study_dir"
    (study / "photos").mkdir(parents=True, exist_ok=True)
    logs, photos = [], {}
    for z in zips:
        r = read_zip(Path(z))
        logs.append(r["log"])
        photos.update(r["photos"])
    merged = merge_logs(logs)
    log = build_dryrun(merged, DRYRUN_ASSIGN)
    (study / "study_log.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in log), encoding="utf-8")
    need = logged_hashes(log)
    hs = set().union(*need.values()) if need else set()
    n = 0
    for h in hs:
        if h in photos:
            (study / "photos" / f"{h}.jpg").write_bytes(photos[h])
            n += 1
    (out / "DRYRUN.txt").write_text(
        "DRYRUN - test data (participant P00/P01 are device-qualification sessions).\n"
        "Conditions were RELABELLED to exercise the analysis chain. Never copy into a real\n"
        "analysis folder and never report any number from here.\n", encoding="utf-8")
    return {"events": len(log), "photos": n, "participants": sorted({e["participant"] for e in log})}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build the DRYRUN study folder from test zips.")
    ap.add_argument("--zip", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(main_dryrun(a.zip, a.out))
