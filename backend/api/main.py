"""
PQF API.

Exposes the Photography Quality Framework over HTTP so the mobile application
can use it. The framework itself lives in backend.pqf and is not duplicated
here. This layer only handles transport, validation and shaping of responses.

Endpoints
    GET  /health              liveness and configuration summary
    POST /score               score one image, full framework, returns a decision
    POST /guidance            fast on device style check, cheap criteria only
    POST /batch               score several images, select a set, run the gate
    GET  /criteria            the criteria, weights and thresholds in force

Run locally
    uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

The mobile client on a physical device cannot reach localhost on your machine,
so use your machine's LAN address, for example http://192.168.1.5:8000
"""
from __future__ import annotations

import io
import time
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..pqf import config
from ..pqf.pipeline import score_image, process_batch
from ..pqf.combination import ImageDecision

app = FastAPI(
    title="Photography Quality Framework API",
    description="Scores product photographs against the PQF specification.",
    version="1.0.0",
)

# The mobile client is a separate origin. Open during development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024

# Live guidance parameters. Guidance trades precision for speed, because it runs
# repeatedly on a viewfinder frame rather than once on a capture decision.
GUIDANCE_LONGEST_SIDE = 512   # analysed size for live frames
GUIDANCE_PASS_MIN = 0.40      # exposure and background pass mark
GUIDANCE_SHARPNESS_MIN = 0.12 # lower than scoring, since variance falls with size
ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------
class CriterionScore(BaseModel):
    name: str
    score: float
    weight: float
    passed: bool | None = None


class ScoreResponse(BaseModel):
    tqs: float
    sqs: float
    fqs: float
    role: str
    passed: bool
    hard_rejected: bool
    reason: str
    technical: List[CriterionScore]
    semantic: List[CriterionScore]
    feedback: List[str]
    elapsed_ms: int


class GuidanceResponse(BaseModel):
    ready: bool
    checks: List[CriterionScore]
    feedback: List[str]
    elapsed_ms: int


class BatchImageResult(BaseModel):
    index: int
    fqs: float
    role: str
    passed: bool


class BatchResponse(BaseModel):
    certified: bool
    selected: List[BatchImageResult]
    role_sets: dict
    recapture: dict | None
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Corrective feedback, driven by which criterion failed
# ---------------------------------------------------------------------------
FEEDBACK = {
    "sharpness":   "Hold the phone steady and tap the product to focus.",
    "exposure":    "Adjust the brightness. Move to better light if the product looks dark.",
    "background":  "Place the product on a plain white or light surface.",
    "brisque":     "Image quality is low overall. Clean the lens and retake.",
    "piqe":        "Part of the image is unclear. Retake with steadier hands.",
    "colorcast":   "Colour looks tinted. Use neutral lighting or adjust white balance.",
    "subject_centering":      "Centre the product in the frame and avoid cutting it off.",
    "feature_visibility":     "Move closer or adjust the angle so the details are visible.",
    "marketing_suitability":  "The shot does not look ready to post. Improve lighting and framing.",
    "angle_value":            "Try a different angle that shows more about the product.",
    "lighting_style_quality": "Improve the lighting. Avoid harsh shadows on the product.",
}


def _read_upload(f: UploadFile) -> bytes:
    if f.content_type not in ALLOWED_MIME:
        raise HTTPException(415, f"Unsupported type {f.content_type}. Send JPEG, PNG or WebP.")
    data = f.file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. Limit is {MAX_UPLOAD_BYTES // (1024*1024)} MB.")
    return data


def _shape(d: ImageDecision) -> tuple[list, list, list]:
    """Turn a decision into per criterion lists plus corrective feedback."""
    tech_raw = getattr(d, "technical_scores", {}) or {}
    technical = [
        CriterionScore(name=k, score=round(tech_raw.get(k, 0.0), 3), weight=w)
        for k, w in config.TQS_WEIGHTS.items()
    ]
    semantic = [
        CriterionScore(
            name=k,
            score=round(d.semantic_scores.get(k, 0.0), 3),
            weight=w,
            passed=d.semantic_scores.get(k, 0.0) >= config.SQS_PASS_THRESHOLDS.get(k, 0.0),
        )
        for k, w in config.SQS_WEIGHTS.items()
    ] if d.semantic_scores else []

    feedback = []
    for c in technical:
        if c.score < 0.40 and c.name in FEEDBACK:
            feedback.append(FEEDBACK[c.name])
    for c in semantic:
        if c.passed is False and c.name in FEEDBACK:
            feedback.append(FEEDBACK[c.name])
    return technical, semantic, feedback


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "framework_version": getattr(config, "SPEC_VERSION", "1.3"),
        "semantic_model": getattr(config, "GEMINI_MODEL", "unknown"),
        "fqs_alpha": config.FQS_ALPHA,
        "fqs_beta": config.FQS_BETA,
        "fqs_pass_threshold": config.FQS_PASS_THRESHOLD,
    }


