# PQF – Photography Quality Framework

PQF helps small and medium scale business owners to take better product photos with a phone. The mobile app (**Éclat**) guides the user through a short shot plan, checks each frame live, and scores the finished set against a quality framework.

Project website: https://malmio.github.io/PQF/

## How it works

1. **Add a product** and start the guided camera.
2. **Take the shots**: Main, Angle 1, Angle 2, Detail (plus an optional Extra).
3. **Live guidance**: small preview frames go to the backend, which returns pass/fail checks, a plain instruction, and exposure and zoom hints. Auto-capture fires once the shot holds steady.
4. **Get a score**: the full set is sent for scoring and the results screen shows what passed and what to retake.

## Project layout

| Folder | Contents |
|---|---|
| `mobile/` | Flutter app (camera, guidance overlay, results) |
| `backend/` | FastAPI service (`/guidance`, `/batch`) and the `pqf` scoring package |
| `research/` | Evaluation scripts and study data |
| `docs/` | Project website (GitHub Pages) |
