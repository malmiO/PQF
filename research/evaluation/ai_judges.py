"""
ai_judges.py  -  independent AI-judge panel (J1-J3) for the cross-check (spec: AI_Judge_Protocol_2026-10-16).

The judges see ONLY a neutral prompt and neutral images (labelled A/B or 1..n). Private keys
(condition, source, fault type, file names, sha256) never enter a prompt. Every pair/set is judged
in BOTH presentation orders; a judge's vote counts only when it is the same in both orders,
otherwise that judge = tie. Unparseable answers are retried (max 3) then logged as missing,
never guessed. An HTTP/API error stops the run (nothing is retried silently): ask the owner.

Sources (--source) and the sheet each writes, in the layout the analysis scripts read:
  blind_pairs   --dir <make_blind_packs out>   (blind_key.csv + blind_pairs/)   -> rater_sheet.csv
  packs_sets    --dir <make_blind_packs out> --photos <folder> (packs/product_photo_key.csv)
                                                                                   -> photographer_picks_sheet.csv
  bank_pairs    --pair-key research/results/crosscheck/pair_key.csv              -> crosscheck_pairs_sheet.csv
                                                  (+ gate.json: known-answer gate, 24 holdout pairs)
  bank_sets     --set-key <set_photo_key.csv>                                    -> crosscheck_picks_sheet.csv
rater ids are J1, J2, J3.  Outputs go to --out (a folder of its own):
  ai_judge_log.jsonl         raw log: item, order, judge, requested+returned model, routed provider,
                             prompt hash, response, timestamp, tokens, cost
  ai_judge_consistency.csv   judge, item_id, valid_both_orders, consistent
  <sheet>.csv, gate.json

  python ai_judges.py models                       # model metadata (list call, no judging)
  python ai_judges.py run --source bank_pairs ...  # prints the estimated cost; add --yes to spend
  python ai_judges.py run --mock ...               # mock judge, no API
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

JUDGES = {"J1": "openai/gpt-6.1-sol", "J2": "anthropic/claude-sonnet-5.5",
          "J3": "qwen/qwen3.8-max-0902"}
FRAMEWORK_EVALUATOR = "gemini-3.5-flash-lite"       # never a judge
API = "https://openrouter.ai/api/v1"
LONGEST, QUALITY = 1536, 92
MAX_PARSE_TRIES = 3
ROLES = ("main", "angle1", "angle2", "detail")

PAIR_PROMPT = ("You are an experienced e-commerce product photographer. Which photo is better for an "
               "online product listing? Answer A, B or NO_DIFFERENCE, give strength 1-5 and one short reason.")
PAIR_FORMAT = ' Reply with JSON only: {"choice": "A" | "B" | "NO_DIFFERENCE", "strength": 1-5, "reason": "..."}'
SET_PROMPT = ("Pick the best MAIN photo, two photos showing DIFFERENT angles, and one DETAIL photo, "
              "by number, with one short reason.")
SET_FORMAT = (' Reply with JSON only: {"main": n, "angle1": n, "angle2": n, "detail": n, "reason": "..."}'
              " using four different numbers.")

OPEN_WEIGHTS = {  # not given by the API: from the vendors' public release status (check before citing)
    "openai/": "closed", "anthropic/": "closed", "qwen/qwen3.8-max": "closed (Max tier is API-only)"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_slug(slug: str) -> str:
    if ":free" in slug.lower():
        raise SystemExit(f"{slug}: ':free' variants are never allowed")
    if FRAMEWORK_EVALUATOR in slug:
        raise SystemExit(f"{slug}: the framework's own evaluator cannot be a judge")
    return slug


# ------------------------------------------------------------------------------ images
def prep_image(path: Path) -> bytes:
    """Identical for all judges: EXIF orientation applied, longest side 1536 px (never upscaled),
    RGB JPEG q92."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = im.size
    s = LONGEST / max(w, h)
    if s < 1:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY)
    return buf.getvalue()


def img_tokens(data: bytes) -> int:
    from PIL import Image
    w, h = Image.open(io.BytesIO(data)).size
    return int(w * h / 750) + 85


