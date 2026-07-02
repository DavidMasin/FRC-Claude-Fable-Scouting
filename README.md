# FRC Vision Scouting — REBUILT (2026)

Automated scouting of FRC matches from a YouTube live stream / VOD. Watches the
broadcast, tracks all six robots, resolves identities against the published
match schedule, and emits per-robot scouting records (fuel scoring, cycles,
defense, Tower climb) — every event carrying a confidence and a timestamp so a
human can verify it.

## Status: all 10 milestones built

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Game manual → `rubric.json` parser + validation | ✅ |
| 2 | Schedule fetch (TBA / FRC Events / Nexus) → 6 teams + stations | ✅ |
| 3 | Stream ingest → frame iterator (yt-dlp + OpenCV) | ✅ |
| 4 | FMS overlay OCR → phase / timer / score timeline | ✅ |
| 5 | Robot detection + tracking (YOLO or color-blob; ByteTrack-style) | ✅ |
| 6 | Bumper OCR + track↔team assignment | ✅ |
| 7 | Homography → field zones | ✅ |
| 8 | Event detection (zone+overlay heuristics, VLM disambiguation) | ✅ |
| 9 | Aggregation, reconciliation, JSON/CSV export | ✅ |
| 10 | Live/replay pipeline (`frcscout scout`) w/ scene-cut guard | ✅ |

Remaining before real-event use: verify `rubric.json` against the actual
manual (`frcscout rubric build --fetch`), train YOLO weights on labeled
broadcast frames (`frcscout ingest sample` bootstraps the dataset), measure
zone polygons from the field drawings, and calibrate the homography per
broadcast camera. Everything is unit/e2e-tested against synthetic broadcasts.

## Quick start (full pipeline)

```bash
frcscout rubric build --fetch                       # manual -> rubric.json
frcscout schedule fetch --match 2026isde1_qm14 --json > lineup.json
frcscout scout match.mp4 --lineup lineup.json --debug-video debug.mp4
# live: frcscout scout "https://youtube.com/watch?v=..." --match 2026isde1_qm14 --mode live
```

`scout` runs ingest → overlay OCR → detect/track → identify → field-map →
events → aggregate. It streams confirmed events to
`out/<match>_events.jsonl` as they happen (live consumers tail this), then
writes the per-match record `out/<match>.json` (per-robot auto/teleop fuel,
cycles, endgame climb, defense seconds, full event log with confidences and
flags, alliance reconciliation vs the overlay scoreboard) and a flat
`out/<match>.csv` for scouting-database import. Broadcast cuts/replays are
detected (SceneGuard) and suspend tracking + attribution until the shot
stabilizes; the count of suspended frames is reported.

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

## Overlay OCR (phase + score timeline)

```bash
frcscout overlay read match.mp4 --fps 4 --expect-final 112:98
```

Crops the configured overlay regions (`overlay.regions`, fractional boxes so
they're resolution-independent), OCRs timer + both scores every sampled frame,
and reconstructs the match: phase changes (`auto → between_periods → teleop →
endgame → post_match`, timing from `rubric.json`) and a debounced score
timeline. Nothing is trusted from one frame: a score needs 2 consecutive
identical reads to confirm, and decreases or implausible jumps need 4 (real
scorekeeper corrections surface as `correction` events; OCR spikes like
`5 → 58 → 5` are dropped). `--expect-final` cross-checks the OCR'd final
score against the known result.

OCR backends (`overlay.ocr_backend`): `template` — built-in zero-dependency
NCC digit matcher, good for clean overlays and tests; `paddleocr` /
`tesseract` for styled broadcast fonts (`pip install -e ".[ocr]"`).

## Detection + tracking

```bash
frcscout track match.mp4 --fps 6 --debug-video debug.mp4          # color-blob
frcscout track match.mp4 --detector yolo --debug-video debug.mp4  # YOLO weights
```

Two detectors behind one `Detection` interface: `yolo` (ultralytics, weights
fine-tuned on broadcast frames with classes robot/bumper-red/bumper-blue/fuel
— the production path, needs `pip install -e ".[vision]"` + `models.detector_weights`)
and `color` (HSV bumper-blob detector — zero dependencies, works because FRC
bumpers are mandated saturated red/blue; the graceful-degradation and test
path). The tracker is ByteTrack-style: two-stage greedy IoU association
(high-confidence first, low-confidence rescues), constant-velocity prediction,
and explicit track states — `tentative → confirmed → lost → dead`. A lost
robot is *reported* lost (no fabricated positions) and can be re-associated
by alliance color + proximity when it reappears; an alliance mismatch always
vetoes a match. `--debug-video` renders boxes/IDs/alliance/state for human
verification.

## Team identity (track ↔ team assignment)

```bash
frcscout schedule fetch --match 2026isde1_qm14 --json > lineup.json
frcscout track match.mp4 --lineup lineup.json --debug-video debug.mp4
```

Identity is a 6-way assignment problem against the schedule, never open-set
OCR. Evidence accumulates per (track, team): a station prior at match start
(station order ↔ image-x order, refined by homography in milestone 7) and
opportunistic bumper OCR reads, fuzzy-matched against only the 3 expected
numbers on that track's alliance (a partial `598` counts toward 5987; a read
matching nobody counts nowhere). The solver brute-forces the track→team
bijection per alliance (exact at 3×3) with hysteresis — a challenger must
beat the incumbent by a margin, so one noisy read can never flip a confident
assignment, while repeated contrary evidence can. Every assignment carries a
confidence (softmax over that track's evidence, damped when evidence is
thin); the debug renderer marks low-confidence labels with `?`.

