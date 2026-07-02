# FRC Vision Scouting — REBUILT (2026)

Automated scouting of FRC matches from a YouTube live stream / VOD. Watches the
broadcast, tracks all six robots, resolves identities against the published
match schedule, and emits per-robot scouting records (fuel scoring, cycles,
defense, Tower climb) — every event carrying a confidence and a timestamp so a
human can verify it.

## Status: Milestone 3 of 10 — stream ingest

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Game manual → `rubric.json` parser + validation | ✅ |
| 2 | Schedule fetch (TBA / FRC Events / Nexus) → 6 teams + stations | ✅ |
| 3 | Stream ingest → frame iterator (yt-dlp + OpenCV) | ✅ |
| 4 | FMS overlay OCR → phase / timer / score timeline | ⏳ |
| 5 | YOLO robot detection + ByteTrack tracking | ⏳ |
| 6 | Bumper OCR + track↔team assignment | ⏳ |
| 7 | Homography → field zones | ⏳ |
| 8 | Event detection (zone+overlay heuristics, VLM disambiguation) | ⏳ |
| 9 | Aggregation, reconciliation, JSON/CSV export | ⏳ |
| 10 | Live mode wrapper | ⏳ |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # milestones 1-2 need only pypdf/PyYAML/requests
pytest                          # 63 tests
cp config.example.yaml config.yaml   # fill in API keys
```

Later milestones: `pip install -e ".[vision,ocr,ingest]"` (YOLO/ultralytics,
OpenCV, PaddleOCR, yt-dlp) plus `ffmpeg` and optionally `tesseract-ocr` from
your OS package manager. GPU recommended for detection; CPU works at lower FPS.

## The rubric (`rubric.json`)

Ground truth for scoring lives in `rubric.json`, derived from the official
2026 game manual — **never hardcoded from memory**. Every downstream event
type maps to a rubric entry (enforced by `validate_rubric`).

Every rule value carries a verification status:

- `verified-manual` — extracted from the official manual by the parser.
- `needs-verification` — seeded from secondary sources (team write-ups,
  frcmanual.com, frctools.com, official field CAD); not yet confirmed.
- `missing` — no trustworthy value found; the pipeline must not emit
  points for it.

### Build / refresh the rubric

```bash
# Download the official manual and parse it:
frcscout rubric build --fetch

# Or parse a manual you already downloaded:
frcscout rubric build --manual data/2026GameManual.pdf

