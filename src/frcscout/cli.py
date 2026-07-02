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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
