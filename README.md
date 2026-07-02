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
| + | Active-learning dataset miner (`frcscout dataset mine`) | ✅ |
| + | Galaxia push / Statbotics EPA cross-check / bilingual reports | ✅ |
| + | Web UI dashboard (`frcscout ui`) | ✅ |
| + | Zero-calibration auto mode (overlay auto-detect + pixel zones) | ✅ |
| + | Synthetic training data (`frcscout dataset synth`) | ✅ |

Remaining before real-event use: verify `rubric.json` against the actual
manual (`frcscout rubric build --fetch`) and train YOLO weights (start from
`dataset synth` + the real datasets below). Calibration is now optional —
with nothing configured the pipeline auto-detects the overlay and uses
pixel-band zones; a measured homography just makes zone logic sharper.

## Web UI

```bash
pip install -e ".[ui]"
frcscout ui                      # -> http://127.0.0.1:5000
```

Start a run from the browser: paste a video path/URL, type the six team
numbers (or just a match key when API keys are configured), hit *Start
scouting*. You get a live event feed while it runs, then a match dashboard:
per-robot cards (auto/teleop fuel, cycles, climb, defense, identity-
confidence meter, flags), a fuel bar chart, a hoverable event timeline with
phase markers, the full event table, and download buttons for the JSON /
CSV / bilingual reports. Light and dark theme follow the system; the
alliance palette is CVD-validated in both.

## Deploy on Railway

The repo is Railway-ready (`Dockerfile` + `railway.json`, health check at
`/healthz`):

1. **Railway → New Project → Deploy from GitHub repo** and pick this repo
   (`main`). Railway detects the Dockerfile and builds automatically.
   CLI alternative: `railway init && railway up`.
2. **Add a volume** mounted at **`/data`** (Service → Attach Volume) so
   scouted matches and uploads survive redeploys — records are written to
   `/data/out` (`FRCSCOUT_OUT_DIR`, already set in the image).
3. **Optional env vars** (Service → Variables): `TBA_AUTH_KEY` to fetch
   lineups by match key, `FRC_EVENTS_USERNAME`/`FRC_EVENTS_AUTH_TOKEN`,
   `NEXUS_API_KEY`, `ANTHROPIC_API_KEY` for `--vlm`-style disambiguation.
   No config file is needed — everything is environment-first.
4. **Generate a domain** (Settings → Networking) and open it.

On Railway you feed matches by **YouTube/direct URL** or the **upload
field** on the start page (uploads land on the volume; up to 4 GB). Notes:
Railway instances are CPU-only, so keep the sample FPS around 4–6; the app
runs one gunicorn worker with 8 threads because job state is in-process —
scale threads, not workers/replicas.

## Zero-calibration mode

With an empty config the pipeline configures itself:

- **overlay**: crop regions are auto-detected from the stream (decreasing
  timer + flanking score integers), no measuring;
- **zones**: without a homography it falls back to pixel bands — each
  alliance's side and a neutral middle, with the red side inferred from
  where the red robots actually start. Hub/tower share the band, so
  attribution is coarser than with a measured homography (events carry the
  same confidences either way); add `field.calibration` whenever you want
  real field coordinates.

The zero-config e2e test scouts the full synthetic match this way with
identical results to the calibrated run.

## Robot detection data

Two immediate options, best combined:

- `frcscout dataset synth --n 500` renders a labeled synthetic set (robots
  with red/blue bumpers + numbers, fuel, overlay bar, blur/lighting/occlusion
  jitter) — enough to bootstrap a first detector with zero labeling work.
- Real community datasets to mix in (synthetic-only detectors overfit):
  [FRC robots on Roboflow Universe](https://universe.roboflow.com/frc-08aim/frc-robots-fx5cu)
  (~3.3k labeled robot images + pretrained model) and
  [Dataset Colab](https://www.chiefdelphi.com/t/introducing-dataset-colab-an-object-detection-dataset-collaboration-software/447259)
  (~4.8k robot images collected by FRC teams). Export in YOLO format and
  merge with the synth set; class names are in `dataset.yaml`.

Then `yolo detect train data=data/synth/dataset.yaml model=yolo11n.pt`,
point `models.detector_weights` at the result, and refine with
`frcscout dataset mine` (active learning) on real event VODs. Until you have
weights, the color-blob detector keeps everything running.

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
stabilizes; the count of suspended frames is reported. A confirmed robot
going untracked emits a `track_lost` event (flag `tracking_gap`) so the
record shows the observation gap instead of silence. With `--vlm`, the
pipeline feeds the Claude disambiguator crops of the candidate robots from
the most recent stable frame — it's only consulted on ambiguous
attributions, and responses are disk-cached.

## After the match

```bash
frcscout report out/2026isde1_qm14.json            # bilingual he/en markdown
frcscout push out/2026isde1_qm14.json              # -> Galaxia (apis.galaxia)
frcscout crosscheck out/2026isde1_qm14.json        # vs Statbotics EPA
```

`report` writes `<match>_report.en.md` and `<match>_report.he.md` (RTL-wrapped)
with per-robot tables and any reconciliation warnings. `push` POSTs the full
record to the Galaxia Flask stack (`apis.galaxia.path_template` controls the
endpoint). `crosscheck` compares each robot's vision-attributed points to its
Statbotics EPA (self-hosted `apis.statbotics.base_url` or statbotics.io) and
marks large deviations `epa_outlier` — informational, a reviewer cue, not a
verdict.

## Improving the detector (active learning)

```bash
frcscout dataset mine event_vod.mp4 --fps 2 --out data/dataset
# label the frames in data/dataset/queue/ (each JPEG has a .json of the
# detector's own guesses to pre-fill your annotation tool), then:
yolo detect train data=data/dataset/dataset.yaml model=yolo11n.pt
# point models.detector_weights at runs/detect/train/weights/best.pt and
# re-mine with --detector yolo: the queue shrinks toward the hard frames.
```

Confident frames become YOLO-format pseudo-labels (sampled every few seconds
to avoid near-duplicates); frames with low-confidence detections — the ones
the current detector is worst at — go to the human label queue.

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
frcscout overlay autodetect match.mp4 --start 300   # find the crop regions
frcscout overlay read match.mp4 --fps 4 --expect-final 112:98
```

`autodetect` samples a few frames of live play and finds the regions itself:
bright text lines are OCR'd, candidates are clustered across frames (the
overlay is static; drifting bumper numbers and non-parsing text drop out),
the cluster whose value strictly decreases is the timer, and the aligned
non-decreasing integers flanking it are the scores (left = red, right =
blue). It prints a paste-ready `overlay.regions` config snippet.

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
  report.py             bilingual (en/he) markdown match reports
  aggregate/
    records.py          per-robot records + scoreboard reconciliation
    export.py           per-match JSON + flat CSV
  dataset/
    miner.py            active learning: pseudo-labels + human label queue
    synth.py            synthetic labeled bootstrap dataset
  ui/
    app.py              Flask dashboard (jobs, live feed, match pages)
    jobs.py             background run manager
  field/autozones.py    calibration-free pixel-band zones
  overlay/autodetect.py automatic overlay-region discovery
  integrations/
    galaxia.py          push records to the Galaxia scouting stack
    statbotics.py       EPA cross-check (informational outlier flags)
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
    autodetect.py       find timer/score regions automatically
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
