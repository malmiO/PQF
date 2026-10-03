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

    @property
    def path_name(self) -> str:
        return self.filename


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
    return base / "assets" / "music"


def load_library(base: Path) -> list:
    """Reads the track library from a manifest.

    The manifest exists so every track carries its licence attribution, which
    must be recorded rather than assumed.
    """
    import csv

    manifest = library_dir(base) / "tracks.csv"
    if not manifest.exists():
        return []

    tracks = []
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("filename"):
                continue
            tracks.append(Track(
                id=row.get("id", row["filename"]),
                title=row.get("title", row["filename"]),
                mood=row.get("mood", "upbeat").strip().lower(),
                filename=row["filename"],
                attribution=row.get("attribution", ""),
            ))
    return tracks


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

    all_tracks = load_library(base)
    preferred = [t for t in all_tracks if t.mood == mood]
    others = [t for t in all_tracks if t.mood != mood]

    return MoodRecommendation(
        mood=mood,
        reason=reason,
        tracks=preferred + others,
    )


def resolve_track(track_id: str, base: Path) -> Path | None:
    """Finds the audio file for a chosen track, or None if it is unknown."""
    for t in load_library(base):
        if t.id == track_id:
            p = library_dir(base) / t.filename
            return p if p.exists() else None
    return None