@app.get("/criteria")
def criteria():
    """The criteria in force, so the client never hard codes them."""
    return {
        "technical": [
            {"name": k, "weight": w} for k, w in config.TQS_WEIGHTS.items()
        ],
        "semantic": [
            {"name": k, "weight": w,
             "pass_threshold": config.SQS_PASS_THRESHOLDS.get(k)}
            for k, w in config.SQS_WEIGHTS.items()
        ],
        "combination": {
            "alpha": config.FQS_ALPHA,
            "beta": config.FQS_BETA,
            "pass_threshold": config.FQS_PASS_THRESHOLD,
        },
        "roles": config.ROLE_RULES,
        "role_priority": config.ROLE_PRIORITY,
    }


@app.post("/score", response_model=ScoreResponse)
def score(file: UploadFile = File(...)):
    """Full framework evaluation of one image. Costs one semantic model call."""
    t0 = time.time()
    data = _read_upload(file)
    d = score_image(data, path=file.filename, mime=file.content_type)
    technical, semantic, feedback = _shape(d)
    return ScoreResponse(
        tqs=round(d.tqs, 3), sqs=round(d.sqs, 3), fqs=round(d.fqs, 3),
        role=d.role, passed=d.passed, hard_rejected=d.hard_rejected,
        reason=d.reason, technical=technical, semantic=semantic,
        feedback=feedback, elapsed_ms=int((time.time() - t0) * 1000),
    )


@app.post("/guidance", response_model=GuidanceResponse)
def guidance(file: UploadFile = File(...)):
    """Fast pre capture check. Cheap deterministic criteria only.

    Runs sharpness, exposure and background, which are the faults a user can
    correct while still holding the camera. It never calls the semantic model,
    so it is fast and free, and it is the endpoint the live viewfinder uses.

    The frame is analysed at a reduced working size, because live guidance needs
    speed rather than the precision required for a scoring decision. Scores from
    this endpoint are indicative and are never used for certification. The full
    /score endpoint at the standard working resolution makes that decision.
    """
    t0 = time.time()
    data = _read_upload(file)

    import numpy as np
    import cv2
    from ..pqf import technical as T

    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode the image.")

    # Reduced working size for live use. Sharpness is resolution dependent, so
    # the threshold below is deliberately lower than the scoring threshold.
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > GUIDANCE_LONGEST_SIDE:
        s = GUIDANCE_LONGEST_SIDE / longest
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    checks = []
    for name, fn, thr in (("sharpness", T.t1_sharpness, GUIDANCE_SHARPNESS_MIN),
                          ("exposure", T.t2_exposure, GUIDANCE_PASS_MIN),
                          ("background", T.t3_background, GUIDANCE_PASS_MIN)):
        s = float(fn(img))
        checks.append(CriterionScore(name=name, score=round(s, 3),
                                     weight=config.TQS_WEIGHTS[name],
                                     passed=s >= thr))

    feedback = [FEEDBACK[c.name] for c in checks if c.passed is False]
    return GuidanceResponse(
        ready=all(c.passed for c in checks),
        checks=checks, feedback=feedback,
        elapsed_ms=int((time.time() - t0) * 1000),
    )


@app.post("/batch", response_model=BatchResponse)
def batch(files: List[UploadFile] = File(..., media_type="multipart/form-data")):
    """Score a capture batch, select the best set, and run the set level gate."""
    t0 = time.time()
    if not files:
        raise HTTPException(400, "No files received.")
    if len(files) > 24:
        raise HTTPException(413, "Too many images. Send 24 or fewer.")

    payload = [(_read_upload(f), f.filename or f"image_{i}")
               for i, f in enumerate(files)]
    result = process_batch(payload)

    index_of = {id(d): i for i, d in enumerate(result.all_decisions)}
    selected = [
        BatchImageResult(index=index_of.get(id(d), -1),
                         fqs=round(d.fqs, 3), role=d.role, passed=d.passed)
        for d in result.selected
    ]
    role_sets = {
        role: [getattr(d, "path", "") for d in items]
        for role, items in result.role_sets.items()
    }
    return BatchResponse(
        certified=result.certified, selected=selected, role_sets=role_sets,
        recapture=result.recapture, elapsed_ms=int((time.time() - t0) * 1000),
    )

