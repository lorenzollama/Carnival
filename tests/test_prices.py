import pytest

from carnival.prices import Price, money, package_lb


@pytest.mark.parametrize(
    "printed, qty, cents, unit, shown",
    [
        ("2 LBS $1", 2, 100, "lb", "2 lb for $1"),
        ("3 FOR $5", 3, 500, "each", "3 for $5"),
        ("99¢ EA.", 1, 99, "each", "99¢ ea"),
        ("$3.99 +CRV", 1, 399, "package", "$3.99"),
        ("$5.99 LB.", 1, 599, "lb", "$5.99/lb"),
        ("89¢ LB.", 1, 89, "lb", "89¢/lb"),
        ("$6.99 +TAX +CRV", 1, 699, "package", "$6.99"),
        ("2 for $5 +crv", 2, 500, "each", "2 for $5"),
        ("2/$5", 2, 500, "each", "2 for $5"),
        ("4 for 99¢", 4, 99, "each", "4 for 99¢"),
        ("$7.99", 1, 799, "package", "$7.99"),
        ("$5", 1, 500, "package", "$5"),
        ("$1.29/lb", 1, 129, "lb", "$1.29/lb"),
    ],
)
def test_reads_printed_prices(printed, qty, cents, unit, shown):
    price = Price.parse(printed)
    assert price == Price(qty, cents, unit)
    assert str(price) == shown


def test_cents_are_never_split_into_a_multi_buy():
    assert Price.parse("89¢") == Price(1, 89, "package")  # not "8 for 9¢"


@pytest.mark.parametrize("printed", ["Buy 1 Get 1 Free", "$5.9", "SALE", ""])
def test_unknown_formats_are_none(printed):
    assert Price.parse(printed) is None


def test_per_unit_divides_out_multi_buys():
    assert Price.parse("2 LBS $1").per_unit == 0.5  # dollars per pound
    assert Price.parse("3 FOR $5").per_unit == pytest.approx(5 / 3)


@pytest.mark.parametrize("cents, shown", [(89, "89¢"), (99, "99¢"), (100, "$1"), (299, "$2.99"), (1999, "$19.99")])
def test_money(cents, shown):
    assert money(cents) == shown


@pytest.mark.parametrize(
    "size, pounds",
    [
        ("16 oz. Package", 1.0),
        ("10-11 oz.", 0.625),  # a range counts at its smaller, less favorable weight
        ("4 Lb. Bag", 4.0),
        ("5 oz., Selected Varieties; or 8 oz.", 5 / 16),
        ("16.9 fl. oz. Bottles", None),  # volume, not weight
        ("20 Count Flat", None),
        ("1? oz. Package", None),  # partly illegible: don't estimate
        ("", None),
    ],
)
def test_package_weight(size, pounds):
    assert package_lb(size) == pounds
