# Mobile — Flutter guided-capture app (Objective 2)

Scaffold only at this stage. Structure:
- `lib/screens/`  — capture screen, results/selection screen
- `lib/services/` — API client (calls the backend), on-device live checks
                    (lightweight: sharpness, exposure, framing only)
- `lib/widgets/`  — live guidance overlays
- `lib/models/`   — data classes (score objects, gate results)

The heavy criteria (BRISQUE, PIQE, LLM) run server-side; only lightweight
real-time checks run on-device. See docs/PQF_Specification_v1.1.docx.
