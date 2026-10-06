"""
Audio recommendation for the marketing video.

THE DESIGN POSITION, AND WHY
----------------------------
The framework RECOMMENDS a mood and offers a short list of tracks. The owner
chooses. It does not select music automatically.

Two reasons, both recorded in the specification.

First, an automatically decided "correct" track is a subjective judgement with no
ground truth to validate against. It is the same class of problem as verifying
true colour without a reference card. A claim of optimal music selection could
not be evaluated, so it is not made.

Second, attaching arbitrary music to content a seller will publish raises
licensing exposure. Recommending from a cleared library and requiring the owner
to confirm removes that.

Keeping the human in the loop is also consistent with how the rest of the
framework behaves. It guides and recommends against a standard, and the person
decides.

WHAT THE RECOMMENDATION IS BASED ON
-----------------------------------
The product category and the audience the seller states. The mapping below is a
declared design prior drawn from the practitioner observation that audio matched
to a product's audience performs better than audio chosen for reach alone. It is
cited as motivation, not as measured performance of this framework, and the
claim made is that the audio is audience appropriate, never that it is optimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Track:
    id: str
    title: str
    mood: str
    filename: str
    attribution: str
    artist: str = ""
    licence: str = ""
    source_url: str = ""
    bpm: float | None = None

    @property
    def path_name(self) -> str:
        return self.filename

    @property
    def is_test_tone(self) -> bool:
        from ..audio.settings import TEST_LICENCE
        return self.licence == TEST_LICENCE


@dataclass
class MoodRecommendation:
    mood: str
    reason: str
    tracks: list


# Mood categories. Deliberately few. A seller choosing between fifteen moods is
# being given a task, not a recommendation.
MOODS = {
    "calm": "Slow and gentle. Suits products bought thoughtfully, where the "
            "feeling is care and quality rather than excitement.",
    "upbeat": "Bright and energetic. Suits everyday products and impulse "
              "purchases, where the feeling is fun and immediacy.",
    "elegant": "Restrained and refined. Suits premium or gift items, where the "
               "feeling is craftsmanship and occasion.",
}

# Category to mood. A declared prior, not an empirical finding.
CATEGORY_MOOD = {
    "cosmetics": ("calm", "Personal care is usually bought thoughtfully, so a "
                           "calm track suits the decision being made."),
    "skincare": ("calm", "Skincare buyers respond to a sense of care and "
                          "gentleness rather than urgency."),
    "jewellery": ("elegant", "Jewellery is often a gift or an occasion "
                             "purchase, so a refined track fits the moment."),
    "accessories": ("elegant", "Accessories are chosen for style, so a refined "
                               "track matches what the buyer is looking for."),
    "clothing": ("upbeat", "Clothing browsing is quick and visual, so an "
                            "energetic track keeps attention."),
    "food": ("upbeat", "Food and snacks are impulse purchases, so a bright "
                       "track suits the mood."),
    "handmade": ("calm", "Handmade items sell on craftsmanship, which a gentle "
                          "track supports better than an energetic one."),
}

DEFAULT_MOOD = ("upbeat", "A bright track suits most social media product "
                          "videos when the category is unclear.")


def library_dir(base: Path) -> Path:
    """Where the original audio files are (backend/assets/music)."""
    from ..audio.settings import FILES_DIR
    return base / FILES_DIR


def playable_path(track: "Track", base: Path) -> Path:
    """The loudness normalised copy, the ONLY file the renderer and the preview
    use (v1.1.0). Made once by scripts/normalise_tracks.py."""
    from ..audio.settings import NORMALISED_DIR
    return base / NORMALISED_DIR / track.filename


def load_library(base: Path) -> list:
    """Reads the track library from the manifest (backend/audio/tracks.csv).

    The manifest exists so every track carries its licence and attribution,
    which must be recorded rather than assumed (checked by scripts/check_tracks.py).
    """
    from ..audio.catalog import read_rows

    tracks = []
    for row in read_rows(base):
        if not row.get("file"):
            continue
        try:
            bpm = float(row["bpm"]) if row.get("bpm") else None
        except ValueError:
            bpm = None
        tracks.append(Track(
            id=row.get("track_id") or row["file"],
            title=row.get("title") or row["file"],
            mood=(row.get("mood") or "upbeat").lower(),
            filename=row["file"],
            attribution=row.get("attribution", ""),
            artist=row.get("artist", ""),
            licence=row.get("licence", ""),
            source_url=row.get("source_url", ""),
            bpm=bpm,
        ))
    return tracks


def _pace_order(tracks: list, mood: str) -> list:
    """Tracks of a mood, the one whose bpm is closest to the mood's pace first
    (calm slower, upbeat faster). Tracks without a bpm come last."""
    from ..audio.settings import MOOD_BPM
    target = MOOD_BPM.get(mood)
    return sorted(tracks, key=lambda t: (t.bpm is None or target is None,
                                         abs((t.bpm or 0) - (target or 0))))


def recommend(category: str | None, base: Path) -> MoodRecommendation:
    """Recommend a mood and the tracks available in it.

    Tracks from other moods are still offered afterwards, because the
    recommendation is advice rather than a restriction. A seller who knows their
    audience better than the mapping does should not be prevented from acting on
    that.
    """
    key = (category or "").strip().lower()
    mood, reason = DEFAULT_MOOD
    for cat, (m, r) in CATEGORY_MOOD.items():
        if cat in key:
            mood, reason = m, r
            break

    # Only offer tracks whose normalised audio file is actually present. Offering
    # a track that cannot be played produced a silent video with no error
    # (2026-10-05). Within each mood, the closest bpm comes first (v1.1.0).
    all_tracks = [t for t in load_library(base) if playable_path(t, base).exists()]
    preferred = _pace_order([t for t in all_tracks if t.mood == mood], mood)
    others = [t for m in MOODS if m != mood
              for t in _pace_order([t for t in all_tracks if t.mood == m], m)]

    return MoodRecommendation(
        mood=mood,
        reason=reason,
        tracks=preferred + others,
    )


def resolve_track(track_id: str, base: Path) -> Path | None:
    """Finds the audio file for a chosen track, or None if it is unknown."""
    for t in load_library(base):
        if t.id == track_id:
            p = playable_path(t, base)
            return p if p.exists() else None
    return None


def first_track(mood: str, base: Path):
    """The track a video of this mood uses: the closest bpm, or None."""
    return next((t for t in recommend(None, base).tracks if t.mood == mood), None)


def tracks_per_mood(base: Path) -> dict:
    """{mood: number of playable tracks}, for /health."""
    tracks = recommend(None, base).tracks
    return {m: sum(1 for t in tracks if t.mood == m) for m in MOODS}
