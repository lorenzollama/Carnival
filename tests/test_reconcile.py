import pytest

from carnival import transcribe

# One page, 1000 px wide. Pass A cut it at 0-1000 and 700-1700; pass B, offset, at 0-850 and 350-1350.
MANIFEST = {
    "width": 1000,
    "tiles": [
        {"id": "a1-1", "pass": "a", "page": 1, "top": 0, "bottom": 1000},
        {"id": "a1-2", "pass": "a", "page": 1, "top": 700, "bottom": 1700},
        {"id": "b1-1", "pass": "b", "page": 1, "top": 0, "bottom": 850},
        {"id": "b1-2", "pass": "b", "page": 1, "top": 350, "bottom": 1350},
    ],
}


def cell(box, name, price="$1.29 LB.", amount=1.29, unit="lb", **fields):
    return {"box": box, "name": name, "spanish": "", "size": "", "price": price, "qty": 1, "amount": amount,
            "unit": unit, "window": "full-week", "coupon": False, **fields}  # fmt: skip


def tile(tile_id, cells=(), unreadable=()):
    return {"tile": tile_id, "header": None, "calendar": None, "banners": [], "cells": list(cells), "unreadable": list(unreadable)}


def grouped(a_tiles, b_tiles):
    found = transcribe.readings([{"tiles": a_tiles}, {"tiles": b_tiles}], MANIFEST)
    return transcribe.group(found)


def test_agreeing_readings_form_one_cell_even_with_sloppy_boxes():
    groups = grouped(
        [tile("a1-1", [cell([0, 100, 250, 300], "Roma Tomatoes or Limes")])],
        [tile("b1-1", [cell([12, 90, 260, 330], "Roma Tomatoes or Limes")])],
    )
    assert len(groups) == 1
    keep, why = transcribe.settle(groups[0])
    assert why is None and keep["name"] == "Roma Tomatoes or Limes"


def test_repeats_in_overlapping_tiles_merge_and_the_most_central_reading_wins():
    # Tilapia sits at page y 750-950: in both of A's tiles and in B's second tile.
    groups = grouped(
        [tile("a1-1", [cell([300, 750, 550, 950], "Tilapia Fish Fillet", "$3.99 LB.", 3.99)]),
         tile("a1-2", [cell([300, 50, 550, 250], "Tilapia Fish Fillet", "$3.99 LB.", 3.99)])],
        [tile("b1-2", [cell([300, 400, 550, 600], "Tilapia Fish Fillet", "$3.99 LB.", 3.99)])],
    )  # fmt: skip
    assert len(groups) == 1 and len(groups[0]) == 3
    keep, why = transcribe.settle(groups[0])
    assert why is None and keep["tile"] == "b1-2"  # 400 px from its tile's nearest edge


def test_a_price_disagreement_is_disputed():
    groups = grouped(
        [tile("a1-1", [cell([300, 750, 550, 950], "Tilapia Fish Fillet", "$3.99 LB.", 3.99)])],
        [tile("b1-2", [cell([300, 400, 550, 600], "Tilapia Fish Fillet", "$3.49 LB.", 3.49)])],
    )
    assert transcribe.settle(groups[0]) == (None, "price differ")


def test_a_cell_only_one_pass_found_is_disputed():
    groups = grouped([tile("a1-1", [cell([0, 100, 250, 300], "Pork Spareribs", "$2.99 LB.", 2.99)])], [])
    assert transcribe.settle(groups[0]) == (None, "only pass A found it")


def test_a_reading_whose_printed_and_parsed_price_differ_is_disputed():
    groups = grouped(
        [tile("a1-1", [cell([0, 100, 250, 300], "Cilantro or Radishes", "2 FOR $1", 1.0, "each")])],
        [tile("b1-1", [cell([0, 100, 250, 300], "Cilantro or Radishes", "2 FOR $1", 1.0, "each")])],
    )
    keep, why = transcribe.settle(groups[0])
    assert keep is None and "doesn't match its parsed form" in why  # qty should have been 2


def test_neighbors_never_merge_even_when_boxes_overlap_a_little():
    groups = grouped(
        [tile("a1-1", [cell([0, 100, 250, 300], "Roma Tomatoes or Limes"), cell([0, 280, 250, 480], "Cilantro or Radishes")])],
        [tile("b1-1", [cell([0, 110, 250, 310], "Roma Tomatoes or Limes"), cell([0, 270, 250, 470], "Cilantro or Radishes")])],
    )
    assert sorted(len(g) for g in groups) == [2, 2]
    assert all(len({r["name"] for r in g}) == 1 for g in groups)


