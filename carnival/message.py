"""Step 9: the Telegram message, rendered from JSON with no judgment left to make.

The first two lines are what a lock screen shows: the ad week, then the headline. Protein is
listed in full, best grams of protein per dollar first; produce and pantry fold into expandable
quotes. Anything that couldn't be read is listed last, and a photo of each spot follows.
"""

import datetime as dt
import re
from html import escape, unescape

from .prices import Price
from .transcribe import day_tag

LIMIT = 4096  # Telegram's, counted after the HTML is parsed


def week_label(start, year=False):
    """ "Sep 8 – 14", "Sep 29 – Oct 5", with ", 2026" if asked."""
    first = dt.date.fromisoformat(start)
    last = first + dt.timedelta(days=6)
    text = f"{first:%b} {first.day} – " + (f"{last.day}" if last.month == first.month else f"{last:%b} {last.day}")
    return text + (f", {last.year}" if year else "")


def lines(transcript, judged):
    """The kept items by section, as rendered lines, in message order."""
    items = {i["id"]: i for i in transcript["items"]}
    out = {"protein": [], "produce": [], "pantry": []}
    for deal in judged:
        if not deal["kept"]:
            continue
        item = items[deal["id"]]
        tag = day_tag(transcript, item["window"])
        parts = [str(_price(item))]
        if deal["section"] == "protein" and deal["g_per_dollar"]:
            parts.append(f"{deal['g_per_dollar']} g/$")
        if tag:
            parts.append(f"<i>{tag}</i>")
        text = f"{escape(deal['name'], quote=False)} — " + " · ".join(parts)
        if deal["section"] == "protein":
            key = (-(deal["g_per_dollar"] or 0), deal["name"])
        else:
            key = (item["window"] == "full-week", (transcript["windows"].get(item["window"]) or [""])[0], deal["name"])
        out[deal["section"]].append((key, text))
    return {section: [text for _, text in sorted(rows)] for section, rows in out.items()}


def headline(transcript, judged, picks):
    """Claude's one or two standout picks, priced by us: "Drumsticks 89¢/lb Friday · …".

    A pick must be a kept item and its label can't carry numbers or prices of its own, so the
    headline can only ever quote a printed price. Otherwise: the best protein per dollar.
    """
    kept = {d["id"]: d for d in judged if d["kept"]}
    items = {i["id"]: i for i in transcript["items"]}
    valid = 0 < len(picks) <= 2 and all(
        p["id"] in kept and 0 < len(p["label"]) <= 40 and not re.search(r"[\d$¢<>&]", p["label"]) for p in picks
    )
    if not valid:
        ranked = sorted(kept.values(), key=lambda d: (d["section"] != "protein", -(d["g_per_dollar"] or 0)))
        picks = [{"id": ranked[0]["id"], "label": ranked[0]["name"]}] if ranked else []
    text = " · ".join(
        f"{p['label']} {_price(items[p['id']])} {day_tag(transcript, items[p['id']]['window'], long=True)}" for p in picks
    )
    return escape(text[:1].upper() + text[1:], quote=False)


def render(transcript, judged, picks, full_ad, revised=False):
    """The whole message as Telegram HTML."""
    by_section = lines(transcript, judged)
    out = [f"<b>Carnival · {week_label(transcript['week']['start'])}{' (revised)' if revised else ''}</b>"]
    if any(by_section.values()):
        out.append(headline(transcript, judged, picks))
    else:
        out.append("Nothing on this week's ad fits your rules.")
    if by_section["protein"]:
        out += ["", "<b>Protein</b><i> · grams of protein per $</i>", *by_section["protein"]]
    folded = [s for s in ("produce", "pantry") if by_section[s]]
    if folded:
        out.append("")
    for section in folded:
        rows = by_section[section]
        out += [f"<b>{section.title()} ({len(rows)})</b>", "<blockquote expandable>" + "\n".join(rows) + "</blockquote>"]
    out += ["", *unreadable(transcript), f'<a href="{escape(full_ad)}">Full ad</a>']
    html = "\n".join(out)
    while visible_length(html) > LIMIT:  # never, at today's ad sizes; but never fail to send
        html = _shorten(html)
    return html


def unreadable(transcript):
    spots = transcript["unreadable"]
    if not spots:
        return []
    describe = [escape(f"{s['legible']}, {s['problem']}", quote=False) for s in spots]
    if len(spots) == 1:
        return [f"⚠️ 1 item couldn't be read: {describe[0]}. Photo below."]
    return [f"⚠️ {len(spots)} items couldn't be read. Photos below.", *describe]


def captions(transcript):
    return [f"{s['legible']}, {s['problem']}" for s in transcript["unreadable"]]


def visible_length(html):
    return len(unescape(re.sub(r"<[^>]+>", "", html)).encode("utf-16-le")) // 2


def _shorten(html):
    """Drop the last line of the longest folded list, counting what's been left out."""
    quotes = re.findall(r"<blockquote expandable>(.*?)</blockquote>", html, re.S)
    if not quotes:
        raise ValueError("message is over Telegram's limit with nothing left to fold")
    longest = max(quotes, key=len)
    rows = longest.split("\n")
    hidden = int(rows.pop()[1:].split()[0]) if rows[-1].startswith("+") else 0
    return html.replace(longest, "\n".join(rows[:-1] + [f"+{hidden + 1} more in the full ad"]), 1)


def _price(item):
    return Price(item["qty"], round(item["amount"] * 100), item["unit"])
