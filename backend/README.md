# Backend — the PQF framework + API

## Structure
- `pqf/config.py` — ALL thresholds and weights (spec v1.1). Single source of truth.
- `pqf/technical/` — T0 gate + T1–T5 metrics → TQS (deterministic, offline).
- `pqf/semantic/` — S1–S5 via Gemini Flash → SQS (temperature 0, versioned prompt).
- `pqf/combination/` — MCDM: FQS = α·TQS + β·SQS.
- `pqf/gate/` — role classification + set-level quality gate.
- `api/` — FastAPI server exposing scoring endpoints to the mobile app.
- `tests/` — one test module per criterion.

## Setup
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp api/secrets.example.py api/secrets.py   # then add your Gemini API key
python -m pqf.config                        # verify weights sum to 1.0
```

## Design rules
- No magic numbers outside config.py.
- The semantic model version string is PINNED in config (determinism).
- Thresholds are calibrated on the CALIBRATION split only — never the holdout.
