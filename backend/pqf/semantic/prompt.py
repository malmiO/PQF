"""
Versioned semantic-evaluation prompt (pqf-sem-v1).

The prompt is version-controlled deliberately: the semantic score depends on the
exact wording, so the version string (config.PROMPT_VERSION) is recorded with
every result for reproducibility. Changing the prompt = bump the version.

The model returns STRICT JSON: five 0-1 scores + a short justification + a role.
Scores are marketing-suitability judgements a numerical IQA metric cannot make.
"""
from __future__ import annotations

# Each criterion: (key, human description shown to the model)
SEMANTIC_CRITERIA = [
    ("subject_centering",
     "Is the product well-composed and well-centred in the frame, not cut off or awkwardly placed?"),
    ("feature_visibility",
     "Are the product's key features, details, label text, and texture clearly visible?"),
    ("marketing_suitability",
     "Does the image look professional and suitable for social-media marketing of this product?"),
    ("angle_value",
     "Does the camera angle show useful information about the product (e.g. a meaningful view), beyond a flat generic shot?"),
    ("lighting_style_quality",
     "Is the lighting and overall visual style good for presenting this product attractively?"),
]

ROLE_OPTIONS = ["hero_shot", "angle_shot", "detail_shot", "reject"]


def build_prompt() -> str:
    """Return the full instruction text for the semantic evaluator."""
    criteria_lines = "\n".join(
        f'  - "{key}": {desc}' for key, desc in SEMANTIC_CRITERIA
    )
    keys = ", ".join(f'"{k}"' for k, _ in SEMANTIC_CRITERIA)
    return f"""You are an expert product-marketing photographer evaluating a single \
product photograph for suitability in social-media marketing.

Judge the image ONLY on the following five criteria. For each, give a score from \
0.0 (poor) to 1.0 (excellent):
{criteria_lines}

Then classify the image's role as exactly one of: {", ".join(ROLE_OPTIONS)}.
  - hero_shot: a strong main marketing image
  - angle_shot: a useful secondary angle
  - detail_shot: a close-up showing detail/texture
  - reject: not usable for marketing

Respond with STRICT JSON only, no markdown, no prose outside the JSON, in exactly \
this shape:
{{
  "scores": {{ {keys} }},
  "role": "one of {ROLE_OPTIONS}",
  "justification": "one short sentence explaining the overall judgement"
}}

Each score must be a number between 0.0 and 1.0. Do not include any text outside \
the JSON object."""
