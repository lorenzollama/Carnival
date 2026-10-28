"""Steps 4-7: transcribe twice, reconcile in Python, take a closer look at every disagreement,
and check the result against what we know about this ad."""

import datetime as dt
import json
import re
import shutil
import unicodedata
from difflib import SequenceMatcher
from itertools import combinations

from . import ROOT, claude
from .prices import UNITS, Price

WINDOWS = ("full-week", "3-day", "friday", "weekend")
CELL = ("name", "spanish", "size", "price", "qty", "amount", "unit", "window", "coupon")
ITEMS_EXPECTED = (60, 110)  # non-coupon items on a whole ad: 73, 77 and 84 on the three test ads


class CheckFailed(ValueError):
    """The transcript contradicts what we know about this ad. Retrying won't help."""


# Step 4: two independent passes ----------------------------------------------------------------


def transcribe(work, manifest, pass_):
    """One pass: a Claude process that reads this pass's tiles and writes a JSON file per tile."""
    tiles = [t for t in manifest["tiles"] if t["pass"] == pass_]
    workdir = work / f"pass-{pass_}"
    (workdir / "tiles").mkdir(parents=True, exist_ok=True)
    lines = []
    for t in tiles:
        shutil.copy(work / "tiles" / f"{t['id']}.jpg", workdir / "tiles")
        page_height = manifest["pages"][t["page"] - 1]["height"]
        lines.append(
            f"| `tiles/{t['id']}.jpg` | {manifest['width']} x {t['bottom'] - t['top']} | page {t['page']}, "
            f"rows {t['top']}-{t['bottom']} of {page_height} | `{t['id']}.json` |"
        )
    inputs = (
        "## This run\n\nRead the tiles in this order. Each row gives the tile's size in pixels and where it "
        "sits on its page.\n\n| Tile | Size | Position | Write |\n|---|---|---|---|\n" + "\n".join(lines) + "\n"
    )
    by_file = {f"{t['id']}.json": t for t in tiles}
    results, usage = claude.run(
        "transcribe", workdir, list(by_file), lambda f, data: check_tile(data, by_file[f], manifest["width"]), inputs
    )
    return {"tiles": list(results.values()), "usage": usage}


def check_tile(data, tile, width):
    if data.get("tile") != tile["id"]:
        raise ValueError(f'"tile" must be "{tile["id"]}"')
    height = tile["bottom"] - tile["top"]
    if data["header"] is not None:
        _dates(data["header"]["start"], data["header"]["end"])
        _text(data["header"], "text")
    if data["calendar"] is not None:
        _dates(data["calendar"]["start"], data["calendar"]["end"])
    for banner in data["banners"]:
        if banner["window"] not in WINDOWS[1:] or not banner["dates"]:
            raise ValueError(f"bad banner {banner}")
        _dates(*banner["dates"])
    for cell in data["cells"]:
        _box(cell, width, height)
        _text(cell, "name", "price")
        _text(cell, "spanish", "size", empty=True)
        if not (isinstance(cell["qty"], int) and cell["qty"] >= 1 and isinstance(cell["amount"], (int, float))):
            raise ValueError(f"bad qty/amount in {cell['name']!r}")
        if cell["amount"] <= 0 or cell["unit"] not in UNITS or cell["window"] not in WINDOWS:
            raise ValueError(f"bad amount, unit, or window in {cell['name']!r}")
        if not isinstance(cell["coupon"], bool):
            raise ValueError(f"coupon must be true or false in {cell['name']!r}")
    for spot in data["unreadable"]:
        _box(spot, width, height)
        _text(spot, "legible", "problem")


def _box(obj, width, height):
    box = obj["box"]
    if not (len(box) == 4 and all(isinstance(v, int) for v in box)):
        raise ValueError(f"box must be four integers: {box}")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= width + 2 and 0 <= y0 < y1 <= height + 2):
        raise ValueError(f"box {box} is not inside the {width} x {height} tile")


