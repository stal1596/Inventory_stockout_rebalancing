"""Canonical identifier construction for the stockout data model.

Two rules drive everything here:

1. Build keys from ATOMIC columns wherever they exist. Composite strings in the
   source data are not delimiter-safe -- ``METRO_57_38_ROSE_GOLD`` has an
   underscore inside the colour and ``900_1690_BLUE/NAVY_84`` has a slash. A
   naive ``split("_")`` silently corrupts both.

2. Never silently repair a value you cannot verify. Normalisation (case,
   whitespace) is always safe and always applied. Repair (the ``GUSO3`` ->
   ``GUS03`` letter-O/digit-0 confusion) is only applied when the repaired value
   resolves against a known master list, and it is always reported so the source
   system gets fixed rather than papered over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import product as iter_product

import pandas as pd

# Delimiter for every composite uid we build. Safe because normalise_colour
# strips this character out of the only component that could contain it.
SEP = "_"

# Characters routinely confused with digits in hand-keyed store codes.
#
# Deliberately narrow. S->5 and B->8 are classic OCR confusions but are excluded
# here: real store codes contain S and B as genuine letters (GUS03, BPC01,
# BHS01), so including them would make almost every repair ambiguous and refused.
_DIGIT_CONFUSIONS: dict[str, tuple[str, ...]] = {
    "O": ("0",),
    "Q": ("0",),
    "I": ("1",),
    "L": ("1",),
}

# Known size scales. Footwear extracts mix an EU run with a second, unexplained
# 83-90 block; they must not be compared or joined as if they were one scale.
SIZE_SCALES: dict[str, range] = {
    "EU": range(15, 56),
    "ALT": range(75, 100),
}


# --------------------------------------------------------------------------
# scalar normalisers
# --------------------------------------------------------------------------

def normalise_text(value: object) -> str:
    """Upper-case, trim, and collapse internal whitespace."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().upper())


def normalise_store_id(value: object) -> str:
    """Safe normalisation only: case and whitespace. No character repair."""
    return normalise_text(value).replace(" ", "")


def normalise_colour(value: object) -> str:
    """Canonicalise a colour name to a delimiter-safe token.

    ``ROSE_GOLD``, ``ANTIC GOLD`` and ``BLUE/NAVY`` all use different internal
    separators. Collapsing them to ``-`` makes ``SEP`` unambiguous inside a uid.
    """
    text = normalise_text(value)
    return re.sub(r"[\s/_\-]+", "-", text).strip("-")


def normalise_city(value: object) -> str:
    return normalise_text(value)


def normalise_zone(value: object) -> str:
    """``SOUTH ZONE`` and ``East Zone`` must land on the same token."""
    return re.sub(r"\s*ZONE\s*$", "", normalise_text(value)).strip()