# Check status:
frcscout rubric validate -v
```

The build prints a report: which values were confirmed from the manual, which
patterns didn't match (those keep their seeded value and stay flagged), and
any conflicts where the manual disagreed with the seed (manual wins, conflict
is surfaced for human review).

## The schedule (identity prior)

```bash
# 6 teams + stations for a match, trying TBA -> FRC Events -> Nexus:
frcscout schedule fetch --match 2026isde1_qm14
frcscout schedule fetch --json                 # match_key from config.yaml
frcscout schedule fetch --provider nexus       # force a provider
```

Providers are tried in order; unconfigured ones are skipped and every failure
is reported if the whole chain comes up empty. Secrets can live in
`config.yaml` or the environment (`TBA_AUTH_KEY`, `FRC_EVENTS_USERNAME`,
`FRC_EVENTS_AUTH_TOKEN`, `NEXUS_API_KEY`); the file wins when both are set.
The resulting `MatchLineup` (6 slots, station-ordered, validated: 3 red +
3 blue, unique teams) is the identity prior the tracker assigns robots
against — see `src/frcscout/schedule/model.py`.

## Ingest

```bash
pip install -e ".[ingest]"                 # yt-dlp, for YouTube URLs
frcscout ingest probe <file|url|youtube-url>
frcscout ingest sample match.mp4 --fps 2 --start 300 --duration 60 --out data/samples
```

`resolve_source` turns a local file / direct media URL / YouTube page into
something OpenCV can open (yt-dlp resolves YouTube to an HLS manifest for
live, mp4 for VODs). `FrameIterator` hands downstream stages evenly spaced
frames (default 6 fps sampling; tracker interpolates between) stamped with
source frame index + video time; `--start/--duration` window a single match
out of a long event VOD. `ingest sample` doubles as the labeled-dataset
bootstrap: it dumps timestamped JPEGs for annotation.

> **Note:** the committed `rubric.json` was generated in a sandbox whose
> network policy blocks `firstfrc.blob.core.windows.net`, so all values are
> currently `needs-verification` (seeded from public secondary sources).
> Run `frcscout rubric build --fetch` on a normal connection to verify them
> against the manual; the parser's extraction patterns are unit-tested against
> manual-style fixtures in `tests/fixtures/`, and any pattern that fails
> against the real PDF text degrades honestly rather than guessing.

## Architecture (agreed plan)

Pipeline stages, each a module under `src/frcscout/`:

1. **rubric** *(this milestone)* — manual PDF/HTML → `rubric.json`.
2. **schedule** — The Blue Alliance API v3 (primary), FRC Events API and
   Nexus as fallbacks: `event_key + match_key` → 6 team numbers + stations.
3. **ingest** — `yt-dlp` manifest resolution → OpenCV/ffmpeg frame iterator;
   `replay` (deterministic VOD pass) and `live` (tail, tolerate drops) modes.
4. **overlay** — crop FMS overlay regions (configurable per broadcast layout),
   OCR timer/phase/scores with PaddleOCR (Tesseract fallback) → phase
   segmentation + score-delta timeline.
5. **detect/track** — YOLOv8/v11 fine-tuned on FRC broadcast frames (classes:
   robot, bumper-red, bumper-blue, fuel) at 5–10 fps + ByteTrack persistent
   IDs; alliance-color split from bumper hue.
6. **identify** — schedule prior makes identity a 6-way assignment problem:
   alliance color splits 3v3, opportunistic bumper OCR fuzzy-matched against
   the 3 expected numbers, starting-station prior at match start; per-track
   assignment confidence, never overwritten by a single noisy read.
7. **fieldmap** — homography from field landmarks → robot field coordinates →
   zone membership (`rubric.json` zones).
8. **events** — zone + overlay-score-delta heuristics as the workhorse
   (hub-active shifts constrain which alliance a delta belongs to); Claude
   (Anthropic API) on short ambiguous clips as sparse, cached disambiguation;
   Tower climb from vertical position + endgame phase + final score delta.
9. **aggregate** — reconcile events vs. overlay scoreboard, flag mismatches,
   emit per-robot JSON + flat CSV (Galaxia push as stretch).

Known hard problems tracked explicitly (bumper OCR unreliability, score
attribution in scrums, occlusion, broadcast cuts, overlay layout drift) — see
the build prompt; each stage exposes uncertainty rather than papering over it.

## Repo layout

```
src/frcscout/
  cli.py                frcscout CLI (rubric build|validate, schedule fetch)
  config.py             config.yaml loader (+ env-var secret fallback)
  schedule/
    model.py            MatchLineup/RobotSlot (validated 6-team identity prior)
    matchkey.py         TBA match-key parsing incl. double-elim mapping
    tba.py              The Blue Alliance API v3 (primary)
    frc_events.py       FRC Events API v3.0 (fallback)
    nexus.py            Nexus API v1 (fallback)
    fetch.py            provider chain + error aggregation
  ingest/
    source.py           file/URL/YouTube resolution (yt-dlp)
    frames.py           sampled Frame iterator (replay + live semantics)
  rubric/
    seed.py             seeded REBUILT rubric + provenance
    patterns.py         regex extraction specs (unit-tested)
    extract.py          PDF/HTML → normalized text
    fetch.py            manual download (PDF, HTML mirror fallback)
    build.py            seed + manual text → rubric.json + report
    model.py            validation, verification-status contract
tests/                  28 tests, incl. manual-style fixture excerpts
rubric.json             generated rubric (currently seed-only, see note)
config.example.yaml     API keys, stream, overlay crops, thresholds
```
