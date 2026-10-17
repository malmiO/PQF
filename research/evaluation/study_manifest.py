"""study_manifest.py - STEP 1 of the study rescore: tolerant parse of the raw participant zips,
exclusions, arm, attempts, manifest. READ-ONLY on the zips (never edits them); touches no
framework code. Writes research/results/study/{participant_manifest.csv,manifest_report.json,
raw_sha256.txt,excluded/*}.

    .venv/Scripts/python.exe research/evaluation/study_manifest.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "research" / "results" / "study"
RAW, EXC = ROOT / "raw", ROOT / "excluded"
ANALYSED = ["P01", "P02", "P03", "P04", "P05", "P06", "P09", "P11", "P13", "P14"]
STATION_DEVICE = "samsung sm-j610f"
ENTRY = re.compile(r"^study/photos/[A-Za-z0-9_-]+/([0-9a-f]{64})\.jpg$")
# whole-zip exclusions: name fragment -> reason
EXCLUDED_ZIPS = {
    "pqf_study_P05_20261015_200152": "SUPERSEDED_BY_20261016_151524",
    "pqf_study_P10_": "P10_EXCLUDED",
    "pqf_study_P12_": "P12_EXCLUDED",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parse_zip(p: Path):
    z = zipfile.ZipFile(p)
    events, bad = [], []
    for i, line in enumerate(z.read("study_log.jsonl").decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            if not isinstance(e, dict):
                raise ValueError("not an object")
            events.append((i, line, e))
        except ValueError as ex:
            bad.append((i, str(ex)[:60], line[:80]))
    photos = {m.group(1) for n in z.namelist() if (m := ENTRY.match(n))}
    return events, bad, photos


def zip_excluded_reason(name: str):
    for frag, why in EXCLUDED_ZIPS.items():
        if frag in name:
            return why
    return None


def hashes_of(ev):
    s = set()
    for e in ev:
        s.update(e.get("photo_hashes") or [])
        s.update((e.get("own_picks") or {}).values())
        s.update(p["hash"] for p in e.get("photos") or [] if p.get("hash"))
        if e.get("hash"):
            s.add(e["hash"])
    return s


def main():
    EXC.mkdir(parents=True, exist_ok=True)
    zips = sorted(RAW.glob("*.zip")) + sorted(EXC.glob("*.zip"))
    shas = {z.name: sha256_file(z) for z in zips}
    (ROOT / "raw_sha256.txt").write_text(
        "".join(f"{h}  {n}\n" for n, h in sorted(shas.items())), encoding="utf-8")

    report = {"malformed_lines": [], "excluded_zips": [], "excluded_rows": [], "zips": {}}
    runs = defaultdict(list)           # (code, session, run_id) -> [(zip, event)]
    zip_hashes = {}
    for zp in zips:
        events, bad, photos = parse_zip(zp)
        zip_hashes[zp.name] = photos
        for i, why, snip in bad:
            report["malformed_lines"].append(
                {"zip": zp.name, "line": i, "error": why, "start": snip})
        why = zip_excluded_reason(zp.name)
        report["zips"][zp.name] = {"sha256": shas[zp.name], "lines": len(events) + len(bad),
                                   "malformed": len(bad), "photos": len(photos)}
        if why:
            report["excluded_zips"].append({"zip": zp.name, "reason": why})
            continue
        for i, line, e in events:
            code = e.get("participant")
            if code not in ANALYSED:
                reason = {"P10": "P10_EXCLUDED", "P12": "P12_EXCLUDED",
                          "P00": "P00_TEST"}.get(code, "NOT_IN_ANALYSED_LIST")
                report["excluded_rows"].append(
                    {"zip": zp.name, "line": i, "participant": code, "event": e.get("event"),
                     "reason": reason, "raw": line})
                continue
            rid = (e.get("times") or {}).get("session_start") or ""
            runs[(code, e.get("session"), rid)].append((zp.name, e))

    # move whole-zip exclusions (the copies in raw/; the originals stay where you put them)
    for x in report["excluded_zips"]:
        src = RAW / x["zip"]
        if src.exists():
            shutil.move(str(src), str(EXC / x["zip"]))
    # excluded rows, grouped by reason
    byr = defaultdict(list)
    for r in report["excluded_rows"]:
        byr[(r["reason"], r["zip"])].append(r)
    for (reason, zname), rows in byr.items():
        out = EXC / f"rows_{reason}_{Path(zname).stem}.jsonl"
        out.write_text("".join(
            json.dumps({"zip": r["zip"], "line": r["line"], "reason": reason, "raw": r["raw"]})
            + "\n" for r in rows), encoding="utf-8")
    (EXC / "excluded_index.json").write_text(json.dumps(
        {"zips": report["excluded_zips"],
         "row_counts": {f"{k[0]}|{k[1]}": len(v) for k, v in byr.items()}}, indent=1))

    # ---- attempts -------------------------------------------------------------------
    # An attempt ends at an own_picks event; it is COMPLETE when a capture_end precedes that
    # own_picks inside the segment (capture_end is re-emitted on every retake, so several
    # capture_ends before one own_picks are ONE attempt). batch_result events after an
    # own_picks belong to that attempt. Segments with no own_picks are incomplete attempts.
    bysess = defaultdict(list)
    for (code, sess, rid), evs in runs.items():
        bysess[(code, sess)].extend(evs)
    attempts = defaultdict(list)       # (code, session) -> [attempt dict] in time order
    for (code, sess), evs in bysess.items():
        seen, ev = set(), []
        for zn, e in sorted(evs, key=lambda t: t[1].get("timestamp", "")):
            k = json.dumps(e, sort_keys=True)
            if k not in seen:
                seen.add(k)
                ev.append((zn, e))
        segs, cur = [], []
        for zn, e in ev:
            if e["event"] == "session_start" and cur and                     not any(x["event"] == "own_picks" for _, x in cur) and                     not any(x["event"] != "session_start" for _, x in cur):
                cur = []                     # an empty earlier session_start: drop it into next
            if e["event"] == "session_start" and cur:
                # an app restart: the events so far are a finished (complete or incomplete)
                # attempt; the new session_start opens the next one
                segs.append(cur)
                cur = []
            if cur and any(x["event"] == "own_picks" for _, x in cur) and e["event"] in (
                    "photo_captured", "help_card_shown", "setup_check_shown", "session_start",
                    "capture_end"):
                segs.append(cur)
                cur = []
            cur.append((zn, e))
        if cur:
            segs.append(cur)
        ss_ev = next((e for _, e in ev if e["event"] == "session_start"), None)
        for seg in segs:
            E = [e for _, e in seg]
            ce = [e for e in E if e["event"] == "capture_end"]
            op = [e for e in E if e["event"] == "own_picks"]
            br = [e for e in E if e["event"] == "batch_result"]
            cap = {e["hash"] for e in E if e["event"] == "photo_captured" and e.get("hash")}
            complete = bool(ce and op)
            prev = attempts[(code, sess)][-1] if attempts[(code, sess)] else None
            if not ce and not op and prev and prev["complete"]:
                # photo_captured / help cards / re-run batch_result AFTER the results screen,
                # with no new capture_end+own_picks: not an attempt; kept as a flag.
                prev["post_result_photos"] += len(cap)
                continue
            final = set(ce[-1].get("photo_hashes") or []) if ce else set()
            picks = set((op[0].get("own_picks") or {}).values()) if op else set()
            allh = hashes_of(E)
            zn = sorted({z for z, _ in seg})
            miss = sorted(h[:10] for h in allh
                          if not any(h in zip_hashes[z] for z in zn)
                          and not any(h in zip_hashes[z] for z in zip_hashes))
            last_br = br[-1] if br else None
            attempts[(code, sess)].append({
                "events": E, "start": E[0].get("timestamp"), "end": E[-1].get("timestamp"),
                "zips": zn,
                "session_start": next((e for e in E if e["event"] == "session_start"), ss_ev),
                "complete": complete, "n_capture_end": len(ce), "photos_captured": len(cap),
                "photos_final": len(final), "photos_picks": len(picks | final),
                "scoring_hashes": sorted(final | picks), "hashes_present": not miss,
                "missing_hashes": miss,
                "gate": (f"{sum(1 for p in last_br['photos'] if p.get('passed'))}/"
                         f"{len(last_br['photos'])} passed" if last_br else "no_batch_result"),
                "flags": [], "has_events_before_start": False, "post_result_photos": 0})
    for k in attempts:
        attempts[k].sort(key=lambda a: a["start"] or "")

    # ---- manifest -------------------------------------------------------------------
    rows, keys = [], defaultdict(dict)
    codes = sorted({c for c, _ in attempts})
    for code in codes:
        sess_info = {}
        for s in sorted(k[1] for k in attempts if k[0] == code):
            at = attempts[(code, s)]
            comp = [a for a in at if a["complete"]]
            ss = next((a["session_start"] for a in at if a["session_start"]), {}) or {}
            sess_info[s] = {"attempts": at, "first": comp[0] if comp else None,
                            "last": comp[-1] if comp else None, "ss": ss}
        devs = {(i["ss"].get("device_model") or "") for i in sess_info.values()}
        for s, i in sess_info.items():
            dm = i["ss"].get("device_model") or ""
            arm = "STATION" if dm.lower().startswith(STATION_DEVICE) else "REMOTE"
            i["arm"], i["device"] = arm, dm
        for s, i in sess_info.items():
            f, l = i["first"], i["last"]
            ss = i["ss"]
            fl = []
            if f is None:
                fl.append("NO_COMPLETE_ATTEMPT")
            else:
                if f["n_capture_end"] > 1:
                    fl.append(f"retakes_capture_end_x{f['n_capture_end']}")
                if not f["hashes_present"]:
                    fl.append("HASHES_MISSING:" + ";".join(f["missing_hashes"]))
                if f["has_events_before_start"]:
                    fl.append("NO_SESSION_START_EVENT")
            if f and f["post_result_photos"]:
                fl.append(f"post_result_photos_not_scored={f['post_result_photos']}")
            reps = [a for a in i["attempts"] if a["complete"]][1:]
            incomplete = [a for a in i["attempts"] if not a["complete"]]
            if reps:
                fl.append(f"repeat_not_analysed={len(reps)}")
            if incomplete:
                fl.append(f"incomplete_attempts={len(incomplete)}")
            rows.append({
                "zip": ";".join(sorted({z for a in i["attempts"] for z in a["zips"]})),
                "zip_sha256": ";".join(sorted({shas[z][:16] for a in i["attempts"]
                                               for z in a["zips"]})),
                "code": code, "arm": i["arm"], "key": f"{code}_{i['arm']}",
                "device": i["device"],
                "android": (re.search(r"Android ([\d.]+)", i["device"]) or [None, ""])[1],
                "group": ss.get("group", ""),
                "condition_order": ">".join(ss.get("condition_order") or []),
                "session": s, "condition": ss.get("condition", ""),
                "product": (ss.get("product") or "").lower(),
                "n_attempts": len(i["attempts"]),
                "n_complete": sum(a["complete"] for a in i["attempts"]),
                "first_window": f"{f['start']}..{f['end']}" if f else "",
                "last_window": f"{l['start']}..{l['end']}" if l else "",
                "photos_captured_first": f["photos_captured"] if f else "",
                "photos_final_first": f["photos_final"] if f else "",
                "photos_to_score_first": len(f["scoring_hashes"]) if f else "",
                "photos_to_score_last": len(l["scoring_hashes"]) if l else "",
                "hashes_present": f["hashes_present"] if f else "",
                "gate_result": f["gate"] if f else "",
                "flags": " | ".join(fl)})
            keys[(code, i["arm"])][s] = rows[-1]

    # ---- inclusion ------------------------------------------------------------------
    verdict = {}
    for (code, arm), ses in sorted(keys.items()):
        why = []
        if set(ses) != {1, 2}:
            why.append(f"sessions_present={sorted(ses)}")
        if any(r["n_complete"] == 0 for r in ses.values()):
            why.append("session_without_complete_attempt")
        if len({r["device"] for r in ses.values()}) > 1:
            why.append("sessions_on_different_devices")
        if len({r["product"] for r in ses.values()}) > 1:
            why.append("different_product_between_sessions")
        if any(r["hashes_present"] is False for r in ses.values()):
            why.append("hashes_missing_from_zip")
        if len(ses) == 2 and len({r["condition"] for r in ses.values()}) < 2:
            why.append("conditions_not_GUIDED_and_UNGUIDED")
        verdict[(code, arm)] = why
    for r in rows:
        w = verdict[(r["code"], r["arm"])]
        r["primary"] = (not w) and r["arm"] == "REMOTE"
        r["secondary"] = not w
        r["exclusion_reason"] = ";".join(w)
    fields = ["zip", "zip_sha256", "key", "code", "arm", "device", "android", "group",
              "condition_order", "session", "condition", "product", "n_attempts", "n_complete",
              "first_window", "last_window", "photos_captured_first", "photos_final_first",
              "photos_to_score_first", "photos_to_score_last", "hashes_present", "gate_result",
              "primary", "secondary", "exclusion_reason", "flags"]
    with open(ROOT / "participant_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["code"], r["session"])))

    # scoring list (hash -> key/session) for step 2
    todo = []
    for (code, sess), at in attempts.items():
        comp = [a for a in at if a["complete"]]
        if not comp:
            continue
        arm = next(r["arm"] for r in rows if r["code"] == code and r["session"] == sess)
        for tag, a in (("first", comp[0]), ("last", comp[-1])):
            for h in a["scoring_hashes"]:
                todo.append({"key": f"{code}_{arm}", "session": sess, "which": tag,
                             "hash": h, "zips": ";".join(a["zips"])})
    with open(ROOT / "scoring_list.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["key", "session", "which", "hash", "zips"])
        w.writeheader()
        w.writerows(sorted(todo, key=lambda r: (r["key"], r["session"], r["which"], r["hash"])))

    report["verdict"] = {f"{k[0]}_{k[1]}": v for k, v in verdict.items()}
    (ROOT / "manifest_report.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "excluded_rows"}
                   | {"excluded_row_count": len(report["excluded_rows"])}, indent=1))

    # ---- print ----------------------------------------------------------------------
    print("RAW SHA-256 ->", ROOT / "raw_sha256.txt")
    print("\nMALFORMED LINES (skipped, not repaired):")
    for m in report["malformed_lines"]:
        print(f"  {m['zip']} line {m['line']}: {m['error']} | {m['start']!r}")
    print("\nEXCLUDED ZIPS:", *[f"\n  {x['zip']}  [{x['reason']}]" for x in report["excluded_zips"]])
    print("\nEXCLUDED ROWS:", {f"{k[0]}|{k[1]}": len(v) for k, v in byr.items()})
    print("\nMANIFEST")
    for r in sorted(rows, key=lambda r: (r["code"], r["session"])):
        print(f"{r['key']:<14}s{r['session']} {r['condition']:<9}{r['product']:<6}"
              f"att={r['n_attempts']}/{r['n_complete']}c photos(cap/final/score)="
              f"{r['photos_captured_first']}/{r['photos_final_first']}/{r['photos_to_score_first']} "
              f"hash={r['hashes_present']} gate={r['gate_result']} {r['android']} "
              f"{r['group']} {r['condition_order']} {r['flags']}")
    print("\nKEYS")
    for k, w in sorted(verdict.items()):
        tier = "EXCLUDED: " + ",".join(w) if w else ("PRIMARY" if k[1] == "REMOTE" else "SECONDARY")
        print(f"  {k[0]}_{k[1]}: {tier}")
    return attempts, rows, verdict


if __name__ == "__main__":
    main()
