# Real-Time Photography Quality Framework (PQF)

Final-year research project (BSc Hons Computing, NIBM / Coventry, 2024.2).
Design Science Research — the single artefact is the **Photography Quality
Framework (PQF)**, a validated, machine-evaluable quality standard for
catalog-style product photography.

Student: D J A M O Nayanaransi · COBSCCOMP24.2P-074
Supervisor: Mr. Niranga Dharmaratna

## Repository layout
```
backend/    Python — the PQF framework (contribution) + FastAPI server
  pqf/        config.py + technical (T0–T5) / semantic (S1–S5) / combination / gate
  api/        server the mobile app calls
  tests/      unit tests per criterion
research/   Validation — dataset tooling + O1–O4 evaluation scripts + results
mobile/     Flutter guided-capture app (Objective 2)
data/        Dataset (git-ignored: images, splits stay local)
docs/        Specification, methodology, decisions, project files, proposal
scripts/    One-off helpers
```

## The framework in one line
An image is standardised → gated (T0) → scored by the technical engine
(T1–T5 → TQS) and the semantic evaluator (S1–S5 → SQS) → combined
(FQS = α·TQS + β·SQS) → classified into a role or rejected → sets checked
by the quality gate.

## Status
Objectives frozen. Spec v1.1 frozen (docs/). Dataset scoped to two
categories (fashion accessories, cosmetics/care). Build in progress.

## Key documents
- `docs/PQF_Specification_v1.1.docx` — the formal framework definition
- `docs/methodology.md` — the research methodology (argument, not workflow)
- `docs/decisions.md` — every design decision with its rationale
- `docs/project.md` — current state (the warm-start brain)
- `docs/sources.md` — claims-to-verify ledger

## Running the backend (once code is in place)
```
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pqf.config          # sanity-check weights sum to 1.0
```