# ---------------------------------------------------------------------------
# Test page
# ---------------------------------------------------------------------------
_TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>PQF test</title>
<style>
 body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#f5f7fa;color:#1f2430}
 .wrap{max-width:860px;margin:0 auto;padding:28px 20px 60px}
 h1{color:#1F3A63;margin:0 0 4px;font-size:24px}
 p.sub{color:#5a6472;margin:0 0 26px}
 .card{background:#fff;border:1px solid #dfe4ec;border-radius:12px;padding:20px;margin-bottom:18px}
 h2{font-size:17px;margin:0 0 6px;color:#2E5090}
 .hint{color:#6b7482;font-size:13.5px;margin:0 0 14px}
 input[type=file]{display:block;margin:10px 0 14px;width:100%}
 button{background:#1F3A63;color:#fff;border:0;border-radius:8px;padding:11px 20px;font-size:15px;cursor:pointer}
 button:disabled{background:#9aa4b3;cursor:default}
 pre{background:#0f1720;color:#d7e2f0;padding:14px;border-radius:8px;overflow:auto;font-size:12.5px;max-height:420px}
 .verdict{padding:12px 14px;border-radius:8px;margin:12px 0;font-weight:600}
 .ok{background:#EAF4EC;color:#1B5E20;border:1px solid #2E7D32}
 .no{background:#FFF6E5;color:#7a5600;border:1px solid #B8860B}
 .roles{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
 .role{background:#eef3fa;border:1px solid #cdd9ea;border-radius:8px;padding:8px 12px;font-size:13.5px}
</style></head><body><div class="wrap">
<h1>PQF test page</h1>
<p class="sub">Swagger cannot render a multi file picker for this API, so use this instead.</p>

<div class="card">
  <h2>Single image</h2>
  <p class="hint">Full framework evaluation. Costs one semantic model call.</p>
  <input type="file" id="one" accept="image/*">
  <button onclick="score()">Score this image</button>
  <div id="oneOut"></div>
</div>

<div class="card">
  <h2>Guidance only</h2>
  <p class="hint">The fast pre capture check. No semantic call, so this is free.</p>
  <input type="file" id="g" accept="image/*">
  <button onclick="guide()">Check</button>
  <div id="gOut"></div>
</div>

<div class="card">
  <h2>Batch, the quality gate</h2>
  <p class="hint">Select several images at once, hold Ctrl or Shift in the picker.
  Each image costs one semantic call. Try four varied shots, then four near
  identical close ups to see the gate fail.</p>
  <input type="file" id="many" accept="image/*" multiple>
  <button onclick="batch()">Score the set</button>
  <div id="manyOut"></div>
</div>
</div>
<script>
async function post(url, form, outId, render){
  const el = document.getElementById(outId);
  el.innerHTML = '<p class="hint">Working...</p>';
  try{
    const r = await fetch(url, {method:'POST', body:form});
    const j = await r.json();
    el.innerHTML = (render ? render(j) : '') + '<pre>'+JSON.stringify(j,null,2)+'</pre>';
  }catch(e){ el.innerHTML = '<pre>'+e+'</pre>'; }
}
function score(){
  const f=document.getElementById('one').files[0]; if(!f) return;
  const fd=new FormData(); fd.append('file',f);
  post('/score',fd,'oneOut', j=>{
    const cls = j.passed ? 'ok':'no';
    return `<div class="verdict ${cls}">FQS ${j.fqs} &middot; role ${j.role} &middot; ${j.passed?'passed':'not passed'}</div>`;
  });
}
function guide(){
  const f=document.getElementById('g').files[0]; if(!f) return;
  const fd=new FormData(); fd.append('file',f);
  post('/guidance',fd,'gOut', j=>{
    const cls = j.ready ? 'ok':'no';
    const fb = j.feedback.length ? ' &middot; '+j.feedback[0] : '';
    return `<div class="verdict ${cls}">${j.ready?'Ready':'Not ready'}${fb}</div>`;
  });
}
function batch(){
  const fs=document.getElementById('many').files; if(!fs.length) return;
  const fd=new FormData(); for(const f of fs) fd.append('files',f);
  post('/batch',fd,'manyOut', j=>{
    const cls = j.certified ? 'ok':'no';
    let head = j.certified ? 'Set certified' :
      ('Not certified &middot; ' + (j.recapture?.instruction || ''));
    let roles = '';
    if(j.role_sets){
      const bits = Object.entries(j.role_sets)
        .filter(([k,v])=>v.length)
        .map(([k,v])=>`<div class="role"><b>${k}</b><br>${v.length} image(s)</div>`);
      if(bits.length) roles = '<div class="roles">'+bits.join('')+'</div>';
    }
    return `<div class="verdict ${cls}">${head}</div>`+roles;
  });
}
</script></body></html>"""


@app.get("/test", response_class=HTMLResponse)
def test_page():
    """A small page for exercising the endpoints, including multi file upload.

    Swagger UI renders an OpenAPI 3.1 binary array as a text field rather than a
    file picker, so the batch endpoint cannot be tested from /docs. This page
    provides a working multi file picker and shows the verdict clearly.
    """
    return _TEST_PAGE
