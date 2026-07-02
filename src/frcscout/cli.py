"""frcscout CLI. Milestone 1 ships the `rubric` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_rubric_build(args: argparse.Namespace) -> int:
    from .rubric.build import build_rubric, write_rubric
    from .rubric.extract import extract_manual_text

    manual_path: Path | None = Path(args.manual) if args.manual else None
    if args.fetch:
        from .rubric.fetch import fetch_manual
        try:
            manual_path = fetch_manual(args.data_dir)
            print(f"fetched manual -> {manual_path}")
        except Exception as exc:
            print(f"WARNING: manual fetch failed ({exc}); "
                  "building seed-only rubric (all values needs-verification)",
                  file=sys.stderr)

    text = extract_manual_text(manual_path) if manual_path else None
    rubric, report = build_rubric(text)
    out = write_rubric(rubric, args.out)

    print(f"wrote {out}")
    print(f"  verified from manual : {len(report['verified'])}")
    print(f"  patterns unmatched   : {len(report['unmatched'])}")
    for path in report["unmatched"]:
        print(f"    - {path} (kept seed value, needs-verification)")
    for path, seed_v, manual_v in report["conflicts"]:
        print(f"  CONFLICT {path}: seed={seed_v} manual={manual_v} (manual wins — verify pattern)")
    print(f"  entries needing human verification: {len(report['needs_verification'])}")
    return 0


def _cmd_rubric_validate(args: argparse.Namespace) -> int:
    from .rubric.model import RubricError, unverified_entries, validate_rubric

    rubric = json.loads(Path(args.rubric).read_text())
    try:
        validate_rubric(rubric)
    except RubricError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    pending = unverified_entries(rubric)
    print(f"OK: {args.rubric} is structurally valid; "
          f"{len(pending)} value(s) still need manual verification")
    if args.verbose:
        for p in pending:
            print(f"  - {p}")
    return 0


def _cmd_schedule_fetch(args: argparse.Namespace) -> int:
    from .config import load_config
    from .schedule import ScheduleError, fetch_lineup
    from .schedule.fetch import DEFAULT_ORDER

    config = load_config(args.config)
    match_key = args.match or config.get("match_key")
    if not match_key:
        print("no match key: pass --match or set match_key in config.yaml", file=sys.stderr)
        return 2
    providers = tuple(args.provider) if args.provider else DEFAULT_ORDER

    try:
        lineup = fetch_lineup(match_key, config, providers=providers)
    except (ScheduleError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(lineup.to_dict(), indent=2))
    else:
        print(f"{lineup.match_key}  (source: {lineup.source})")
        for alliance in ("red", "blue"):
            teams = "  ".join(f"{t:>5}" for t in lineup.teams(alliance))
            print(f"  {alliance:>4}: {teams}   (stations 1-3)")
    return 0


def _cmd_ingest_probe(args: argparse.Namespace) -> int:
    from .ingest import FrameIterator, IngestError, resolve_source

    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, live=src.is_live) as frames:
            meta = frames.meta
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"kind      : {src.kind}" + (f"  ({src.title})" if src.title else ""))
    print(f"live      : {src.is_live}")
    print(f"resolution: {meta.width}x{meta.height}")
    print(f"fps       : {meta.fps:g}")
    if meta.duration_s is not None:
        print(f"duration  : {meta.duration_s:.1f}s ({meta.frame_count} frames)")
    else:
        print("duration  : unknown (live or unseekable)")
    return 0


def _cmd_ingest_sample(args: argparse.Namespace) -> int:
    import cv2

    from .ingest import FrameIterator, IngestError, resolve_source

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, sample_fps=args.fps, start_s=args.start,
                           duration_s=args.duration, live=src.is_live) as frames:
            n = 0
            for frame in frames:
                name = out_dir / f"frame_{frame.index:07d}_t{frame.t_video:08.2f}.jpg"
                cv2.imwrite(str(name), frame.image)
                n += 1
                if args.max and n >= args.max:
                    break
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {n} frames to {out_dir}/")
    return 0


def _cmd_overlay_read(args: argparse.Namespace) -> int:
    from .config import load_config
    from .ingest import FrameIterator, IngestError, resolve_source
    from .overlay.ocr import get_backend
    from .overlay.parse import read_overlay
    from .overlay.timeline import OverlayTimeline, PhaseChange, ScoreChange

    config = load_config(args.config)
    regions = (config.get("overlay") or {}).get("regions") or {}
    if not regions:
        print("no overlay.regions in config", file=sys.stderr)
        return 2
    backend = get_backend(args.backend
                          or (config.get("overlay") or {}).get("ocr_backend")
                          or "template")

    rubric_path = Path(config.get("rubric_path", "rubric.json"))
    if rubric_path.exists():
        timeline = OverlayTimeline.from_rubric(json.loads(rubric_path.read_text()))
    else:
        timeline = OverlayTimeline()

    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, sample_fps=args.fps, start_s=args.start,
                           duration_s=args.duration, live=src.is_live) as frames:
            for frame in frames:
                reading = read_overlay(frame.image, frame.t_video, regions, backend)
                for event in timeline.add(reading):
                    if isinstance(event, PhaseChange):
                        print(f"[{event.t_video:8.2f}s] phase -> {event.phase}")
                    elif isinstance(event, ScoreChange):
                        print(f"[{event.t_video:8.2f}s] {event.alliance} "
                              f"{event.delta:+d} -> {event.total} ({event.kind})")
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"final: red {timeline.scores['red']} - blue {timeline.scores['blue']}")
    if args.expect_final:
        red, blue = (int(x) for x in args.expect_final.split(":"))
        ok = (timeline.scores["red"], timeline.scores["blue"]) == (red, blue)
        print("scoreboard cross-check:", "OK" if ok else
              f"MISMATCH (expected {red}:{blue})")
        return 0 if ok else 1
    return 0


def _load_lineup(path: str):
    from .schedule.model import lineup_from_alliances

    data = json.loads(Path(path).read_text())
    return lineup_from_alliances(data["match_key"], data["event_key"],
                                 data.get("source", "file"),
                                 data["red"], data["blue"])


def _cmd_track(args: argparse.Namespace) -> int:
    from .identify import TeamAssigner, read_bumper
    from .ingest import FrameIterator, IngestError, resolve_source
    from .overlay.ocr import get_backend
    from .vision import ColorBlobDetector, IouTracker
    from .vision.debug import DebugVideoWriter, draw_tracks
    from .vision.tracker import LOST

    if args.detector == "yolo":
        from .config import load_config
        from .vision.yolo_detector import YoloDetector

        config = load_config(args.config)
        weights = (config.get("models") or {}).get("detector_weights")
        if not weights or not Path(weights).exists():
            print(f"no detector weights at {weights!r} — train/download them "
                  "or use --detector color", file=sys.stderr)
            return 2
        detector = YoloDetector(weights,
                                conf=(config.get("thresholds") or {}).get("detection_conf", 0.35))
    else:
        detector = ColorBlobDetector()

    assigner = None
    ocr_backend = None
    bumper_band = (0.0, 1.0) if args.detector == "color" else (0.55, 1.0)
    if args.lineup:
        assigner = TeamAssigner(_load_lineup(args.lineup))
        ocr_backend = get_backend(args.bumper_backend)

    tracker = IouTracker()
    writer = None
    n_frames = 0
    lost_events = 0
    seeded = False
    was_lost: set[int] = set()
    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, sample_fps=args.fps, start_s=args.start,
                           duration_s=args.duration, live=src.is_live) as frames:
            for frame in frames:
                shape = frame.image.shape[:2]
                confirmed = tracker.update(detector.detect(frame.image),
                                           frame.t_video, shape)
                n_frames += 1
                if assigner is not None:
                    if not seeded and len(confirmed) == 6:
                        assigner.seed_station_prior(confirmed)
                        seeded = True
                    for tr in confirmed:
                        digits, conf = read_bumper(frame.image, tr.xyxy,
                                                   ocr_backend, band=bumper_band)
                        if digits and tr.alliance:
                            assigner.add_ocr(tr.track_id, tr.alliance, digits, conf)
                for tr in tracker.tracks:
                    if tr.state == LOST and tr.track_id not in was_lost:
                        was_lost.add(tr.track_id)
                        lost_events += 1
                    elif tr.state != LOST:
                        was_lost.discard(tr.track_id)
                if args.debug_video:
                    if writer is None:
                        writer = DebugVideoWriter(args.debug_video, args.fps,
                                                  (shape[1], shape[0]))
                    labels = assigner.team_labels() if assigner else None
                    writer.write(draw_tracks(frame.image, tracker.tracks, labels))
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if writer is not None:
            writer.close()

    confirmed = [tr for tr in tracker.tracks if tr.state == "confirmed"]
    by_alliance = {"red": 0, "blue": 0, None: 0}
    for tr in confirmed:
        by_alliance[tr.alliance] = by_alliance.get(tr.alliance, 0) + 1
    print(f"processed {n_frames} sampled frames")
    print(f"confirmed tracks: {len(confirmed)} "
          f"(red {by_alliance['red']}, blue {by_alliance['blue']}, "
          f"unknown {by_alliance[None]})")
    print(f"lost-track episodes: {lost_events}")
    if assigner is not None:
        print("team assignments:")
        for tid, a in sorted(assigner.assignments().items()):
            team = a.team if a.team is not None else "unassigned"
            print(f"  track #{tid}: {team}  conf={a.confidence:.2f} "
                  f"evidence={a.evidence:.1f}")
    if args.debug_video:
        print(f"debug video: {args.debug_video}")
    return 0


def _cmd_overlay_autodetect(args: argparse.Namespace) -> int:
    import yaml

    from .ingest import FrameIterator, IngestError, resolve_source
    from .overlay.autodetect import autodetect_regions
    from .overlay.ocr import get_backend

    backend = get_backend(args.backend)
    frames = []
    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, sample_fps=1.0 / args.spacing,
                           start_s=args.start, live=src.is_live) as it:
            for frame in it:
                frames.append(frame.image)
                if len(frames) >= args.frames:
                    break
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if len(frames) < 3:
        print("need at least 3 frames of live play", file=sys.stderr)
        return 1
    try:
        regions = autodetect_regions(frames, backend)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("# paste into config.yaml:")
    print(yaml.safe_dump({"overlay": {"regions": regions}}, sort_keys=False).rstrip())
    return 0


def _cmd_field_locate(args: argparse.Namespace) -> int:
    from .config import load_config
    from .field import FieldMap, ZoneMap

    config = load_config(args.config)
    field_config = config.get("field") or {}
    try:
        fmap = FieldMap.from_config(field_config)
    except ValueError as exc:
        print(f"ERROR: {exc} — fill in field.calibration in config", file=sys.stderr)
        return 1
    rubric = None
    rubric_path = Path(config.get("rubric_path", "rubric.json"))
    if rubric_path.exists():
        rubric = json.loads(rubric_path.read_text())
    zmap = ZoneMap.from_config(field_config, rubric)

    px, py = (float(v) for v in args.pixel.split(","))
    fx, fy = fmap.to_field(px, py)
    zones = sorted(zmap.zone_names_at(fx, fy))
    print(f"pixel ({px:g}, {py:g}) -> field ({fx:.2f} m, {fy:.2f} m)"
          f"{'' if fmap.in_bounds(fx, fy) else '  [OUT OF BOUNDS]'}")
    print(f"zones: {', '.join(zones) if zones else '(none)'}")
    return 0


def _cmd_scout(args: argparse.Namespace) -> int:
    from .aggregate import write_csv, write_json
    from .config import load_config
    from .ingest import IngestError
    from .pipeline import ScoutingPipeline
    from .schedule import ScheduleError, fetch_lineup

    config = load_config(args.config)

    rubric_path = Path(config.get("rubric_path", "rubric.json"))
    if not rubric_path.exists():
        print(f"{rubric_path} not found — run `frcscout rubric build` first",
              file=sys.stderr)
        return 2
    rubric = json.loads(rubric_path.read_text())

    if args.lineup:
        lineup = _load_lineup(args.lineup)
    else:
        match_key = args.match or config.get("match_key")
        if not match_key:
            print("need --lineup, --match, or match_key in config", file=sys.stderr)
            return 2
        try:
            lineup = fetch_lineup(match_key, config)
        except (ScheduleError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    detector = None
    if args.detector == "yolo":
        from .vision.yolo_detector import YoloDetector

        weights = (config.get("models") or {}).get("detector_weights")
        detector = YoloDetector(weights)

    vlm = None
    anthropic_cfg = (config.get("apis") or {}).get("anthropic") or {}
    if args.vlm and anthropic_cfg.get("api_key"):
        from .events.vlm import AnthropicDisambiguator

        vlm = AnthropicDisambiguator(anthropic_cfg["api_key"],
                                     model=anthropic_cfg.get("model", "claude-fable-5"))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / f"{lineup.match_key}_events.jsonl"
    pipeline = ScoutingPipeline(config, rubric, lineup, detector=detector, vlm=vlm)

    with events_path.open("w") as events_fh:
        def on_event(ev):
            events_fh.write(json.dumps(ev.to_dict()) + "\n")
            events_fh.flush()  # live consumers tail this file
            print(f"[{ev.t_video:8.2f}s] {ev.type} team={ev.team} "
                  f"count={ev.count} conf={ev.conf:.2f}"
                  + (f" flags={','.join(ev.flags)}" if ev.flags else ""))

        try:
            result = pipeline.run(args.source, sample_fps=args.fps,
                                  start_s=args.start, duration_s=args.duration,
                                  mode=args.mode, on_event=on_event,
                                  debug_video=args.debug_video,
                                  stop_at_match_end=not args.run_to_eof)
        except IngestError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    json_path = write_json(result.record, out_dir / f"{lineup.match_key}.json")
    csv_path = write_csv(result.record, out_dir / f"{lineup.match_key}.csv")

    print(f"\nprocessed {result.n_frames} frames "
          f"({result.n_unstable} suspended during cuts/replays)")
    scores = result.record["alliances"]
    print(f"final (overlay): red {scores['red']['overlay_final']} - "
          f"blue {scores['blue']['overlay_final']}")
    for alliance in ("red", "blue"):
        if scores[alliance].get("flag"):
            print(f"  WARNING {alliance}: vision attributed "
                  f"{scores[alliance]['vision_attributed_points']} pts "
                  f"vs overlay {scores[alliance]['overlay_final']}")
    print(f"wrote {json_path}, {csv_path}, {events_path}")
    return 0


def _cmd_dataset_mine(args: argparse.Namespace) -> int:
    from .dataset import DatasetMiner
    from .ingest import FrameIterator, IngestError, resolve_source
    from .vision import ColorBlobDetector

    if args.detector == "yolo":
        from .config import load_config
        from .vision.yolo_detector import YoloDetector

        config = load_config(args.config)
        detector = YoloDetector((config.get("models") or {}).get("detector_weights"))
    else:
        detector = ColorBlobDetector()

    tag = Path(args.source).stem[:40] or "stream"
    miner = DatasetMiner(detector, args.out, low_conf=args.low_conf,
                         pseudo_every_s=args.pseudo_every, source_tag=tag)
    try:
        src = resolve_source(args.source)
        with FrameIterator(src.location, sample_fps=args.fps, start_s=args.start,
                           duration_s=args.duration, live=src.is_live) as frames:
            for frame in frames:
                miner.process(frame.image, frame.t_video, frame.index)
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    stats = miner.finalize()
    print(json.dumps(stats, indent=2))
    print(f"\ndataset: {args.out}/dataset.yaml  "
          f"(train: yolo detect train data={args.out}/dataset.yaml model=yolo11n.pt)")
    print(f"label queue: {args.out}/queue/ "
          f"({stats['queued_for_labeling']} frames need human labels)")
    return 0


def _cmd_dataset_synth(args: argparse.Namespace) -> int:
    from .dataset.synth import generate_synthetic_dataset

    stats = generate_synthetic_dataset(args.out, n_images=args.n, seed=args.seed)
    print(json.dumps(stats, indent=2))
    print(f"\ntrain: yolo detect train data={args.out}/dataset.yaml model=yolo11n.pt")
    print("mix in real labeled frames (see README data sources) as soon as you can —")
    print("synthetic-only detectors overfit to the renderer.")
    return 0


def _cmd_push(args: argparse.Namespace) -> int:
    from .config import load_config
    from .integrations import push_match
    from .integrations.galaxia import IntegrationError

    record = json.loads(Path(args.record).read_text())
    try:
        response = push_match(record, load_config(args.config))
    except IntegrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"pushed {record['match_key']} -> {response}")
    return 0


def _cmd_crosscheck(args: argparse.Namespace) -> int:
    from .config import load_config
    from .integrations import epa_crosscheck

    record = json.loads(Path(args.record).read_text())
    rows = epa_crosscheck(record, load_config(args.config), season=args.season)
    outliers = 0
    for row in rows:
        epa = f"{row['epa_mean']:.1f}" if row["epa_mean"] is not None else "n/a"
        marker = ""
        if row["verdict"] == "epa_outlier":
            outliers += 1
            marker = "  <-- check this one"
        print(f"team {row['team']:>5} ({row['alliance']:>4}): "
              f"attributed {row['attributed_points']:>3} pts, EPA {epa:>6} "
              f"[{row['verdict']}]{marker}")
    print(f"\n{outliers} outlier(s); deviations are informational, not verdicts")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from .report import write_reports

    record = json.loads(Path(args.record).read_text())
    langs = tuple(args.langs.split(","))
    paths = write_reports(record, args.out_dir, langs)
    for p in paths:
        print(f"wrote {p}")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    try:
        from .ui import create_app
    except ImportError:
        print("the UI needs Flask: pip install -e '.[ui]'", file=sys.stderr)
        return 2

    app = create_app(config_path=args.config, out_dir=args.out_dir)
    print(f"frcscout UI -> http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frcscout")
    sub = parser.add_subparsers(dest="command", required=True)

    rubric = sub.add_parser("rubric", help="game-manual rubric tools")
    rsub = rubric.add_subparsers(dest="rubric_command", required=True)

    build = rsub.add_parser("build", help="build rubric.json from the game manual")
    build.add_argument("--manual", help="path to a local manual PDF/HTML")
    build.add_argument("--fetch", action="store_true",
                       help="download the official manual first")
    build.add_argument("--data-dir", default="data", help="download directory")
    build.add_argument("--out", default="rubric.json")
    build.set_defaults(func=_cmd_rubric_build)

    validate = rsub.add_parser("validate", help="validate an existing rubric.json")
    validate.add_argument("rubric", nargs="?", default="rubric.json")
    validate.add_argument("-v", "--verbose", action="store_true")
    validate.set_defaults(func=_cmd_rubric_validate)

    schedule = sub.add_parser("schedule", help="match schedule tools")
    ssub = schedule.add_subparsers(dest="schedule_command", required=True)

    sfetch = ssub.add_parser("fetch", help="fetch the 6-team lineup for a match")
    sfetch.add_argument("--match", help="match key, e.g. 2026isde1_qm14 "
                        "(default: match_key from config)")
    sfetch.add_argument("--config", default="config.yaml")
    sfetch.add_argument("--provider", action="append",
                        choices=["tba", "frc_events", "nexus"],
                        help="force provider order (repeatable)")
    sfetch.add_argument("--json", action="store_true", help="emit JSON")
    sfetch.set_defaults(func=_cmd_schedule_fetch)

    ingest = sub.add_parser("ingest", help="stream/VOD ingestion tools")
    isub = ingest.add_subparsers(dest="ingest_command", required=True)

    probe = isub.add_parser("probe", help="print source metadata")
    probe.add_argument("source", help="local file, direct URL, or YouTube URL")
    probe.set_defaults(func=_cmd_ingest_probe)

    sample = isub.add_parser(
        "sample", help="dump sampled frames as JPEGs (also feeds the labeling bootstrap)")
    sample.add_argument("source")
    sample.add_argument("--fps", type=float, default=2.0, help="sampling rate")
    sample.add_argument("--start", type=float, default=0.0, help="seek (seconds)")
    sample.add_argument("--duration", type=float, help="stop after N seconds of video")
    sample.add_argument("--max", type=int, help="stop after N frames")
    sample.add_argument("--out", default="data/samples")
    sample.set_defaults(func=_cmd_ingest_sample)

    overlay = sub.add_parser("overlay", help="FMS overlay OCR tools")
    osub = overlay.add_subparsers(dest="overlay_command", required=True)

    oread = osub.add_parser("read", help="OCR the overlay into a phase/score timeline")
    oread.add_argument("source")
    oread.add_argument("--config", default="config.yaml")
    oread.add_argument("--backend", choices=["template", "tesseract", "paddleocr"],
                       help="override OCR backend")
    oread.add_argument("--fps", type=float, default=4.0)
    oread.add_argument("--start", type=float, default=0.0)
    oread.add_argument("--duration", type=float)
    oread.add_argument("--expect-final", metavar="RED:BLUE",
                       help="validate the OCR'd final score, e.g. 112:98")
    oread.set_defaults(func=_cmd_overlay_read)

    odetect = osub.add_parser("autodetect",
                              help="find timer/score crop regions automatically")
    odetect.add_argument("source")
    odetect.add_argument("--start", type=float, default=0.0,
                         help="seek into live play (seconds)")
    odetect.add_argument("--frames", type=int, default=6,
                         help="how many sample frames to inspect")
    odetect.add_argument("--spacing", type=float, default=2.0,
                         help="seconds between sample frames")
    odetect.add_argument("--backend", default="template",
                         choices=["template", "tesseract", "paddleocr"])
    odetect.set_defaults(func=_cmd_overlay_autodetect)

    track = sub.add_parser("track", help="detect + track robots, render debug video")
    track.add_argument("source")
    track.add_argument("--config", default="config.yaml")
    track.add_argument("--detector", choices=["color", "yolo"], default="color")
    track.add_argument("--fps", type=float, default=6.0)
    track.add_argument("--start", type=float, default=0.0)
    track.add_argument("--duration", type=float)
    track.add_argument("--debug-video", metavar="OUT.mp4",
                       help="write annotated video (boxes, IDs, alliance, state)")
    track.add_argument("--lineup", metavar="LINEUP.json",
                       help="6-team lineup (from `frcscout schedule fetch --json`); "
                            "enables bumper OCR + team assignment")
    track.add_argument("--bumper-backend", default="template",
                       choices=["template", "tesseract", "paddleocr"])
    track.set_defaults(func=_cmd_track)

    fieldp = sub.add_parser("field", help="field mapping tools")
    fsub = fieldp.add_subparsers(dest="field_command", required=True)
    locate = fsub.add_parser("locate", help="map a pixel to field coords + zones")
    locate.add_argument("--config", default="config.yaml")
    locate.add_argument("--pixel", required=True, metavar="X,Y")
    locate.set_defaults(func=_cmd_field_locate)

    scout = sub.add_parser("scout", help="run the full scouting pipeline on a match")
    scout.add_argument("source", help="local file, direct URL, or YouTube URL")
    scout.add_argument("--config", default="config.yaml")
    scout.add_argument("--match", help="match key (schedule fetched via APIs)")
    scout.add_argument("--lineup", metavar="LINEUP.json",
                       help="pre-fetched lineup file (skips schedule APIs)")
    scout.add_argument("--mode", choices=["replay", "live"], default="replay")
    scout.add_argument("--detector", choices=["color", "yolo"], default="color")
    scout.add_argument("--vlm", action="store_true",
                       help="enable Claude disambiguation on ambiguous events")
    scout.add_argument("--fps", type=float, default=6.0)
    scout.add_argument("--start", type=float, default=0.0)
    scout.add_argument("--duration", type=float)
    scout.add_argument("--out-dir", default="out")
    scout.add_argument("--debug-video", metavar="OUT.mp4")
    scout.add_argument("--run-to-eof", action="store_true",
                       help="keep processing after the match ends "
                            "(default: stop once post-match is detected)")
    scout.set_defaults(func=_cmd_scout)

    dataset = sub.add_parser("dataset", help="detector training-data tools")
    dsub = dataset.add_subparsers(dest="dataset_command", required=True)
    mine = dsub.add_parser("mine", help="mine footage into a YOLO dataset + label queue")
    mine.add_argument("source")
    mine.add_argument("--out", default="data/dataset")
    mine.add_argument("--config", default="config.yaml")
    mine.add_argument("--detector", choices=["color", "yolo"], default="color")
    mine.add_argument("--fps", type=float, default=2.0)
    mine.add_argument("--start", type=float, default=0.0)
    mine.add_argument("--duration", type=float)
    mine.add_argument("--low-conf", type=float, default=0.55,
                      help="detections below this queue the frame for human labeling")
    mine.add_argument("--pseudo-every", type=float, default=5.0,
                      help="seconds between pseudo-labeled keeps")
    mine.set_defaults(func=_cmd_dataset_mine)

    synth = dsub.add_parser("synth", help="generate a synthetic bootstrap dataset")
    synth.add_argument("--out", default="data/synth")
    synth.add_argument("--n", type=int, default=300)
    synth.add_argument("--seed", type=int, default=0)
    synth.set_defaults(func=_cmd_dataset_synth)

    push = sub.add_parser("push", help="push a match record to the Galaxia stack")
    push.add_argument("record", help="out/<match>.json")
    push.add_argument("--config", default="config.yaml")
    push.set_defaults(func=_cmd_push)

    crosscheck = sub.add_parser("crosscheck",
                                help="compare attributed points vs Statbotics EPA")
    crosscheck.add_argument("record")
    crosscheck.add_argument("--config", default="config.yaml")
    crosscheck.add_argument("--season", type=int, default=2026)
    crosscheck.set_defaults(func=_cmd_crosscheck)

    report = sub.add_parser("report", help="bilingual (en/he) markdown match report")
    report.add_argument("record")
    report.add_argument("--out-dir", default="out")
    report.add_argument("--langs", default="en,he")
    report.set_defaults(func=_cmd_report)

    ui = sub.add_parser("ui", help="launch the web dashboard")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=5000)
    ui.add_argument("--config", default="config.yaml")
    ui.add_argument("--out-dir", default="out")
    ui.add_argument("--debug", action="store_true")
    ui.set_defaults(func=_cmd_ui)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