## Field mapping (homography + zones)

```bash
frcscout field locate --pixel 640,400     # -> field coords + zones at that pixel
```

Calibrate once per camera: click ≥4 known landmarks on a frame and record the
pixel ↔ field-coordinate pairs in `field.calibration`. Robots map through
their ground contact point (bottom-center of the box; the homography is only
valid on the floor plane). Zone *names/roles* come from `rubric.json`; zone
*geometry* is config (`field.zones`, polygons in meters — the shipped ones
are placeholders to re-measure from the official field drawings), and a
configured zone name that the rubric doesn't declare is rejected. Zone
membership ("at the Tower", "in the hub zone") is what event attribution
keys on — far more robust than trying to see a ball enter a goal.

## Event detection

`EventEngine` (src/frcscout/events/) consumes per-frame context — phase,
tracks with field positions and zones, overlay score changes — and emits
`ScoutingEvent`s, every one carrying confidence, source, timestamp, frame
index, and flags. The workhorse: an overlay score jump for an alliance is
credited to that alliance's robot recently in its scoring zone. One candidate
→ conf 0.85; several → the VLM disambiguator (Claude, sparse + disk-cached,
`events/vlm.py`) if configured, else most-recent entrant at conf 0.5 with an
`ambiguous_attribution` flag; none → unattributed event with
`no_robot_in_zone` — never fabricated onto a robot. Wrong-alliance robots are
never credited. Endgame deltas matching Tower point values with one robot at
the tower become `climb_level_N`; tower-zone dwell emits `climb_attempt_start`;
defense = sustained proximity to an opponent in their half; cycles from
loading-zone → hub-zone transitions. Points come from `rubric.json` — events
built on unverified rubric values carry `points_unverified`.

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
  cli.py                frcscout CLI (rubric, schedule, ingest, overlay,
                        track, field, scout)
  config.py             config.yaml loader (+ env-var secret fallback)
  pipeline.py           full-pipeline orchestrator + SceneGuard (cut detection)
  aggregate/
    records.py          per-robot records + scoreboard reconciliation
    export.py           per-match JSON + flat CSV
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
  overlay/
    regions.py          fractional crop regions (per-broadcast config)
    ocr.py              OCR backends: template (built-in) / tesseract / paddleocr
    parse.py            timer/score parsing -> OverlayReading
    timeline.py         phase machine + debounced score timeline
  events/
    model.py            ScoutingEvent (confidence + source + frame + flags)
    engine.py           zone+overlay attribution, climbs, defense, cycles
    vlm.py              Claude disambiguator (sparse, disk-cached)
  field/
    homography.py       pixel -> field coords (ground-point mapping)
    zones.py            zone polygons; names validated against rubric
  identify/
    bumper_ocr.py       bumper-band crop + digit OCR (evidence only)
    assignment.py       fuzzy match + per-alliance assignment solver w/ hysteresis
  vision/
    detections.py       Detection type + IoU
    color_detector.py   HSV bumper-blob detector (no weights needed)
    yolo_detector.py    ultralytics YOLO wrapper (production)
    tracker.py          ByteTrack-style IoU tracker w/ lost-state + re-association
    debug.py            annotated debug-video renderer
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
