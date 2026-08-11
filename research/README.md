# Research — validation and evidence

Separate from `backend/` on purpose: backend is the *artefact*, research is
the *evidence that it works* (the DSR knowledge claim).

- `dataset_tools/` — build and freeze the validation dataset:
    - `abo_select.py`      sample/fetch ABO good images
    - `abo_rebuild.py`     rebuild the manifest from folder contents
    - `narrow_categories.py`  chop ABO to the two chosen categories
    - `build_dataset.py`   assemble ABO + phone, one-time stratified split
- `evaluation/` — objective evaluation scripts:
    - O1: Cohen's κ vs. rater consensus; per-criterion detection; SRCC vs. SPAQ/KonIQ
    - O2: guided-vs-unguided paired test + blind preference
    - O3: top-3 selection overlap + weight sensitivity
    - O4: usability (SUS) summary
- `results/` — generated tables and figures.

## Dataset build order
1. `narrow_categories.py`   (chop ABO to 2 categories)
2. place phone captures under `data/phone/validation/<category>/`
3. `build_dataset.py --assemble`   (merge + manifest + violation check)
4. `build_dataset.py --split`      (ONE-TIME freeze — refuses to re-run)
