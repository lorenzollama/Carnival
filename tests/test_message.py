import os
from pathlib import Path

from carnival import message

SNAPSHOT = Path(__file__).parent / "snapshots" / "message.html"

WINDOWS = {"3-day": ["2026-09-29", "2026-09-30", "2026-10-01"], "friday": ["2026-10-02"], "weekend": ["2026-10-03", "2026-10-04"]}


def item(item_id, price, qty, amount, unit, window="full-week", name=""):
    return {"id": item_id, "name": name, "size": "", "price": price, "qty": qty, "amount": amount, "unit": unit,
            "window": window, "coupon": False}  # fmt: skip


def deal(item_id, section, name, g_per_dollar=None, kept=True):
    return {"id": item_id, "kept": kept, "section": section, "name": name, "g_per_dollar": g_per_dollar, "options": []}


TRANSCRIPT = {
    "week": {"start": "2026-09-29", "end": "2026-10-05", "note": ""},
    "windows": WINDOWS,
    "items": [
        item("i1", "89¢ LB.", 1, 0.89, "lb", "friday"),
        item("i2", "$2.99 LB.", 1, 2.99, "lb"),
        item("i3", "$2.99 LB.", 1, 2.99, "lb", "weekend"),
        item("i4", "2 LBS $1", 2, 1.00, "lb"),
        item("i5", "79¢ EA.", 1, 0.79, "each", "3-day"),
        item("i6", "3 FOR $5", 3, 5.00, "each"),
        item("i7", "$7.99", 1, 7.99, "package"),
        item("i8", "$16.99 +CRV", 1, 16.99, "package"),
    ],
    "unreadable": [{"page": 1, "box": [0, 0, 10, 10], "legible": "Sun Vista beans, $2.99", "problem": "size line illegible"}],
}
JUDGED = [
    deal("i1", "protein", "Chicken drumsticks", 63),
    deal("i2", "protein", "Chicken breast, boneless", 34),
    deal("i3", "protein", "Chicken fajitas", 27),
    deal("i4", "produce", "Oranges, bananas or yellow onions"),
    deal("i5", "produce", "Large avocados"),
    deal("i6", "pantry", "Chicken of the Sea tuna & El Pato sauce"),
    deal("i7", "pantry", "Mazola oil"),
    deal("i8", "cut", "Modelo beer", kept=False),
]
PICKS = [{"id": "i1", "label": "Drumsticks"}, {"id": "i2", "label": "chicken breast"}]


def render(**changes):
    return message.render(TRANSCRIPT, JUDGED, changes.get("picks", PICKS), "https://github.com/example/data/2026-09-29/source.pdf")


def test_snapshot():
    html = render()
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(html + "\n")
    assert html + "\n" == SNAPSHOT.read_text()


def test_lock_screen_lines():
    first, second = render().split("\n")[:2]
    assert first == "<b>Carnival · Sep 29 – Oct 5</b>"
    assert second == "Drumsticks 89¢/lb Friday · chicken breast $2.99/lb all week"


def test_headline_falls_back_to_the_best_protein_per_dollar():
    for picks in ([{"id": "i8", "label": "Beer"}], [{"id": "i2", "label": "breast at $1.99"}], []):
        assert render(picks=picks).split("\n")[1] == "Chicken drumsticks 89¢/lb Friday"


def test_nothing_kept():
    html = message.render({**TRANSCRIPT, "unreadable": []}, [deal("i8", "cut", "Modelo beer", kept=False)], [], "https://x")
    assert html.split("\n")[1] == "Nothing on this week's ad fits your rules."


def test_week_labels():
    assert message.week_label("2026-09-08") == "Sep 8 – 14"
    assert message.week_label("2026-10-27", year=True) == "Oct 27 – Nov 2, 2026"


def test_stays_under_telegrams_limit():
    many = {**TRANSCRIPT, "items": [item(f"x{n}", "$1.29 LB.", 1, 1.29, "lb") for n in range(400)]}
    deals = [deal(f"x{n}", "pantry", f"An item with a reasonably long name, number {n}") for n in range(400)]
    html = message.render(many, deals, [], "https://x")
    assert message.visible_length(html) <= message.LIMIT
    assert "more in the full ad" in html