def _text(obj, *keys, empty=False):
    for k in keys:
        if not isinstance(obj[k], str) or not (empty or obj[k].strip()):
            raise ValueError(f'"{k}" must be {"a" if empty else "a non-empty"} string')


def _dates(*isodates):
    for d in isodates:
        dt.date.fromisoformat(d)


# Step 5: reconcile ------------------------------------------------------------------------------


def readings(passes, manifest):
    """Every cell and unreadable spot from both passes, placed on its page."""
    tiles = {t["id"]: t for t in manifest["tiles"]}
    found = []
    for p in passes:
        for data in p["tiles"]:
            t = tiles[data["tile"]]
            for kind in ("cells", "unreadable"):
                for r in data[kind]:
                    x0, y0, x1, y1 = r["box"]
                    found.append(
                        {**r, "readable": kind == "cells", "pass": t["pass"], "tile": t["id"], "page": t["page"],
                         "at": [x0, y0 + t["top"], x1, y1 + t["top"]],
                         "margin": min(y0, t["bottom"] - t["top"] - y1)}  # distance from the tile's edge
                    )  # fmt: skip
    return found


def group(found):
    """Gather the readings of each ad cell: same page, overlapping boxes, similar text.

    A tile shows each cell at most once, so a group never takes two readings from one tile.
    Pairs merge best-first, which keeps a sloppy box from pulling in a neighboring cell.
    """
    pairs = []
    for i, j in combinations(range(len(found)), 2):
        r, s = found[i], found[j]
        if r["page"] == s["page"] and r["tile"] != s["tile"] and (o := _overlap(r["at"], s["at"])) >= 0.3:
            score = o + SequenceMatcher(None, normalize(_text_of(r)), normalize(_text_of(s))).ratio()
            if score >= 1.0:
                pairs.append((score, i, j))
    groups = [{i} for i in range(len(found))]
    where = list(range(len(found)))  # reading -> its group
    for _, i, j in sorted(pairs, reverse=True):
        gi, gj = where[i], where[j]
        if gi == gj or {found[k]["tile"] for k in groups[gi]} & {found[k]["tile"] for k in groups[gj]}:
            continue
        for k in groups[gj]:
            where[k] = gi
        groups[gi] |= groups[gj]
        groups[gj] = set()
    return [[found[k] for k in sorted(g)] for g in groups if g]


def _overlap(a, b):
    """Intersection over the smaller box: 1 when one box holds the other."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def _text_of(r):
    return r["name"] if r["readable"] else r["legible"]


def normalize(text):
    """What a name says, for comparing: no case, accents, punctuation, or "or"."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join(w for w in re.sub(r"[^\w¢$.?]+", " ", text).split() if w not in ("or", "and"))


def settle(readings_of_cell):
    """Return (the reading to keep, None) if both passes agree, else (None, why it's disputed)."""
    seen = {r["pass"] for r in readings_of_cell}
    if seen != {"a", "b"}:
        return None, f"only pass {''.join(seen).upper()} found it"
    if not all(r["readable"] for r in readings_of_cell):
        return None, "marked unreadable"
    for r in readings_of_cell:
        printed = Price.parse(r["price"])
        if printed and printed != _price(r):
            return None, f"printed price {r['price']!r} doesn't match its parsed form"
    differ = [field for field, key in MUST_MATCH.items() if len({key(r) for r in readings_of_cell}) > 1]
    if differ:
        return None, f"{', '.join(differ)} differ"
    return max(readings_of_cell, key=lambda r: r["margin"]), None


def _price(r):
    return Price(r["qty"], round(r["amount"] * 100), r["unit"])


MUST_MATCH = {  # what has to match for two readings to agree
    "name": lambda r: normalize(r["name"]),
    "price": _price,
    "window": lambda r: r["window"],
    "size": lambda r: tuple(re.findall(r"\d+(?:\.\d+)?", r["size"])),  # the numbers are what matter
    "coupon": lambda r: r["coupon"],
}


