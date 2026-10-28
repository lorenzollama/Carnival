"""Compare tile settings: how often the two passes agree, and how often they're wrong.

    python tools/evaluate.py tests/fixtures/2026-10-27.pdf --width 1400 --height 1050 --overlap 500

Runs both transcription passes (cached under work/eval/) and reports how many cells the passes
agree on. If tests/golden/ has a reference transcription of the ad, it also scores each pass
against it, and counts the worst kind of error: one both passes made identically, which
reconciliation can't catch because nothing disagrees.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from carnival import ROOT, pages, transcribe  # noqa: E402
from carnival.prices import Price  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--overlap", type=int, required=True)
    args = parser.parse_args()

    work = ROOT / "work" / "eval" / f"{args.source.stem}-w{args.width}-h{args.height}-o{args.overlap}"
    manifest = pages.tile(pages.extract(args.source, work / "pages"), work / "tiles", args.width, args.height, args.overlap)
    missing = [p for p in "ab" if not (work / f"pass-{p}.json").exists()]
    with ThreadPoolExecutor(2) as pool:
        for p, result in zip(missing, pool.map(lambda p: transcribe.transcribe(work, manifest, p), missing)):
            (work / f"pass-{p}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    passes = [json.loads((work / f"pass-{p}.json").read_text()) for p in "ab"]

    groups = transcribe.group(transcribe.readings(passes, manifest))
    settled = [(g, *transcribe.settle(g)) for g in groups]
    agreed = [keep for _, keep, why in settled if keep]
    report = {
        "source": args.source.name, "width": args.width, "height": args.height, "overlap": args.overlap,
        "tiles": {p: sum(t["pass"] == p for t in manifest["tiles"]) for p in "ab"},
        "seconds": {p: sum(u["seconds"] for u in passes[i]["usage"]) for i, p in enumerate("ab")},
        "cells": len(groups), "agreed": len(agreed),
        "disputes": sorted(why for _, keep, why in settled if why),
    }  # fmt: skip
    golden_path = ROOT / "tests" / "golden" / f"{args.source.stem[:10]}.json"  # by date: one ad, any format
    if golden_path.exists():
        golden = json.loads(golden_path.read_text())["items"]
        for i, p in enumerate("ab"):
            report[f"pass {p}"] = score(single_pass(passes[i], manifest), golden)
        report["agreed but wrong"] = score(agreed, golden)["wrong"]
    (work / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


def single_pass(pass_, manifest):
    """One pass's own reading of each cell: the most central of its repeats."""
    groups = transcribe.group(transcribe.readings([pass_], manifest))
    return [max((r for r in g if r["readable"]), key=lambda r: r["margin"]) for g in groups if any(r["readable"] for r in g)]


def similarity(a, b):
    """How alike two names are; a shortened name ("Chicken Leg Meat") still matches its whole."""
    a, b = transcribe.normalize(a), transcribe.normalize(b)
    shorter, longer = sorted((set(a.split()), set(b.split())), key=len)
    return max(SequenceMatcher(None, a, b).ratio(), len(shorter & longer) / len(shorter) if shorter else 0)


def score(items, golden):
    """Match transcribed items to golden ones by page and name; list every field that's wrong.

    A size the reader marked with "?" counts as uncertain, not wrong: it said what it couldn't
    read. Golden sizes recorded as null were too degraded to be sure of, and aren't scored.
    """
    pairs = sorted(
        ((similarity(g["name"], t["name"]), gi, ti)
         for gi, g in enumerate(golden) for ti, t in enumerate(items) if g["page"] == t["page"]),
        reverse=True,
    )  # fmt: skip
    matched, used = {}, set()
    for ratio, gi, ti in pairs:
        if ratio >= 0.6 and gi not in matched and ti not in used:
            matched[gi], used = ti, used | {ti}
    wrong, uncertain = [], []
    for gi, ti in matched.items():
        g, t = golden[gi], items[ti]
        fields = []
        if Price(g["qty"], round(g["amount"] * 100), g["unit"]) != Price(t["qty"], round(t["amount"] * 100), t["unit"]):
            fields.append(f"price {t['price']!r}, not {g['price']!r}")
        if g["window"] != t["window"]:
            fields.append(f"window {t['window']}, not {g['window']}")
        if g["coupon"] != t["coupon"]:
            fields.append("coupon flag")
        if g["size"] is not None and transcribe.MUST_MATCH["size"](g) != transcribe.MUST_MATCH["size"](t):
            if "?" in t["size"]:
                uncertain.append(f"{g['name']}: size {t['size']!r}, not {g['size']!r}")
            else:
                fields.append(f"size {t['size']!r}, not {g['size']!r}")
        if fields:
            wrong.append(f"{g['name']}: " + "; ".join(fields))
    return {
        "found": len(matched),
        "missing": [g["name"] for gi, g in enumerate(golden) if gi not in matched],
        "extra": [t["name"] for ti, t in enumerate(items) if ti not in used],
        "wrong": wrong,
        "uncertain": uncertain,
    }


if __name__ == "__main__":
    main()
