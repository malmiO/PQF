"""gemini_probe.py - one real Gemini call, to tell WHY semantic scoring fails.

Reads GEMINI_API_KEY exactly as the server does (python-dotenv load_dotenv()
on the repo-root .env, then os.environ) and uses the pinned model
(backend.pqf.config.GEMINI_MODEL). It makes ONE generate_content call on a tiny
generated image and prints only:

  - model id
  - HTTP status (or the exception class)
  - a reason code: API_KEY_INVALID / PERMISSION_DENIED / RESOURCE_EXHAUSTED /
    NOT_FOUND / INVALID_ARGUMENT / UNAUTHENTICATED / other
  - latency in ms

It NEVER prints the API key and redacts it from any error text, just in case.

Run (pinned venv, from the repo root):
    .venv/Scripts/python.exe research/tools/gemini_probe.py
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

# Same env loading as the server: repo-root .env via python-dotenv.
from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv()  # also honour an already-exported environment / Railway variables

from backend.pqf import config  # noqa: E402

_REASONS = ("API_KEY_INVALID", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
            "NOT_FOUND", "INVALID_ARGUMENT", "UNAUTHENTICATED", "UNAVAILABLE",
            "DEADLINE_EXCEEDED")


def _tiny_jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def _reason(text: str) -> str:
    up = text.upper()
    for code in _REASONS:
        if code in up:
            return code
    return "other"


def _redact(text: str, key: str | None) -> str:
    if key and key in text:
        text = text.replace(key, "<redacted>")
    return text


def _report_retry_and_thinking(types) -> None:
    """(a) and (b): what the SDK does for retries and thinking, so the raw
    first-attempt latency is interpreted correctly."""
    import google.genai as _g
    print("google-genai version:", getattr(_g, "__version__", "?"))
    has_retry = hasattr(types, "HttpRetryOptions")
    if has_retry:
        print("SDK retry options: HttpRetryOptions present "
              "(inspect its defaults for attempts/backoff)")
    else:
        # google-genai 1.0.0: no retry-options type is exposed, so there is no
        # SDK-level automatic content retry to turn off. The measured latency is
        # therefore the RAW first-attempt latency already.
        print("SDK retry options: none exposed (no HttpRetryOptions in this "
              "google-genai) -> automatic content retries: 0, no backoff")
    # (b) Thinking: we never set thinking_config in our calls.
    tc = getattr(types, "ThinkingConfig", None)
    tfields = list(getattr(tc, "model_fields", {}).keys()) if tc else []
    print("thinking_config set by our calls: no")
    print("ThinkingConfig fields available:", tfields,
          "(no thinking-budget knob)" if "thinking_budget" not in tfields
          else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="One Gemini call, for diagnosis.")
    ap.add_argument("--no-retry", action="store_true",
                    help="Show raw first-attempt latency/status (no SDK retry "
                         "to disable in this SDK) and set an explicit timeout.")
    ap.add_argument("--timeout-ms", type=int, default=120000,
                    help="HttpOptions.timeout in ms for --no-retry (default 120000).")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    print("GEMINI_API_KEY present:", bool(key))
    print("model id:", config.GEMINI_MODEL)
    if not key:
        print("result: NO_KEY (set GEMINI_API_KEY in .env locally, or the "
              "Railway service variable, then redeploy)")
        return 2

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        print("google-genai not installed:", _redact(str(e), key))
        print("result: SDK_MISSING")
        return 3

    # (c) request image size.
    img = _tiny_jpeg()
    print("request image size KB:", round(len(img) / 1024, 2))

    http_options = None
    if args.no_retry:
        _report_retry_and_thinking(types)
        http_options = types.HttpOptions(timeout=args.timeout_ms)  # ms
        print(f"explicit HttpOptions.timeout: {args.timeout_ms} ms")

    client = genai.Client(api_key=key,
                          http_options=http_options) if http_options \
        else genai.Client(api_key=key)
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=["Reply with the single word OK.",
                      types.Part.from_bytes(data=img,
                                            mime_type="image/jpeg")],
            config=types.GenerateContentConfig(
                temperature=config.GEMINI_TEMPERATURE),
        )
        ms = round((time.time() - t0) * 1000)
        print("HTTP status: 200 OK")
        print("model_version:", getattr(resp, "model_version", None))
        print("latency_ms:", ms)
        snippet = (resp.text or "")[:40].replace("\n", " ")
        print("reply_snippet:", repr(snippet))
        print("result: SUCCESS")
        return 0
    except Exception as e:  # noqa: BLE001 - we want the reason, whatever it is
        ms = round((time.time() - t0) * 1000)
        msg = _redact(str(e), key)
        status = getattr(e, "code", None) or getattr(e, "status_code", None)
        print("exception class:", type(e).__name__)
        print("http status:", status)
        print("reason:", _reason(msg))
        print("latency_ms:", ms)
        print("detail:", msg[:300])
        print("result: FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