# ------------------------------------------------------------------------------ items
@dataclass
class Item:
    source: str
    item_id: str
    kind: str                    # pair | set
    images: list                 # canonical order: A,B  or  1..n
    meta: dict                   # sheet columns (never sent to a judge)


def _csv(p: Path) -> list:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolve(p: str, *roots) -> Path:
    p = p.replace("\\", "/")
    for r in roots:
        if (r / p).exists():
            return r / p
    raise FileNotFoundError(p)


def load_items(a) -> list:
    out = []
    if a.source == "blind_pairs":
        d = Path(a.dir)
        for r in _csv(d / "blind_key.csv"):
            im = [next((d / "blind_pairs").glob(f"pair_{r['pair_id']}_{s}.*")) for s in "AB"]
            out.append(Item("blind_pairs", r["pair_id"], "pair", im, {"pair_id": r["pair_id"]}))
    elif a.source == "bank_pairs":
        for r in _csv(Path(a.pair_key)):
            im = [resolve(r["left_path"], REPO, REPO / "data"), resolve(r["right_path"], REPO, REPO / "data")]
            out.append(Item("bank_pairs", r["pair_id"], "pair", im, {"pair_id": r["pair_id"]}))
    elif a.source == "packs_sets":
        from make_blind_packs import index_photos
        photos = index_photos(Path(a.photos))
        by = {}
        for r in _csv(Path(a.dir) / "packs" / "product_photo_key.csv"):
            by.setdefault(r["product"], []).append((int(r["number"]), photos.get(r["sha256"])))
        for prod, lst in sorted(by.items()):
            lst.sort()
            if any(p is None for _, p in lst):
                raise SystemExit(f"product {prod}: photos missing from --photos")
            out.append(Item("packs_sets", prod, "set", [p for _, p in lst], {"product": prod,
                            "numbers": [n for n, _ in lst]}))
    elif a.source == "bank_sets":
        by = {}
        for r in _csv(Path(a.set_key)):
            by.setdefault(r["set_id"], []).append((int(r["number"]), resolve(r["path"], REPO, REPO / "data")))
        for sid, lst in sorted(by.items()):
            lst.sort()
            out.append(Item("bank_sets", sid, "set", [p for _, p in lst], {"set_id": sid,
                            "numbers": [n for n, _ in lst]}))
    else:
        raise SystemExit("unknown --source")
    for it in out:
        if it.kind == "set" and "numbers" not in it.meta:
            it.meta["numbers"] = list(range(1, len(it.images) + 1))
    return out


def build_request(item: Item, order: int, cache: dict) -> tuple:
    """-> (parts, to_canonical). parts = [('text', s) | ('image', bytes)]. order 1 = canonical,
    order 2 = pair swapped / set reversed. to_canonical maps a presented label to the canonical one."""
    idx = list(range(len(item.images)))
    if order == 2:
        idx = idx[::-1]
    for i in idx:
        p = item.images[i]
        if p not in cache:
            cache[p] = prep_image(p)
    if item.kind == "pair":
        prompt = PAIR_PROMPT + PAIR_FORMAT
        parts = [("text", prompt)]
        for lab, i in zip("AB", idx):
            parts += [("text", f"Photo {lab}:"), ("image", cache[item.images[i]])]
        mapping = {lab: "AB"[i] for lab, i in zip("AB", idx)}
    else:
        n = len(idx)
        prompt = f"These {n} photos show one product, numbered 1 to {n} in the order given. " \
                 + SET_PROMPT + SET_FORMAT
        parts = [("text", prompt)]
        for pos, i in enumerate(idx, 1):
            parts += [("text", f"Photo {pos}:"), ("image", cache[item.images[i]])]
        mapping = {pos: item.meta["numbers"][i] for pos, i in enumerate(idx, 1)}
    return parts, mapping


def prompt_hash(parts) -> str:
    h = hashlib.sha256()
    for k, v in parts:
        h.update((v if k == "text" else "<image>").encode())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------ parsing
