# Music library

The video uses only tracks listed in `tracks.csv` and only their loudness
normalised copies. A person downloads each track and accepts its licence; the
code only checks that what was recorded is complete and allowed.

## Add a track

1. Download it from a source whose licence is **CC0**, **CC-BY-4.0** or **Pixabay**
   (never NC or ND). Keep the page URL.
2. Put the file in `backend/assets/music/`.
3. Add one row to `tracks.csv`:

   | column | example |
   |---|---|
   | track_id | `calm_morning` (unique) |
   | mood | `calm`, `elegant` or `upbeat` |
   | title, artist | as on the source page |
   | source_url | the track's page |
   | licence | `CC0`, `CC-BY-4.0` or `Pixabay` |
   | licence_url | the licence text's URL |
   | downloaded_on | `2026-10-07` |
   | attribution | required for CC-BY-4.0 (the credit text) |
   | file | `calm_morning.mp3` |
   | duration_s | at least 16 |
   | bpm | the tempo; the track closest to the mood's pace is used (calm 75, elegant 92, upbeat 120) |

4. Run, from the repo root:

   ```
   python scripts/normalise_tracks.py
   python scripts/check_tracks.py
   ```

   `check_tracks.py` must print **READY**. The Railway build runs it too.

## Before the evaluation

Delete the two `TEST` rows from `tracks.csv` and the files
`backend/assets/music/test_*.mp3` and `backend/assets/music/normalised/test_*.mp3`.
`/health` then reports `"test_tones": false`.

CC BY tracks are credited automatically at the end of the post caption
("Music: title by artist, CC BY 4.0, url"), and in caption.txt and results.json.
