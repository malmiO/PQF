"""
settings.py  -  constants of the AUDIO layer (v1.1.0, 2026-10-06).

Nothing here touches the framework. These govern which music may be offered and
how it is prepared.
"""

# Licences a track may carry. Anything else (and anything NonCommercial or
# NoDerivatives) is refused, because the owner posts the video commercially.
ALLOWED_LICENCES = ("CC0", "CC-BY-4.0", "Pixabay")
FORBIDDEN_LICENCE_PARTS = ("NC", "ND")

# The longest video is 15 s; a track must cover it with room for the fades.
MIN_TRACK_SECONDS = 16.0

# Loudness every track is normalised to once (EBU R128 integrated loudness), the
# level the main platforms normalise short videos to. Design prior, not a
# research finding.
TARGET_LUFS = -14.0
TRUE_PEAK_DB = -1.5
LOUDNESS_RANGE = 11.0

# The moods the app offers; each must have at least one track.
APP_MOODS = ("calm", "elegant", "upbeat")

# The pace each mood is aimed at, in beats per minute: the track with the closest
# bpm is used. Calm slower, upbeat faster. Design prior, not a research finding.
MOOD_BPM = {"calm": 75.0, "elegant": 92.0, "upbeat": 120.0}

# Paths, relative to the repo root.
MANIFEST = "backend/audio/tracks.csv"
FILES_DIR = "backend/assets/music"
NORMALISED_DIR = "backend/assets/music/normalised"

# Rows whose licence is this are generated test tones, never music.
TEST_LICENCE = "TEST"
