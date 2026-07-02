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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