def test_an_unreadable_reading_joins_its_cell_and_sends_it_to_resolution():
    groups = grouped(
        [tile("a1-1", unreadable=[{"box": [0, 100, 250, 300], "legible": "Sun Vista ?, $2.?9", "problem": "smudged"}])],
        [tile("b1-1", [cell([0, 100, 250, 300], "Sun Vista Pinto Beans", "$2.99", 2.99, "package")])],
    )
    assert len(groups) == 1
    assert transcribe.settle(groups[0]) == (None, "marked unreadable")


def test_sizes_compare_by_their_numbers():
    groups = grouped(
        [tile("a1-1", [cell([0, 100, 250, 300], "Mazola Oil", "$4.99 EA.", 4.99, "each", size="40 oz. Bottle")])],
        [tile("b1-1", [cell([0, 100, 250, 300], "Mazola Oil", "$4.99 EA.", 4.99, "each", size="40 oz. Bottle, Selected Varieties")])],
    )  # fmt: skip
    assert transcribe.settle(groups[0])[1] is None


def test_assemble_numbers_items_in_reading_order_and_records_how():
    a = [tile("a1-1", [cell([500, 100, 750, 300], "Tilapia Fish Fillet", "$3.99 LB.", 3.99), cell([0, 100, 250, 300], "Roma Tomatoes or Limes")])]
    b = [tile("b1-1", [cell([500, 100, 750, 300], "Tilapia Fish Fillet", "$3.49 LB.", 3.49), cell([0, 100, 250, 300], "Roma Tomatoes or Limes")])]
    a[0]["header"] = b[0]["header"] = {"text": "Prices Effective Oct. 27, 2026 thru Nov. 02, 2026", "start": "2026-10-27", "end": "2026-11-02"}
    passes = [{"tiles": a}, {"tiles": b}]
    groups = transcribe.group(transcribe.readings(passes, MANIFEST))
    cases = transcribe.disputes(groups)
    verdict = {"verdict": "item", "cell": {k: v for k, v in cell(None, "Tilapia Fish Fillet", "$3.99 LB.", 3.99).items() if k != "box"},
               "note": "It's $3.99."}  # fmt: skip
    resolved = [{"id": "d01", "page": 1, "box": [500, 100, 750, 300], "why": cases[0][1], "verdict": verdict}]
    transcript = transcribe.assemble(passes, groups, resolved)
    assert [(i["id"], i["name"]) for i in transcript["items"]] == [("i1-01", "Roma Tomatoes or Limes"), ("i1-02", "Tilapia Fish Fillet")]
    assert transcript["items"][1]["how"] == "resolved (price differ): It's $3.99."
    assert transcript["items"][0]["how"] == "both passes agree (2 readings)"
    assert transcript["week"] == {"start": "2026-10-27", "end": "2026-11-02", "note": ""}


def transcript(start="2026-10-27", end="2026-11-02", windows=None, items=80):
    return {
        "week": {"start": start, "end": end, "note": ""},
        "windows": windows if windows is not None else {
            "3-day": ["2026-10-27", "2026-10-28", "2026-10-29"], "friday": ["2026-10-30"], "weekend": ["2026-10-31", "2026-11-01"]},
        "items": [{"window": "full-week", "coupon": False}] * items,
    }  # fmt: skip


def test_check_accepts_a_normal_week():
    transcribe.check(transcript(), last_week="2026-10-20")
    transcribe.check(transcript(), last_week="2026-10-27")  # a revision of the same week


@pytest.mark.parametrize(
    "bad, complaint",
    [
        (transcript(start="2026-10-28", end="2026-11-03"), "isn't Tuesday to Monday"),
        (transcript(end="2026-11-01"), "isn't Tuesday to Monday"),
        (transcript(windows={"friday": ["2026-11-06"]}), "friday dates fall outside"),
        (transcript(windows={"3-day": ["2026-10-31"], "friday": ["2026-10-30"]}), "doesn't come after"),
        (transcript(items=12), "12 items is outside"),
    ],
)
def test_check_rejects_what_cant_be_right(bad, complaint):
    with pytest.raises(transcribe.CheckFailed, match=complaint):
        transcribe.check(bad)


def test_check_rejects_an_older_week():
    with pytest.raises(transcribe.CheckFailed, match="older than the last one"):
        transcribe.check(transcript(), last_week="2026-11-03")


def test_day_tags_come_from_the_banner_dates():
    t = transcript()
    assert [transcribe.day_tag(t, w) for w in transcribe.WINDOWS] == ["", "Tue–Thu", "Fri", "Sat–Sun"]
    assert [transcribe.day_tag(t, w, long=True) for w in ("full-week", "friday")] == ["all week", "Friday"]