def disputes(groups):
    """The groups that need a closer look, with the reason, in page order."""
    out = []
    for g in groups:
        keep, why = settle(g)
        if why:
            out.append((g, why))
    return sorted(out, key=lambda d: (d[0][0]["page"], min(r["at"][1] for r in d[0])))


# Step 6: resolve ---------------------------------------------------------------------------------


def resolve(work, manifest, cases):
    """A closer look at every disputed cell: one Claude process, a crop per dispute.

    Each crop comes from the original page, enlarged twice as much as the tiles were. When the
    readings point at very different places, the crop falls back to the whole tile.
    """
    from . import pages  # Pillow: installed only when there is an ad to process

    workdir = work / "resolve"
    (workdir / "crops").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "prompts" / "transcribe.md", workdir)  # the readers' field conventions
    listed = []
    for n, (readings_of_cell, why) in enumerate(cases, 1):
        case_id = f"d{n:02d}"
        boxes = [r["at"] for r in readings_of_cell]
        box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        crop = workdir / "crops" / f"{case_id}.jpg"
        if (box[3] - box[1]) > manifest["height"] / 2:
            best = max(readings_of_cell, key=lambda r: r["margin"])
            shutil.copy(work / "tiles" / f"{best['tile']}.jpg", crop)
        else:
            pages.crop(manifest, work / "pages", readings_of_cell[0]["page"], box, crop)
        listed.append(
            {"id": case_id, "page": readings_of_cell[0]["page"], "box": box, "why": why, "crop": f"crops/{case_id}.jpg",
             "readings": [{k: r[k] for k in ("pass", *(CELL if r["readable"] else ("legible", "problem")))} for r in readings_of_cell]}
        )  # fmt: skip
    (workdir / "disputes.json").write_text(json.dumps(listed, indent=2, ensure_ascii=False))
    ids = [c["id"] for c in listed]
    results, usage = claude.run("resolve", workdir, ["resolutions.json"], lambda f, data: check_resolutions(data, ids))
    verdicts = {v["id"]: v for v in results["resolutions.json"]}
    return [{**case, "verdict": verdicts[case["id"]]} for case in listed], usage


def check_resolutions(data, ids):
    if sorted(v["id"] for v in data) != sorted(ids):
        raise ValueError(f"expected exactly one verdict for each of {', '.join(ids)}")
    for v in data:
        _text(v, "note")
        if v["verdict"] == "item":
            cell = v["cell"]
            _text(cell, "name", "price")
            _text(cell, "spanish", "size", empty=True)
            if not (isinstance(cell["qty"], int) and cell["qty"] >= 1 and cell["amount"] > 0):
                raise ValueError(f"{v['id']}: bad qty or amount")
            if cell["unit"] not in UNITS or cell["window"] not in WINDOWS or not isinstance(cell["coupon"], bool):
                raise ValueError(f"{v['id']}: bad unit, window, or coupon")
        elif v["verdict"] == "unreadable":
            _text(v, "legible", "problem")
        elif v["verdict"] != "not-an-item":
            raise ValueError(f'{v["id"]}: verdict must be "item", "unreadable", or "not-an-item"')


# Putting it together -------------------------------------------------------------------------------