def normalise_size(value: object) -> str:
    """Strip decorations and leading zeros; keep as string (sizes are labels)."""
    text = normalise_text(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(\.0+)?", text):
        return str(int(float(text)))
    return text


def classify_size_scale(value: object) -> str:
    """Return the size scale a value belongs to: ``EU``, ``ALT`` or ``UNKNOWN``."""
    text = normalise_size(value)
    if not re.fullmatch(r"\d+", text):
        return "UNKNOWN"
    number = int(text)
    for scale, allowed in SIZE_SCALES.items():
        if number in allowed:
            return scale
    return "UNKNOWN"


# --------------------------------------------------------------------------
# uid construction
# --------------------------------------------------------------------------

def make_style_uid(dns: object, item: object) -> str:
    return f"{normalise_text(dns)}{SEP}{normalise_text(item)}"


def make_option_uid(dns: object, item: object, colour: object) -> str:
    return f"{make_style_uid(dns, item)}{SEP}{normalise_colour(colour)}"


def make_sku_uid(dns: object, item: object, colour: object, size: object) -> str:
    """The canonical SKU-size identity: dns _ item _ colour _ size."""
    return f"{make_option_uid(dns, item, colour)}{SEP}{normalise_size(size)}"


def split_dns_item(value: object) -> tuple[str, str]:
    """``14_1033`` -> ``("14", "1033")``. Splits on the FIRST separator only."""
    text = normalise_text(value)
    if SEP not in text:
        return text, ""
    dns, _, item = text.partition(SEP)
    return dns, item


# --------------------------------------------------------------------------
# composite-string parsers
# --------------------------------------------------------------------------

# brand _ dns _ item _ colour   (replenishment SKU, forecast options_)
# Non-greedy brand plus anchored numeric dns/item means a colour containing the
# separator (ROSE_GOLD) still lands in the colour group.
_BRANDED_KEY_RE = re.compile(
    r"^(?P<brand>.+?)_(?P<dns>\d+)_(?P<item>\d+)_(?P<colour>.+)$"
)

# dns _ item _ colour _ size    (product_dim Options_size, pending locationskuname)
# Greedy colour with an anchored trailing size, so BLUE/NAVY survives intact.
_SIZED_KEY_RE = re.compile(
    r"^(?P<dns>\d+)_(?P<item>\d+)_(?P<colour>.+)_(?P<size>\d+)$"
)

_ITEMNUMBER_LONG_RE = re.compile(
    r"^(?P<dns>\d+)-(?P<item>\d+)-(?P<colour_code>[A-Z]+)-(?P<size>\d+)-(?P<seq>\d+)$"
)
_ITEMNUMBER_SHORT_RE = re.compile(r"^(?P<dns>\d+)-(?P<item>\d+)-(?P<seq>\d+)$")


@dataclass(frozen=True)
class ParsedKey:
    """Result of parsing a composite key string. ``ok`` is False if unparseable."""

    ok: bool
    brand: str = ""
    dns: str = ""
    item: str = ""
    colour: str = ""
    size: str = ""
    raw: str = ""

    @property
    def style_uid(self) -> str:
        return make_style_uid(self.dns, self.item) if self.ok else ""

    @property
    def option_uid(self) -> str:
        return make_option_uid(self.dns, self.item, self.colour) if self.ok else ""

    @property
    def sku_uid(self) -> str:
        if not self.ok or not self.size:
            return ""
        return make_sku_uid(self.dns, self.item, self.colour, self.size)


def parse_branded_key(value: object) -> ParsedKey:
    """Parse ``METRO_57_38_ROSE_GOLD`` / ``VELTRIX_14_1002_BLACK``.

    Used for ``replenishment_orders.SKU`` and ``forecast.options_``, neither of
    which carries atomic dns/item/colour columns for the key itself.
    """
    raw = str(value).strip() if value is not None else ""
    match = _BRANDED_KEY_RE.match(normalise_text(raw))
    if not match:
        return ParsedKey(ok=False, raw=raw)
    return ParsedKey(
        ok=True,
        brand=match["brand"].strip(),
        dns=match["dns"],
        item=match["item"],
        colour=normalise_colour(match["colour"]),
        raw=raw,
    )


def parse_sized_key(value: object) -> ParsedKey:
    """Parse ``35_205_ANTIC GOLD_37`` / ``900_1690_BLUE/NAVY_84``."""
    raw = str(value).strip() if value is not None else ""
    match = _SIZED_KEY_RE.match(normalise_text(raw))
    if not match:
        return ParsedKey(ok=False, raw=raw)
    return ParsedKey(
        ok=True,
        dns=match["dns"],
        item=match["item"],
        colour=normalise_colour(match["colour"]),
        size=normalise_size(match["size"]),
        raw=raw,
    )


def parse_itemnumber(value: object) -> ParsedKey:
    """Parse either ``product_dim.itemnumber`` format.

    Long form  ``35-205-XAN-37-1``  carries a colour code and size.
    Short form ``35-3152-007``      carries neither.

    product_dim already has atomic dns/item/size/cname columns, so this exists
    to CHECK those columns rather than to build keys from.
    """
    raw = str(value).strip() if value is not None else ""
    text = normalise_text(raw)
    if match := _ITEMNUMBER_LONG_RE.match(text):
        return ParsedKey(
            ok=True,
            dns=match["dns"],
            item=match["item"],
            colour=match["colour_code"],
            size=normalise_size(match["size"]),
            raw=raw,
        )
    if match := _ITEMNUMBER_SHORT_RE.match(text):
        return ParsedKey(ok=True, dns=match["dns"], item=match["item"], raw=raw)
    return ParsedKey(ok=False, raw=raw)


# --------------------------------------------------------------------------
# store-id repair (lookup-assisted, never blind)
# --------------------------------------------------------------------------

def _confusion_candidates(store_id: str, max_candidates: int = 64) -> list[str]:
    """Enumerate letter->digit repairs of the trailing alphanumeric run.

    Only the trailing run is touched: ``GUSO3`` has its ``S`` protected because
    the run stops at the first character that cannot be a digit confusion.
    """
    if not store_id:
        return []

    # Walk backwards while characters are digits or known digit-confusions.
    cut = len(store_id)
    while cut > 0 and (store_id[cut - 1].isdigit() or store_id[cut - 1] in _DIGIT_CONFUSIONS):
        cut -= 1
    prefix, suffix = store_id[:cut], store_id[cut:]

    # A repair must leave a non-empty alphabetic prefix, otherwise we would be
    # rewriting the whole code and could invent a valid-looking id.
    if not prefix or not suffix or not prefix[-1].isalpha():
        return []

    per_char = [
        (char, *_DIGIT_CONFUSIONS[char]) if char in _DIGIT_CONFUSIONS else (char,)
        for char in suffix
    ]
    total = 1
    for options in per_char:
        total *= len(options)
    if total > max_candidates:
        return []

    return [
        prefix + "".join(combo)
        for combo in iter_product(*per_char)
        if prefix + "".join(combo) != store_id
    ]


def repair_store_id(store_id: object, known_ids: set[str]) -> tuple[str, bool]:
    """Repair a store id only if the repair resolves against the master list.

    Returns ``(store_id, was_repaired)``. An unrepairable id is returned
    unchanged so it surfaces as a referential-integrity failure rather than
    disappearing into a wrong-but-valid store.
    """
    normalised = normalise_store_id(store_id)
    if not normalised or normalised in known_ids:
        return normalised, False

    matches = [c for c in _confusion_candidates(normalised) if c in known_ids]
    # Ambiguous repairs (more than one valid landing spot) are refused.
    if len(matches) == 1:
        return matches[0], True
    return normalised, False


# --------------------------------------------------------------------------
# vectorised helpers for panel-scale frames
# --------------------------------------------------------------------------

def _as_str(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("")


def normalise_text_series(series: pd.Series) -> pd.Series:
    return (
        _as_str(series)
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )


def normalise_colour_series(series: pd.Series) -> pd.Series:
    return (
        normalise_text_series(series)
        .str.replace(r"[\s/_\-]+", "-", regex=True)
        .str.strip("-")
    )


def normalise_size_series(series: pd.Series) -> pd.Series:
    text = normalise_text_series(series)
    numeric = text.str.fullmatch(r"\d+(\.0+)?").fillna(False)
    out = text.copy()
    out[numeric] = (
        pd.to_numeric(text[numeric], errors="coerce").astype("Int64").astype("string")
    )
    return out.fillna("")


def make_sku_uid_series(
    dns: pd.Series, item: pd.Series, colour: pd.Series, size: pd.Series
) -> pd.Series:
    return (
        normalise_text_series(dns)
        + SEP
        + normalise_text_series(item)
        + SEP
        + normalise_colour_series(colour)
        + SEP
        + normalise_size_series(size)
    )


def make_option_uid_series(
    dns: pd.Series, item: pd.Series, colour: pd.Series
) -> pd.Series:
    return (
        normalise_text_series(dns)
        + SEP
        + normalise_text_series(item)
        + SEP
        + normalise_colour_series(colour)
    )


# --------------------------------------------------------------------------
# bridges and variant detection
# --------------------------------------------------------------------------

def build_colour_map(pending_orders: pd.DataFrame) -> pd.DataFrame:
    """Derive the colour-code -> colour-name bridge.

    ``pending_orders`` is the only table carrying both representations
    (``color='C'`` with ``cname='BLACK'``), which makes it the bridge between
    ``product_dim.itemnumber`` colour codes and the colour names every other
    table uses.

    Returns columns ``colour_code``, ``colour_norm``, ``n_rows``, ``ambiguous``.
    """
    if not {"color", "cname"} <= set(pending_orders.columns):
        return pd.DataFrame(
            columns=["colour_code", "colour_norm", "n_rows", "ambiguous"]
        )

    frame = pd.DataFrame(
        {
            "colour_code": normalise_text_series(pending_orders["color"]),
            "colour_norm": normalise_colour_series(pending_orders["cname"]),
        }
    )
    counts = (
        frame.groupby(["colour_code", "colour_norm"], as_index=False)
        .size()
        .rename(columns={"size": "n_rows"})
    )
    names_per_code = counts.groupby("colour_code")["colour_norm"].transform("size")
    counts["ambiguous"] = names_per_code > 1
    return counts.sort_values(["colour_code", "n_rows"], ascending=[True, False])


def _edit_distance_le_1(left: str, right: str) -> bool:
    """True if the two strings are within one substitution/insertion/deletion."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        diffs = sum(1 for a, b in zip(left, right) if a != b)
        return diffs <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] != longer[j]:
            if skipped:
                return False
            skipped = True
            j += 1
            continue
        i += 1
        j += 1
    return True


def find_near_duplicate_values(values: pd.Series) -> list[tuple[str, str]]:
    """Flag values within edit distance 1 of each other.

    Catches ``LOOM & PACE`` vs ``LOOM & LACE``. Deliberately REPORTS rather than
    merges: which spelling is correct is a business call, not a parsing one.
    """
    unique = sorted({v for v in normalise_text_series(values).tolist() if v})
    return [
        (left, right)
        for index, left in enumerate(unique)
        for right in unique[index + 1 :]
        if _edit_distance_le_1(left, right)
    ]
