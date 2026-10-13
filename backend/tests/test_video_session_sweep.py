"""The 3-hour video-session deletion is enforced by a background sweep, not only
lazily on the next /video request. These tests exercise the sweep directly and
prove a stale session is removed with NO /video call."""
import asyncio
import os
import time
from pathlib import Path

from backend.api import video_api


def _make_session(root: Path, name: str, age_hours: float) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "plan.json").write_text("{}", encoding="utf-8")
    t = time.time() - age_hours * 3600
    os.utime(d, (t, t))  # set the DIRECTORY mtime, which _cleanup inspects
    return d


def test_sweep_deletes_session_older_than_keep_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(video_api, "SESSIONS", tmp_path)
    old = _make_session(tmp_path, "a" * 32, video_api.KEEP_HOURS + 1)
    fresh = _make_session(tmp_path, "b" * 32, 0.1)

    async def run():
        # start_session_sweeper() runs _cleanup() once immediately, then starts
        # the periodic task. No /video request is made.
        task = video_api.start_session_sweeper()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    assert not old.exists(), "a session older than KEEP_HOURS must be swept away"
    assert fresh.exists(), "a fresh session must be kept"


def test_keep_hours_unchanged():
    # Guard: the retention promise is exactly 3 hours.
    assert video_api.KEEP_HOURS == 3
    assert video_api.SWEEP_INTERVAL_SECONDS == 600
