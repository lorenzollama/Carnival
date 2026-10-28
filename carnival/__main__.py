"""python -m carnival [run | check | process] [--source URL] [--force] [--dry-run [--file PATH]]"""

import argparse
import os

from . import run


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m carnival",
        description="Read Carnival's weekly ad, keep the deals that fit diet.md, and send them to Telegram.",
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=("run", "check", "process"),
        help="run: check, then process if there's a new ad (the default). "
        "check: the cheap hourly step. process: the pipeline, on data/pending.",
    )  # fmt: skip
    parser.add_argument(
        "--source", metavar="URL", default=os.environ.get("SOURCE_URL") or None,
        help="the ad's PDF, the texted sf0.co link, or an image, instead of the store's PDF",
    )  # fmt: skip
    parser.add_argument(
        "--force", action="store_true", default=os.environ.get("FORCE") == "true",
        help="process the ad even if this exact file was processed before",
    )  # fmt: skip
    parser.add_argument("--dry-run", action="store_true", help="work in work/dry-run and print the message: no commits, nothing sent")
    parser.add_argument("--file", metavar="PATH", help="a local copy of an ad, for --dry-run")
    args = parser.parse_args(argv)

    if args.dry_run:
        folder = run.WORK / "dry-run"
        run.stage(folder, args.source, args.force, path=args.file, history=False)
        print("\n" + run.process(folder, dry_run=True))
        return
    if args.file:
        parser.error("--file only works with --dry-run")
    if args.command in ("run", "check"):
        ready = run.check(args.source, args.force)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as out:
                out.write(f"process={str(ready).lower()}\n")
        if args.command == "check" or not ready:
            return
    run.process()


if __name__ == "__main__":
    main()
