"""
Video generation (Layer 3).

Assembles certified images into a short, platform ready marketing video.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not generate or synthesise video content. Every frame shown is derived
from a photograph the framework actually certified. Passing certified images to
a generative video model would break the chain between what was certified and
what the customer sees, which would make the quality guarantee meaningless at
the final step, and would risk misrepresenting the product.

WHERE THE ENGAGEMENT COMES FROM
-------------------------------
From the images and their order, not from effects. The main shot leads because
it is what a customer sees first. Angles follow because they answer the question
a customer would ask next. The detail shot comes late because texture is what
convinces someone the quality is real. That ordering is decided by the
framework's role classifier, so the structure of the video is a direct
consequence of the standard.

Subtle motion, a slow zoom across each still, keeps the eye moving without
inventing anything that was not photographed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Role order in the finished video. Not alphabetical, and not capture order.
# This is the sequence in which a buyer wants the questions answered.
ROLE_ORDER = ["hero_shot", "angle_shot", "detail_shot"]

# Output formats. Square suits feed posts, vertical suits stories and reels.
FORMATS = {
    "square": (1080, 1080),
    "vertical": (1080, 1920),
}

SECONDS_PER_IMAGE = 2.6
CROSSFADE_SECONDS = 0.5
FPS = 30


@dataclass
class VideoResult:
    path: Path
    duration_seconds: float
    image_count: int
    format_name: str
    has_audio: bool


def ffmpeg_binary() -> str | None:
    """Resolve the ffmpeg executable independent of the shell PATH.

    Order: the PQF_FFMPEG environment variable (an absolute path), then PATH,
    then the known Windows winget install locations. A server launched from a
    shell that was opened BEFORE ffmpeg was installed does not have it on PATH,
    so relying on PATH alone reported video as unavailable even though ffmpeg
    was installed (found 2026-10-05). Returns None if ffmpeg cannot be found.
    """
    import os
    import glob

    env = os.environ.get("PQF_FFMPEG")
    if env and os.path.isfile(env):
        return env

    found = shutil.which("ffmpeg")
    if found:
        return found

    # Windows: winget installs ffmpeg under LOCALAPPDATA. Prefer the real
    # executable in Packages over the Links shim, which is an execution alias a
    # subprocess may not be able to run.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for pattern in (
            os.path.join(local, "Microsoft", "WinGet", "Packages",
                         "*FFmpeg*", "**", "bin", "ffmpeg.exe"),
            os.path.join(local, "Microsoft", "WinGet", "Packages",
                         "*FFmpeg*", "**", "ffmpeg.exe"),
            os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        ):
            hits = glob.glob(pattern, recursive=True)
            if hits:
                return hits[0]
    return None


def ffmpeg_available() -> bool:
    return ffmpeg_binary() is not None


def order_by_role(decisions: list) -> list:
    """Order images for the video.

    Within a role, higher scoring images come first, so the strongest example of
    each view is the one shown.
    """
    ordered = []
    for role in ROLE_ORDER:
        matching = [d for d in decisions if getattr(d, "role", None) == role
                    and getattr(d, "passed", False)]
        matching.sort(key=lambda d: getattr(d, "fqs", 0.0), reverse=True)
        ordered.extend(matching)
    return ordered


def background_colour(image_path) -> str:
    """The photograph's own background colour, as 0xRRGGBB for ffmpeg.

    Estimated as the median of the border band, the same estimate the framework
    uses to find the product. Padding with it makes the bars invisible on any
    plain background; padding with pure white showed visible bands on the light
    grey background of a budget lightbox (2026-10-05). Falls back to white.
    """
    import cv2
    import numpy as np
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return "white"
    h, w = img.shape[:2]
    b = max(2, int(min(h, w) * 0.05))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                             img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bgr = np.median(border, axis=0).astype(int)
    return "0x%02X%02X%02X" % (bgr[2], bgr[1], bgr[0])


def _pad_filter(w: int, h: int, colour: str = "white") -> str:
    """Scale to fit, then pad to the exact frame in the photo's background colour.

    Preserving aspect ratio matters. Stretching a product photograph to fill a
    frame distorts the product, which is precisely the kind of misrepresentation
    the framework exists to prevent.
    """
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:{colour}"
    )


def _ken_burns(w: int, h: int, frames: int, zoom_in: bool) -> str:
    """A slow zoom across a still image.

    Alternating direction between shots stops the sequence feeling mechanical.
    The zoom is deliberately small, since a strong push crops detail out of
    frame, and detail is the thing a detail shot exists to show.
    """
    if zoom_in:
        expr = f"zoom='min(zoom+0.0009,1.10)'"
    else:
        expr = f"zoom='if(lte(zoom,1.0),1.10,max(1.001,zoom-0.0009))'"
    return (
        f"zoompan={expr}:d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}"
    )


def build_video(
    image_paths: list[Path],
    out_path: Path,
    format_name: str = "square",
    audio_path: Path | None = None,
    motion: bool = True,
) -> VideoResult:
    """Assemble images into a video.

    Raises RuntimeError with the ffmpeg output on failure, so a caller can
    report something specific rather than a generic failure.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed on the server.")
    if not image_paths:
        raise RuntimeError("No images to assemble.")

    w, h = FORMATS.get(format_name, FORMATS["square"])
    per_frames = int(SECONDS_PER_IMAGE * FPS)

    cmd: list[str] = [ffmpeg_binary() or "ffmpeg", "-y", "-loglevel", "error"]
    for p in image_paths:
        if motion:
            # A SINGLE frame is fed in, and zoompan produces the whole duration
            # from it. Looping the input as well would multiply the two, since
            # zoompan emits its frame count for every frame it receives, which
            # turned a nine second video into nearly three minutes.
            cmd += ["-i", str(p)]
        else:
            cmd += ["-loop", "1", "-t", str(SECONDS_PER_IMAGE), "-i", str(p)]
    if audio_path is not None:
        cmd += ["-i", str(audio_path)]

    # Per image chain, then crossfade the results together.
    parts = []
    for i in range(len(image_paths)):
        chain = _pad_filter(w, h, background_colour(image_paths[i]))
        if motion:
            chain += "," + _ken_burns(w, h, per_frames, zoom_in=(i % 2 == 0))
        chain += f",setsar=1,fps={FPS}"
        parts.append(f"[{i}:v]{chain}[v{i}]")

    if len(image_paths) == 1:
        parts.append("[v0]null[vout]")
    else:
        prev = "v0"
        offset = SECONDS_PER_IMAGE - CROSSFADE_SECONDS
        for i in range(1, len(image_paths)):
            out = "vout" if i == len(image_paths) - 1 else f"x{i}"
            parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:"
                f"duration={CROSSFADE_SECONDS}:offset={offset:.2f}[{out}]"
            )
            prev = out
            offset += SECONDS_PER_IMAGE - CROSSFADE_SECONDS

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]"]

    n_img = len(image_paths)
    total = n_img * SECONDS_PER_IMAGE - (n_img - 1) * CROSSFADE_SECONDS
    if audio_path is not None:
        # Fade the music out over the last second rather than cutting it off.
        fade_start = max(0.0, total - 1.0)
        cmd += ["-map", f"{len(image_paths)}:a", "-shortest",
                "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_start:.2f}:d=1",
                "-c:a", "aac", "-b:a", "128k"]

    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",      # required for playback on most devices
        "-preset", "veryfast",
        "-movflags", "+faststart",  # lets playback start before full download
        str(out_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"Video assembly failed. {proc.stderr[-800:]}")

    n = len(image_paths)
    duration = n * SECONDS_PER_IMAGE - (n - 1) * CROSSFADE_SECONDS
    return VideoResult(
        path=out_path,
        duration_seconds=round(duration, 1),
        image_count=n,
        format_name=format_name,
        has_audio=audio_path is not None,
    )
