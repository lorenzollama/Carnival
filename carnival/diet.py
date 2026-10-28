"""Step 8: the diet. Claude sorts each item against diet.md; Python applies the numbers.

Claude decides what an item is (protein, produce, pantry, or cut, and which row of
nutrition.csv describes it). Protein figures come only from that table, and the protein rule
and grams of protein per dollar are computed here, never by the model.
"""

import csv
import json
import shutil

from . import ROOT, claude
from .prices import Price, package_lb

SECTIONS = ("protein", "produce", "pantry", "cut")
GRAMS_PER_LB = 453.592
COLUMNS = ("key", "food", "fdc_id", "protein_g", "kcal", "yield", "collagen", "verified", "note")


def rules():
    """diet.md's front matter: the numbers the code uses."""
    front = (ROOT / "diet.md").read_text().split("---")[1]
    values = {}
    for line in front.splitlines():
        key, _, value = line.split("#")[0].partition(":")
        if value.strip():
            v = value.strip().lower()
            values[key.strip()] = v == "true" if v in ("true", "false") else float(v)
    return values


def nutrition():
    with open(ROOT / "nutrition.csv", newline="") as f:
        return {row["key"]: typed(row) for row in csv.DictReader(f)}


def typed(row):
    return {**row, "fdc_id": int(row["fdc_id"]), "protein_g": float(row["protein_g"]), "kcal": float(row["kcal"]),
            "yield": float(row["yield"]), "collagen": str(row["collagen"]) in ("1", "True", "true")}  # fmt: skip


def candidates(transcript, settings):
    """The items worth sorting: everything readable, minus the $30-minimum coupons if skipped."""
    return [i for i in transcript["items"] if not (i["coupon"] and settings["skip_min_purchase_coupons"])]


def sort(work, transcript, settings):
    """One Claude process: classify every item, map protein to nutrition rows, pick a headline."""
    workdir = work / "filter"
    workdir.mkdir(parents=True, exist_ok=True)
    for name in ("diet.md", "nutrition.csv"):
        shutil.copy(ROOT / name, workdir)
    items = [{"id": i["id"], "name": i["name"], "spanish": i["spanish"], "size": i["size"],
              "price": str(Price(i["qty"], round(i["amount"] * 100), i["unit"])), "window": i["window"]}
             for i in candidates(transcript, settings)]  # fmt: skip
    (workdir / "items.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    table = nutrition()
    ids = [i["id"] for i in items]
    results, usage = claude.run("filter", workdir, ["filter.json"], lambda f, data: check(data, ids, table))
    return results["filter.json"], usage


def check(data, ids, table):
    if sorted(e["id"] for e in data["items"]) != sorted(ids):
        raise ValueError("every item in items.json needs exactly one entry")
    proposed = {}
    for row in data["new_nutrition"]:
        if row["key"] in table or not all(k in row for k in COLUMNS[:7]):
            raise ValueError(f"new nutrition row {row.get('key')!r} needs a new key and every column")
        if not (0 < float(row["protein_g"]) < 100 and 0 < float(row["kcal"]) < 900 and 0 < float(row["yield"]) <= 1):
            raise ValueError(f"new nutrition row {row['key']!r} has impossible numbers")
        proposed[row["key"]] = row
    for entry in data["items"]:
        if not entry["options"]:
            raise ValueError(f"{entry['id']} has no options")
        for option in entry["options"]:
            if not option["name"].strip() or option["section"] not in SECTIONS:
                raise ValueError(f"{entry['id']}: every option needs a name and a section from {SECTIONS}")
            if option["section"] == "protein" and option.get("nutrition") not in {**table, **proposed}:
                raise ValueError(f"{entry['id']}: protein option {option['name']!r} needs a nutrition row")
            if option["section"] == "cut" and not option.get("reason", "").strip():
                raise ValueError(f"{entry['id']}: cut option {option['name']!r} needs a reason")
    for pick in data["headline"]:
        if pick["id"] not in ids or not isinstance(pick["label"], str):
            raise ValueError(f"headline pick {pick} must name an item id and a label")


def judge(transcript, sorted_items, table, settings):
    """Apply the protein rule and the protein-per-dollar math to Claude's sorting.

    Every option keeps what Claude said and gains a verdict. An item is kept if any option is;
    its grams per dollar is that of its least favorable kept protein option, and left out
    altogether if any of them can't be computed.
    """
    items = {i["id"]: i for i in transcript["items"]}
    judged = []
    for entry in sorted_items["items"]:
        item = items[entry["id"]]
        price = Price(item["qty"], round(item["amount"] * 100), item["unit"])
        options = []
        for option in entry["options"]:
            o = {**option, "verdict": "cut" if option["section"] == "cut" else "keep"}
            if option["section"] == "cut":
                o["why"] = option["reason"]
            elif option["section"] == "protein":
                row = table[option["nutrition"]]
                o["g_per_100kcal"] = round(row["protein_g"] / row["kcal"] * 100, 1)
                if row["collagen"]:
                    o["verdict"], o["why"] = "cut", "collagen-dominant"
                elif o["g_per_100kcal"] < settings["protein_min_g_per_100kcal"]:
                    o["verdict"], o["why"] = "cut", f"protein rule: {o['g_per_100kcal']} g per 100 kcal"
                else:
                    o["g_per_dollar"] = grams_per_dollar(row, price, item["size"])
            options.append(o)
        kept = [o for o in options if o["verdict"] == "keep"]
        metrics = [o.get("g_per_dollar") for o in kept if o["section"] == "protein"]
        judged.append({
            "id": entry["id"],
            "kept": bool(kept),
            "section": kept[0]["section"] if kept else "cut",
            "name": _sentence(_listed([o["name"] for o in kept])) if kept else item["name"],
            "g_per_dollar": min(metrics) if metrics and None not in metrics else None,
            "options": options,
        })  # fmt: skip
    return judged


def grams_per_dollar(row, price, size):
    """453.592 x yield x (protein per 100 g / 100) / price per lb, or None without a weight."""
    per_lb = price.per_unit
    if price.unit != "lb":
        pounds = package_lb(size)
        if not pounds:
            return None
        per_lb /= pounds
    return round(GRAMS_PER_LB * row["yield"] * row["protein_g"] / 100 / per_lb)


def _listed(names):
    """"A", "A or B", "A, B or C"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _sentence(text):
    return text[:1].upper() + text[1:]


def add_rows(rows):
    """Append Claude's proposed nutrition rows to nutrition.csv, marked unverified."""
    with open(ROOT / "nutrition.csv", "a", newline="") as f:
        writer = csv.DictWriter(f, COLUMNS)
        for row in rows:
            writer.writerow({**{k: row.get(k, "") for k in COLUMNS}, "collagen": int(bool(row["collagen"])),
                             "verified": "no", "note": row.get("note") or "proposed by Claude; check the FDC ID"})  # fmt: skip
