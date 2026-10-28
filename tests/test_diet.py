import pytest

from carnival import diet
from carnival.prices import Price

TABLE = diet.nutrition()
SETTINGS = {"protein_min_g_per_100kcal": 10, "skip_min_purchase_coupons": True}


def test_diet_md_front_matter():
    assert diet.rules() == SETTINGS


def test_nutrition_table_is_complete_and_sane():
    for key, row in TABLE.items():
        assert row["fdc_id"] > 0 and 0 < row["protein_g"] < 100 and 0 < row["kcal"] < 900, key
        assert 0 < row["yield"] <= 1, key


@pytest.mark.parametrize(
    "key, low, high",
    [  # diet.md's calibration examples
        ("chicken-breast", 18.5, 19.5),
        ("eggs", 8.5, 9.0),
        ("queso-fresco", 0, 10),
        ("bacon", 0, 7),
        ("greek-yogurt-nonfat", 16.5, 18),
        ("cottage-cheese", 10.5, 12),
        ("tilapia-fillet", 19, 22),
    ],
)
def test_calibration(key, low, high):
    row = TABLE[key]
    assert low <= row["protein_g"] / row["kcal"] * 100 <= high


def test_grams_of_protein_per_dollar():
    # 453.592 g/lb x 0.60 yield x 19.4 g protein per 100 g / $0.99 per lb = 53.3
    assert diet.grams_per_dollar(TABLE["chicken-drumstick"], Price.parse("99¢ LB."), "") == 53
    # By the package: a 5 oz can at 99¢ is $3.168/lb, and only the drained 80% is tuna.
    assert diet.grams_per_dollar(TABLE["tuna-canned"], Price.parse("99¢ EA."), "5 oz. Can") == 22
    # Two for $3 on 5 oz cans is $1.50 a can.
    assert diet.grams_per_dollar(TABLE["tuna-canned"], Price.parse("2 for $3"), "5 oz. Cans") == 15
    # No weight printed: no number, rather than an estimate.
    assert diet.grams_per_dollar(TABLE["eggs"], Price.parse("$3.99"), "18 Count") is None


def item(item_id, name, price, size=""):
    p = Price.parse(price)
    return {"id": item_id, "name": name, "size": size, "price": price, "qty": p.qty, "amount": p.cents / 100,
            "unit": p.unit, "window": "full-week", "coupon": False}  # fmt: skip


def test_judge_option_by_option():
    transcript = {"items": [
        item("i1", "Pork Shank or Marinated or Plain Drumsticks", "99¢ LB."),
        item("i2", "Grade AA Medium Eggs", "$3.99", "20 Count Flat"),
        item("i3", "Budweiser Beer", "$23.99 +TAX +CRV"),
        item("i4", "Chicken Thighs or Drumsticks", "$1.29 LB."),
        item("i5", "Roma Tomatoes", "$1.29 LB."),
    ]}  # fmt: skip
    sorted_items = {"items": [
        {"id": "i1", "options": [{"name": "pork shank", "section": "protein", "nutrition": "pork-shank"},
                                 {"name": "chicken drumsticks", "section": "protein", "nutrition": "chicken-drumstick"}]},
        {"id": "i2", "options": [{"name": "eggs", "section": "protein", "nutrition": "eggs"}]},
        {"id": "i3", "options": [{"name": "Budweiser beer", "section": "cut", "reason": "alcohol"}]},
        {"id": "i4", "options": [{"name": "chicken thighs", "section": "protein", "nutrition": "chicken-thigh-bone-in"},
                                 {"name": "drumsticks", "section": "protein", "nutrition": "chicken-drumstick"}]},
        {"id": "i5", "options": [{"name": "Roma tomatoes", "section": "produce"}]},
    ]}  # fmt: skip
    judged = {d["id"]: d for d in diet.judge(transcript, sorted_items, TABLE, SETTINGS)}

    shank, drumsticks = judged["i1"]["options"]
    assert (shank["verdict"], shank["why"]) == ("cut", "collagen-dominant")
    assert judged["i1"]["name"] == "Chicken drumsticks" and judged["i1"]["g_per_dollar"] == 53

    assert judged["i2"]["kept"] is False
    assert judged["i2"]["options"][0]["why"] == "protein rule: 8.8 g per 100 kcal"

    assert judged["i3"]["kept"] is False and judged["i3"]["options"][0]["why"] == "alcohol"

    # Both pass; the less favorable, drumsticks at 0.60 yield, sets the number.
    thighs, sticks = judged["i4"]["options"]
    assert thighs["g_per_dollar"] > sticks["g_per_dollar"] == judged["i4"]["g_per_dollar"]
    assert judged["i4"]["name"] == "Chicken thighs or drumsticks"

    assert (judged["i5"]["section"], judged["i5"]["g_per_dollar"]) == ("produce", None)


def test_filter_output_is_checked():
    good = {"items": [{"id": "i1", "options": [{"name": "eggs", "section": "protein", "nutrition": "eggs"}]}],
            "new_nutrition": [], "headline": [{"id": "i1", "label": "Eggs"}]}  # fmt: skip
    diet.check(good, ["i1"], TABLE)
    with pytest.raises(ValueError, match="exactly one entry"):
        diet.check(good, ["i1", "i2"], TABLE)
    unknown_row = {**good, "items": [{"id": "i1", "options": [{"name": "eggs", "section": "protein", "nutrition": "ostrich"}]}]}
    with pytest.raises(ValueError, match="needs a nutrition row"):
        diet.check(unknown_row, ["i1"], TABLE)
    reasonless = {**good, "items": [{"id": "i1", "options": [{"name": "beer", "section": "cut"}]}]}
    with pytest.raises(ValueError, match="needs a reason"):
        diet.check(reasonless, ["i1"], TABLE)


def test_options_that_pass_read_as_a_list():
    transcript = {"items": [item("i1", "Oranges, Bananas or Yellow Onions", "2 LBS $1")]}
    names = ("oranges", "bananas", "yellow onions")
    sorted_items = {"items": [{"id": "i1", "options": [{"name": n, "section": "produce"} for n in names]}]}
    assert diet.judge(transcript, sorted_items, TABLE, SETTINGS)[0]["name"] == "Oranges, bananas or yellow onions"