def assemble(passes, groups, resolved):
    """The reconciled transcript: every item on the ad, and how each was settled."""
    items, unreadable = [], []
    for g in groups:
        keep, why = settle(g)
        if keep:
            items.append({"page": keep["page"], "box": keep["at"], **{k: keep[k] for k in CELL},
                          "how": f"both passes agree ({len(g)} readings)"})  # fmt: skip
    for case in resolved:
        v = case["verdict"]
        if v["verdict"] == "item":
            items.append({"page": case["page"], "box": case["box"], **{k: v["cell"][k] for k in CELL},
                          "how": f"resolved ({case['why']}): {v['note']}"})  # fmt: skip
        elif v["verdict"] == "unreadable":
            unreadable.append({"page": case["page"], "box": case["box"], "legible": v["legible"],
                               "problem": v["problem"], "how": f"unreadable ({case['why']}): {v['note']}"})  # fmt: skip
    for kind, rows in (("i", items), ("u", unreadable)):
        rows.sort(key=lambda r: (r["page"], r["box"][1] // 40, r["box"][0]))  # reading order, row by row
        for n, row in enumerate(rows, 1):
            row["id"] = f"{kind}{row['page']}-{n:02d}"
    return {**dates(passes), "coupons": sum(i["coupon"] for i in items), "items": items, "unreadable": unreadable}


def dates(passes):
    """The ad week and the sale windows, which both passes must read the same way.

    The week comes from the calendar strip in the footer when there is one: if it disagrees with
    the header, the header is the likelier typo.
    """
    seen, notes = [], []
    for p in passes:
        header = next(((t["header"]["start"], t["header"]["end"]) for t in p["tiles"] if t["header"]), None)
        calendar = next(((t["calendar"]["start"], t["calendar"]["end"]) for t in p["tiles"] if t["calendar"]), None)
        windows = {}
        for t in p["tiles"]:
            for b in t["banners"]:
                windows.setdefault(b["window"], sorted(b["dates"]))
        seen.append((calendar or header, windows))
        if header and calendar and header != calendar:
            notes.append(f"header reads {header[0]} to {header[1]}, calendar strip {calendar[0]} to {calendar[1]}")
    if seen[0] != seen[1]:
        raise CheckFailed(f"the two passes read the dates differently: A {seen[0]}, B {seen[1]}")
    week, windows = seen[0]
    if not week:
        raise CheckFailed("neither pass found the ad's dates")
    return {"week": {"start": week[0], "end": week[1], "note": "; ".join(sorted(set(notes)))}, "windows": windows}


# Step 7: check -----------------------------------------------------------------------------------------


def check(transcript, last_week=None):
    """Everything we can verify without looking at the ad again. Raises CheckFailed."""
    problems = []
    start, end = (dt.date.fromisoformat(transcript["week"][k]) for k in ("start", "end"))
    if start.weekday() != 1 or end - start != dt.timedelta(days=6):
        problems.append(f"the week {start:%a %b %d} to {end:%a %b %d} isn't Tuesday to Monday")
    previous = None
    for window in WINDOWS[1:]:
        days = [dt.date.fromisoformat(d) for d in transcript["windows"].get(window, [])]
        if not days:
            if any(i["window"] == window for i in transcript["items"]):
                problems.append(f"items are marked {window}, but no {window} banner dates were read")
            continue
        if not all(start <= d <= end for d in days):
            problems.append(f"the {window} dates fall outside the ad week")
        if previous and days[0] <= previous:
            problems.append(f"the {window} sale doesn't come after the one before it")
        previous = days[-1]
    count = sum(not i["coupon"] for i in transcript["items"])
    low, high = ITEMS_EXPECTED
    if not low <= count <= high:
        problems.append(f"{count} items is outside the {low}-{high} a full ad carries")
    if last_week and start < dt.date.fromisoformat(last_week):
        problems.append(f"this ad ({start}) is older than the last one processed ({last_week})")
    if problems:
        raise CheckFailed("; ".join(problems))


def day_tag(transcript, window, long=False):
    """ "Tue–Thu", "Fri", "Sat–Sun" from the window's dates; "Friday" when long; "" all week."""
    days = transcript["windows"].get(window)
    if window == "full-week" or not days:
        return "all week" if long else ""
    first, last = (dt.date.fromisoformat(d) for d in (days[0], days[-1]))
    if first == last:
        return f"{first:%A}" if long else f"{first:%a}"
    return f"{first:%a}–{last:%a}"