def extract_json(text: str):
    try:
        i, j = text.index("{"), text.rindex("}")
        return json.loads(text[i:j + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def parse_pair(text: str):
    d = extract_json(text)
    if not isinstance(d, dict):
        return None
    c = str(d.get("choice", "")).strip().upper().replace(" ", "_")
    c = "NO_DIFFERENCE" if c in ("TIE", "NO_DIFFERENCE", "NONE", "=") else c
    try:
        s = int(d.get("strength"))
    except (TypeError, ValueError):
        return None
    if c not in ("A", "B", "NO_DIFFERENCE") or not 1 <= s <= 5:
        return None
    return {"choice": c, "strength": s, "reason": str(d.get("reason", ""))[:300]}


def parse_set(text: str, n: int):
    d = extract_json(text)
    if not isinstance(d, dict):
        return None
    try:
        v = {r: int(d[r]) for r in ROLES}
    except (KeyError, TypeError, ValueError):
        return None
    if len(set(v.values())) != 4 or any(not 1 <= x <= n for x in v.values()):
        return None
    return {**v, "reason": str(d.get("reason", ""))[:300]}


# ------------------------------------------------------------------------------ backends
class ApiStop(Exception):
    pass


class OpenRouter:
    def __init__(self, key: str):
        self.key = key

    def chat(self, model: str, parts: list, max_tokens: int = 4000) -> dict:
        content = []
        for k, v in parts:
            if k == "text":
                content.append({"type": "text", "text": v})
            else:
                content.append({"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(v).decode()}})
        body = {"model": model, "messages": [{"role": "user", "content": content}],
                "temperature": 0, "max_tokens": max_tokens,
                "provider": {"data_collection": "deny"}}
        req = urllib.request.Request(API + "/chat/completions", json.dumps(body).encode(), {
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
        except urllib.error.HTTPError as e:
            raise ApiStop(f"HTTP {e.code} from OpenRouter for {model}: {e.read()[:400]!r}")
        except Exception as e:      # any failure (network, truncated body, bad JSON ...) stops the run, logged
            raise ApiStop(f"{type(e).__name__} for {model}: {str(e)[:300]}")
        if "error" in r:
            raise ApiStop(f"OpenRouter error for {model}: {json.dumps(r['error'])[:400]}")
        ch = (r.get("choices") or [{}])[0]
        u = r.get("usage") or {}
        return {"text": (ch.get("message") or {}).get("content") or "", "model": r.get("model"),
                "provider": r.get("provider"), "id": r.get("id"),
                "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"),
                "cost": u.get("cost"), "finish": ch.get("finish_reason")}


class Mock:
    """No API. Decides from the image bytes only (edge energy), with judge-specific behaviour:
    J1 sound, J2 position-biased towards 'A'/'1', J3 noisy and emits one malformed answer first."""

    def __init__(self):
        self.calls = 0
        self.seen = set()

    @staticmethod
    def energy(b: bytes) -> float:
        from PIL import Image, ImageFilter, ImageStat
        im = Image.open(io.BytesIO(b)).convert("L").resize((256, 256))
        return ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).mean[0]

    def chat(self, model: str, parts: list, max_tokens: int = 4000) -> dict:
        self.calls += 1
        j = model.split("-")[-1]
        imgs = [v for k, v in parts if k == "image"]
        e = [self.energy(b) for b in imgs]
        key = (j, hashlib.md5(b"".join(imgs)).hexdigest())
        first = key not in self.seen
        self.seen.add(key)
        if j == "J3" and first:
            text = "I think the first one looks better."          # malformed -> retry path
        elif len(imgs) == 2:
            pick = 0 if e[0] >= e[1] else 1
            if j == "J2" and abs(e[0] - e[1]) < 0.15 * max(e):
                pick = 0
            if j == "J3" and int(hashlib.md5(b"".join(imgs)).hexdigest(), 16) % 5 == 0:
                pick = 1 - pick
            text = json.dumps({"choice": "AB"[pick], "strength": 3, "reason": "mock"})
        else:
            rank = sorted(range(len(imgs)), key=lambda i: -e[i])
            if j == "J2":
                rank = list(range(len(imgs)))
            text = json.dumps({"main": rank[0] + 1, "angle1": rank[1] + 1, "angle2": rank[2] + 1,
                               "detail": rank[3] + 1, "reason": "mock"})
        return {"text": text, "model": f"mock/{j}-v1", "provider": "mock", "id": f"mock{self.calls}",
                "tokens_in": 100, "tokens_out": 20, "cost": 0.0, "finish": "stop"}


# ------------------------------------------------------------------------------ run
def load_log(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_log(path: Path, row: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


AMEND_LIMIT = 12000      # J3, set stage only, only for calls that came back empty at 4000 (amendment 2026-10-17)


def is_amended(judge: str, item) -> bool:
    return judge == "J3" and item.kind == "set"


def done_keys(log: list) -> set:
    """(source, item, order, judge) that need no further call: a valid answer, a genuine parse
    'missing', or an amended 12000 attempt. An 'empty at 4000' missing is NOT done."""
    done = set()
    for r in log:
        k = (r["source"], r["item_id"], r["order"], r["judge"])
        if r.get("status") == "ok":
            done.add(k)
        elif r.get("status") == "missing" and not r.get("empty_at_4000"):
            done.add(k)
        elif r.get("max_tokens") == AMEND_LIMIT and r.get("status") in ("ok", "missing"):
            done.add(k)
    return done


def remaining(items, judges, log: list) -> list:
    done = done_keys(log)
    return [(j, it, order) for it in items for order in (1, 2) for j in judges
            if (it.source, it.item_id, order, j) not in done]


def estimate(items, judges, models, prices, cache, log=None) -> dict:
    est = {}
    todo = remaining(items, judges, log or [])
    for j in judges:
        mine = [(it, o) for jj, it, o in todo if jj == j]
        tin, tout = 0, 0
        for it, order in mine:
            parts, _ = build_request(it, order, cache)
            tin += 300 + sum(img_tokens(v) for k, v in parts if k == "image")
            # J3 sets: worst case one empty 4000 attempt plus one 12000 attempt
            tout += (4000 + AMEND_LIMIT) if is_amended(j, it) else 800
        pin, pout = prices.get(models[j], (0.0, 0.0))
        est[j] = {"model": models[j], "calls_still_to_run": len(mine),
                  "calls": [f"{it.item_id}/order{o}" for it, o in mine],
                  "input_tokens": tin, "output_tokens_allowance": tout,
                  "usd": round((tin * pin + tout * pout) / 1e6, 3)}
    return est


def _call(backend, model, parts, max_tokens, log_path=None, ctx=None):
    """One request. A call that dies with IncompleteRead is retried up to 2 more times with the
    IDENTICAL request; each failed attempt is logged (status transport_error). Anything else stops."""
    for k in range(3):
        try:
            if max_tokens == 4000:
                return backend.chat(model, parts)
            return backend.chat(model, parts, max_tokens=max_tokens)
        except ApiStop as e:
            if not str(e).startswith("IncompleteRead") or k == 2:
                raise
            if log_path is not None:
                append_log(log_path, {**(ctx or {}), "status": "transport_error", "transport_attempt": k + 1,
                                      "max_tokens": max_tokens, "error": str(e)[:300], "timestamp": now(),
                                      "cost_usd": 0})


def run_calls(items, judges, models, backend, log_path, cache, source, max_usd=None):
    log0 = load_log(log_path)
    todo = remaining(items, judges, log0)
    pre_flagged = {(r["source"], r["item_id"], r["order"], r["judge"]) for r in log0 if r.get("empty_at_4000")}
    for j, it, order in todo:
        parts, mapping = build_request(it, order, cache)
        ph = prompt_hash(parts)
        n = len(it.images)
        if max_usd is not None and sum(r.get('cost_usd') or 0 for r in load_log(log_path)) > max_usd:
            raise ApiStop(f'running total passed USD {max_usd}: stopped')
        limit, flagged = 4000, False
        if (source, it.item_id, order, j) in pre_flagged:      # already empty at 4000: go straight to the amended limit
            limit, flagged = AMEND_LIMIT, True
        for attempt in range(1, MAX_PARSE_TRIES + 1):
            r = _call(backend, models[j], parts, limit, log_path,
                      {"source": source, "item_id": it.item_id, "order": order, "judge": j,
                       "requested_model": models[j], "prompt_hash": ph})   # other ApiStop: ask the owner
            p = parse_pair(r["text"]) if it.kind == "pair" else parse_set(r["text"], n)
            empty = not (r["text"] or "").strip()
            row = {"source": source, "item_id": it.item_id, "order": order, "judge": j,
                   "requested_model": models[j], "returned_model": r["model"],
                   "provider": r["provider"], "prompt_hash": ph, "attempt": attempt,
                   "max_tokens": limit, "response": r["text"], "parsed": p,
                   "mapping": {str(k): v for k, v in mapping.items()},
                   "timestamp": now(), "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                   "cost_usd": r["cost"], "finish": r["finish"], "status": "ok" if p else "retry"}
            if is_amended(j, it) and limit == 4000 and empty and r["finish"] == "length":
                row["status"] = "empty_at_4000"          # kept in the log, flagged; not retried at 4000
                row["empty_at_4000"] = True
                append_log(log_path, row)
                limit, flagged = AMEND_LIMIT, True
                continue
            if flagged:
                row["amended_after_empty_at_4000"] = True
                if empty and not p:
                    row["status"] = "missing"            # still empty at 12000: missing, no further raise
            if not p and attempt == MAX_PARSE_TRIES:
                row["status"] = "missing"
            append_log(log_path, row)
            if p or row["status"] == "missing":
                break


def canonical(row: dict, kind: str):
    """A logged ok row -> its answer in the canonical frame."""
    p, m = row["parsed"], row["mapping"]
    if kind == "pair":
        return "tie" if p["choice"] == "NO_DIFFERENCE" else m[p["choice"]]
    return {r: m[str(p[r])] for r in ROLES}


def judge_outcomes(log: list, items: list, judges: list) -> dict:
    """(judge, item_id) -> {'status': missing|ok, 'vote': ..., 'consistent': bool, ...}"""
    out = {}
    by = {(r["item_id"], r["order"], r["judge"]): r for r in log
          if r["status"] in ("ok", "missing") and r["source"] == items[0].source} if items else {}
    for it in items:
        for j in judges:
            r1, r2 = by.get((it.item_id, 1, j)), by.get((it.item_id, 2, j))
            if not r1 or not r2 or r1["status"] != "ok" or r2["status"] != "ok":
                out[(j, it.item_id)] = {"valid": False, "consistent": False}
                continue
            c1, c2 = canonical(r1, it.kind), canonical(r2, it.kind)
            if it.kind == "pair":
                ok = c1 == c2
                s = round((r1["parsed"]["strength"] + r2["parsed"]["strength"]) / 2)
                out[(j, it.item_id)] = {"valid": True, "consistent": ok,
                                        "vote": c1 if ok else "tie", "strength": s if ok and c1 != "tie" else ""}
            else:
                same = {r: c1[r] == c2[r] for r in ROLES}
                out[(j, it.item_id)] = {"valid": True, "consistent": all(same.values()),
                                        "roles_consistent": sum(same.values()),
                                        "picks": {r: (c1[r] if same[r] else "") for r in ROLES}}
    return out


SHEET = {"blind_pairs": "rater_sheet.csv", "bank_pairs": "crosscheck_pairs_sheet.csv",
         "packs_sets": "photographer_picks_sheet.csv", "bank_sets": "crosscheck_picks_sheet.csv"}


def write_sheet(out: Path, items, outcomes, judges):
    rows = []
    for j in judges:
        for it in items:
            o = outcomes[(j, it.item_id)]
            if it.kind == "pair":
                v = o.get("vote", "") if o["valid"] else ""
                pref = "" if not o["valid"] else ("tie" if v == "tie" else v)
                rows.append({"rater": j, "pair_id": it.item_id, "preferred": pref,
                             "strength": o.get("strength", "") if o["valid"] else ""})
            else:
                idcol = "product" if it.source == "packs_sets" else "set_id"
                for r in ROLES:
                    rows.append({"rater": j, idcol: it.item_id, "role": r,
                                 "photo_no": o["picks"][r] if o["valid"] else ""})
    keys = list(rows[0]) if rows else []
    with open(out / SHEET[items[0].source], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with open(out / f"ai_judge_consistency_{items[0].source}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["judge", "item_id", "source", "valid_both_orders", "consistent"],
                           lineterminator="\n")
        w.writeheader()
        for (j, iid), o in sorted(outcomes.items()):
            w.writerow({"judge": j, "item_id": iid, "source": items[0].source,
                        "valid_both_orders": o["valid"], "consistent": o["consistent"]})


def pair_sheet_to_votes(key_rows: list, sheet_rows: list) -> dict:
    """crosscheck_pairs_sheet rows -> pair_id -> judge -> clean|fault|tie (uses the private key)."""
    from human_crosscheck import decode_votes
    return decode_votes(sheet_rows, {r["pair_id"]: r for r in key_rows})


def make_gate(out: Path, pair_key: Path, judges):
    from panel import known_answer_gate
    key = _csv(pair_key)
    votes = pair_sheet_to_votes(key, _csv(out / SHEET["bank_pairs"]))
    g = known_answer_gate(key, votes, judges)
    (out / "gate.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    return g


# ------------------------------------------------------------------------------ models / prices
def fetch_models(key: str) -> dict:
    req = urllib.request.Request(API + "/models", headers={"Authorization": "Bearer " + key})
    return {m["id"]: m for m in json.load(urllib.request.urlopen(req, timeout=60))["data"]}


def price_of(m: dict) -> tuple:
    p = m["pricing"]
    return float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6


def env_key() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except ImportError:
        pass
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k and (REPO / ".env").exists():
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"\'')
    if not k:
        raise SystemExit("OPENROUTER_API_KEY not found in the environment or .env")
    return k


def parse_models(arg: str) -> dict:
    m = dict(JUDGES)
    for kv in filter(None, (arg or "").split(",")):
        j, s = kv.split("=", 1)
        m[j] = s
    return {j: check_slug(s) for j, s in m.items()}


def _log_error(out: Path, kind: str, detail: str):
    with open(out / "ai_judge_errors.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": now(), "kind": kind, "detail": detail[-3000:]}) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    mp = sub.add_parser("models")
    mp.add_argument("--models", default="")
    rp = sub.add_parser("run")
    rp.add_argument("--source", required=True, choices=list(SHEET))
    rp.add_argument("--dir")
    rp.add_argument("--photos")
    rp.add_argument("--pair-key", default=str(REPO / "research/results/crosscheck/pair_key.csv"))
    rp.add_argument("--set-key")
    rp.add_argument("--out", required=True)
    rp.add_argument("--judges", default="J1,J2,J3")
    rp.add_argument("--models", default="")
    rp.add_argument("--mock", action="store_true")
    rp.add_argument("--yes", action="store_true", help="spend: without it only the estimate is printed")
    rp.add_argument("--max-usd", type=float, default=6.0, help="stop when the running total passes this")
    rp.add_argument("--repeat-every", type=int, default=0,
                    help="bank_pairs only: re-judge every Nth pair as source bank_pairs_repeat (self-consistency)")
    rp.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    models = parse_models(a.models)
    if a.cmd == "models":
        meta = fetch_models(env_key())
        for j, s in models.items():
            m = meta.get(s)
            if not m:
                print(j, s, "NOT FOUND")
                continue
            pi, po = price_of(m)
            sp = m.get("supported_parameters", [])
            print(json.dumps({"judge": j, "slug": s, "input_modalities": m["architecture"]["input_modalities"],
                              "reasoning_model": "reasoning" in sp or "include_reasoning" in sp,
                              "weights": next((v for k, v in OPEN_WEIGHTS.items() if s.startswith(k)), "unknown"),
                              "usd_per_M_in": pi, "usd_per_M_out": po,
                              "temperature_supported": "temperature" in sp}))
        return 0
    judges = [j for j in a.judges.split(",") if j]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = load_items(a)
    if a.limit:
        items = items[:a.limit]
    if a.repeat_every:
        items = items[::a.repeat_every]
        for it in items:
            it.source = "bank_pairs_repeat"
    cache = {}
    if a.mock:
        backend, prices = Mock(), {}
        models = {j: f"mock-{j}" for j in judges}
    else:
        key = env_key()
        meta = fetch_models(key)
        for j in judges:
            if "image" not in meta[models[j]]["architecture"]["input_modalities"]:
                raise SystemExit(f"{j} {models[j]} cannot take image input: replace it")
        prices = {models[j]: price_of(meta[models[j]]) for j in judges}
        backend = OpenRouter(key)
    log_path = out / "ai_judge_log.jsonl"
    est = estimate(items, judges, models, prices, cache, load_log(log_path))
    print("ESTIMATED COST (before any call):")
    print(json.dumps(est, indent=1), "\nTOTAL USD ~", round(sum(e["usd"] for e in est.values()), 3))
    if not a.mock and not a.yes:
        print("No call made. Re-run with --yes to spend.")
        return 0
    p0, _ = build_request(items[0], 1, cache)
    params = {"timestamp": now(), "source": items[0].source, "items": len(items), "models": models,
              "request_params": {"temperature": 0, "max_tokens": 4000,
                                 "provider": {"data_collection": "deny"}},
              "image_prep": {"longest_side": LONGEST, "jpeg_quality": QUALITY, "exif_applied": True},
              "prompt_hash_first_item": prompt_hash(p0), "pair_prompt": PAIR_PROMPT + PAIR_FORMAT,
              "max_usd": a.max_usd, "mock": a.mock}
    if items[0].kind == "set":
        params["amendment"] = {
            "date": "2026-10-17", "judge": "J3", "stage": "set (packs_sets, bank_sets) only",
            "reason": "J3 (reasoning model) used all 4000 max_tokens and returned an empty answer on the "
                      "set prompt (finish=length), declared before any retry",
            "affected_calls_known_at_declaration": ["packs_sets 2001 order1 J3", "packs_sets 2001 order2 J3"],
            "rule": "only calls that return an empty answer at 4000 are re-run once at the new limit; "
                    "original empty calls stay in the log flagged empty_at_4000; no other judge, prompt, "
                    "image, temperature or ordering changes; still empty at the new limit = missing",
            "new_max_tokens": AMEND_LIMIT}
    with open(out / "run_params.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(params) + "\n")
    print("PARAMS:", json.dumps(params))
    try:
        run_calls(items, judges, models, backend, log_path, cache, items[0].source, a.max_usd)
    except ApiStop as e:
        _log_error(out, "ApiStop", str(e))
        print("API ERROR - run stopped, ask the owner before retrying:", e)
        return 2
    except BaseException as e:      # nothing may exit silently
        import traceback
        _log_error(out, type(e).__name__, traceback.format_exc())
        print("UNEXPECTED ERROR - run stopped:", type(e).__name__, e)
        traceback.print_exc()
        return 3
    if a.repeat_every:
        tot = sum(r.get("cost_usd") or 0 for r in load_log(log_path))
        print(f"repeat stage done. running total USD {tot:.4f}")
        return 0
    outcomes = judge_outcomes(load_log(log_path), items, judges)
    write_sheet(out, items, outcomes, judges)
    if a.source == "bank_pairs":
        print("known-answer gate:", json.dumps(make_gate(out, Path(a.pair_key), judges), indent=1))
    tot = sum(r.get("cost_usd") or 0 for r in load_log(log_path))
    print(f"done. calls logged: {len(load_log(log_path))}; actual cost so far USD {tot:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
