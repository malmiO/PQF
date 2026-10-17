"""
model_check.py - which Gemini model actually answers for config.GEMINI_MODEL?

Run from the REPO ROOT (in the pinned .venv-eval):
    python tools/model_check.py

Makes ONE tiny text-only call with config.GEMINI_MODEL, prints the version that
answered (resp.model_version), then lists the model names containing "flash-lite"
that the key can see. Used to choose the fixed model name to pin for evaluation
v1.4.0. GEMINI_API_KEY is read from .env and is never printed.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.getcwd())

from backend.pqf import config  # noqa: E402


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set (put it in .env). Nothing was called.")
        return 1
    try:
        from google import genai
    except ImportError:
        print("google-genai not installed in this environment.")
        return 1

    client = genai.Client(api_key=key)
    print(f"config.GEMINI_MODEL = {config.GEMINI_MODEL}")

    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents="Reply with the single word: ok",
        )
        print(f"resp.model_version  = {getattr(resp, 'model_version', None)}")
        print(f"reply               = {(resp.text or '').strip()[:40]!r}")
    except Exception as e:  # quota / permission / model-not-found
        print(f"call failed: {type(e).__name__}: {e}")
        return 2

    print('\nModels containing "flash-lite" visible to this key:')
    found = 0
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            if "flash-lite" in name.lower():
                actions = getattr(m, "supported_actions", None)
                callable_ = "generateContent" in (actions or [])
                print(f"  {name}   generateContent={callable_}")
                found += 1
    except Exception as e:
        print(f"  list failed: {type(e).__name__}: {e}")
        return 3
    if not found:
        print("  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
