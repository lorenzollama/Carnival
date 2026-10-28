"""Prices as Carnival prints them, and the one normalized way the message prints them back."""

import re
from dataclasses import dataclass

UNITS = ("lb", "each", "package")  # by weight / printed "EA." / no unit printed

_PRINTED = re.compile(
    r"""^(?:(?P<qty>\d+)\s*(?:(?P<lbs>LBS?\.?)\s*(?:FOR\b)?|FOR\b|/)\s*)?  # "3 FOR", "2 LBS", "2/"
        (?:\$\s*(?P<dollars>\d+(?:\.\d\d)?)|(?P<cents>\d{1,2})\s*¢)  # "$5.99", "$5", "99¢"
        \s*/?\s*(?P<unit>LBS?\.?|EA\.?|EACH)?$                        # "LB.", "/lb", "EA."
    """,
    re.X,
)
_EXTRAS = re.compile(r"\+\s*(?:CRV|TAX|DEP\w*)\.?|\(.*?\)", re.I)  # deposits are not price


@dataclass(frozen=True)
class Price:
    qty: int  # how many you must buy: 3 in "3 for $5", 2 in "2 lb for $1"
    cents: int  # what that quantity costs
    unit: str  # one of UNITS

    @classmethod
    def parse(cls, printed):
        """Read a price the way the ad prints it, or return None if it isn't a known format."""
        text = " ".join(_EXTRAS.sub(" ", printed).upper().split()).rstrip(".,")
        m = _PRINTED.match(text)
        if not m:
            return None
        qty = int(m["qty"] or 1)
        cents = round(float(m["dollars"]) * 100) if m["dollars"] else int(m["cents"])
        if m["lbs"] or (m["unit"] or "").startswith("LB"):
            unit = "lb"
        elif m["unit"] or qty > 1:  # a multi-buy counts items, like "EA."
            unit = "each"
        else:
            unit = "package"
        return cls(qty, cents, unit) if cents else None

    @property
    def per_unit(self):
        """Dollars per pound (unit "lb") or per item."""
        return self.cents / 100 / self.qty

    def __str__(self):
        if self.qty > 1:
            return f"{self.qty} {'lb ' if self.unit == 'lb' else ''}for {money(self.cents)}"
        return money(self.cents) + {"lb": "/lb", "each": " ea", "package": ""}[self.unit]


def money(cents):
    """89 -> "89¢", 299 -> "$2.99", 500 -> "$5"."""
    if cents < 100:
        return f"{cents}¢"
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


# "16 oz.", "10-11 oz.", "4 Lb. Bag". "16.9 fl. oz." never matches: fluid ounces are volume.
_WEIGHT = re.compile(r"(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?\s*(oz|lbs?)\b", re.I)


def package_lb(size):
    """The smallest net weight printed in a size line, in pounds ("10-11 oz." -> 0.625).

    For a range, the smaller weight is the less favorable one. Returns None when no weight is
    printed, or when the small print couldn't all be read ("?"): the caller then leaves out
    anything that would need a weight rather than estimate one.
    """
    if "?" in (size or ""):
        return None
    weights = [float(n) / (16 if unit.lower() == "oz" else 1) for n, unit in _WEIGHT.findall(size or "")]
    return min(weights) if weights else None
