"""Identifier tests, driven by the exact values found in sample_data/.

Every literal in this file is a real string from the supplied extracts. The
awkward ones are the point: ROSE_GOLD hides the uid separator inside a colour,
BLUE/NAVY hides a slash, and GUSO3 differs from GUS03 by a letter-O.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stockout import keys


# --------------------------------------------------------------------------
# branded composite keys: brand _ dns _ item _ colour
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "brand", "dns", "item", "colour"),
    [
        ("METRO_33_3181_WHITE", "METRO", "33", "3181", "WHITE"),
        ("METRO_71_8440_BROWN", "METRO", "71", "8440", "BROWN"),
        ("METRO_33_213_BLACK", "METRO", "33", "213", "BLACK"),
        ("METRO_16_1020_GREY", "METRO", "16", "1020", "GREY"),
        ("METRO_44_571_GREY", "METRO", "44", "571", "GREY"),
        # The trap: the colour itself contains the uid separator.
        ("METRO_57_38_ROSE_GOLD", "METRO", "57", "38", "ROSE-GOLD"),
        # forecast.options_ uses the same shape with a different brand.
        ("VELTRIX_14_1002_BLACK", "VELTRIX", "14", "1002", "BLACK"),
        # A brand containing spaces must survive.
        ("LOOM & LACE_35_205_ANTIC GOLD", "LOOM & LACE", "35", "205", "ANTIC-GOLD"),
    ],
)
def test_parse_branded_key(raw, brand, dns, item, colour):
    parsed = keys.parse_branded_key(raw)
    assert parsed.ok
    assert (parsed.brand, parsed.dns, parsed.item, parsed.colour) == (
        brand,
        dns,
        item,
        colour,
    )


def test_naive_split_would_corrupt_rose_gold():
    """Guards the reason parse_branded_key exists at all."""
    raw = "METRO_57_38_ROSE_GOLD"
    assert len(raw.split("_")) == 5  # naive split over-fragments
    assert keys.parse_branded_key(raw).colour == "ROSE-GOLD"


def test_parse_branded_key_rejects_garbage():
    assert not keys.parse_branded_key("NOT-A-KEY").ok
    assert not keys.parse_branded_key("").ok
    assert not keys.parse_branded_key(None).ok


# --------------------------------------------------------------------------
# sized composite keys: dns _ item _ colour _ size
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "dns", "item", "colour", "size"),
    [
        ("35_205_ANTIC GOLD_37", "35", "205", "ANTIC-GOLD", "37"),
        ("35_3728_ANTIC GOLD_38", "35", "3728", "ANTIC-GOLD", "38"),
        # pending_orders.locationskuname: colour contains a slash.
        ("900_1690_BLUE/NAVY_84", "900", "1690", "BLUE-NAVY", "84"),
        ("900_1597_BLACK_41", "900", "1597", "BLACK", "41"),
        ("900_1692_BLACK_28", "900", "1692", "BLACK", "28"),
    ],
)
def test_parse_sized_key(raw, dns, item, colour, size):
    parsed = keys.parse_sized_key(raw)
    assert parsed.ok
    assert (parsed.dns, parsed.item, parsed.colour, parsed.size) == (
        dns,
        item,
        colour,
        size,
    )


def test_sized_key_round_trips_to_sku_uid():
    parsed = keys.parse_sized_key("900_1690_BLUE/NAVY_84")
    assert parsed.sku_uid == keys.make_sku_uid("900", "1690", "BLUE/NAVY", "84")


# --------------------------------------------------------------------------
# product_dim.itemnumber: two incompatible formats in one column
# --------------------------------------------------------------------------

def test_parse_itemnumber_long_form():
    parsed = keys.parse_itemnumber("35-205-XAN-37-1")
    assert parsed.ok
    assert (parsed.dns, parsed.item, parsed.colour, parsed.size) == (
        "35",
        "205",
        "XAN",
        "37",
    )


def test_parse_itemnumber_short_form_has_no_size_or_colour():
    parsed = keys.parse_itemnumber("35-3152-007")
    assert parsed.ok
    assert (parsed.dns, parsed.item) == ("35", "3152")
    assert parsed.size == ""
    assert parsed.colour == ""


def test_parse_itemnumber_rejects_unknown_format():
    assert not keys.parse_itemnumber("35/3152/007").ok


# --------------------------------------------------------------------------
# colour normalisation makes the uid separator unambiguous
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ROSE_GOLD", "ROSE-GOLD"),
        ("ANTIC GOLD", "ANTIC-GOLD"),
        ("BLUE/NAVY", "BLUE-NAVY"),
        ("  black  ", "BLACK"),
        ("TAN", "TAN"),
    ],
)
def test_normalise_colour(raw, expected):
    assert keys.normalise_colour(raw) == expected


def test_sku_uid_has_exactly_three_separators_even_for_awkward_colours():
    uid = keys.make_sku_uid("57", "38", "ROSE_GOLD", "34")
    assert uid.count(keys.SEP) == 3
    assert uid == "57_38_ROSE-GOLD_34"


def test_differently_written_colours_collide_on_one_uid():
    """ROSE_GOLD, ROSE GOLD and rose-gold are the same colour."""
    uids = {
        keys.make_sku_uid("57", "38", variant, "34")
        for variant in ("ROSE_GOLD", "ROSE GOLD", "rose-gold")
    }
    assert len(uids) == 1


# --------------------------------------------------------------------------
# store id: normalise always, repair only against the master list
# --------------------------------------------------------------------------

KNOWN_STORES = {"GUS03", "BPC01", "HPS01", "KCS05", "GGS01", "NCS01"}


def test_repairs_the_real_guso3_defect():
    repaired, was_repaired = keys.repair_store_id("GUSO3", KNOWN_STORES)
    assert (repaired, was_repaired) == ("GUS03", True)


def test_clean_id_is_untouched():
    assert keys.repair_store_id("GUS03", KNOWN_STORES) == ("GUS03", False)


def test_unknown_id_is_left_alone_to_fail_referential_check():
    """An id we cannot resolve must NOT be invented into a valid-looking one."""
    repaired, was_repaired = keys.repair_store_id("ZZZ99", KNOWN_STORES)
    assert (repaired, was_repaired) == ("ZZZ99", False)


def test_repair_never_rewrites_the_alpha_prefix():
    """The S in GUSO3 is a real letter and must survive the repair.

    Uses an id absent from the master list so the repair path actually runs
    rather than short-circuiting on an exact hit.
    """
    repaired, was_repaired = keys.repair_store_id("GUSO3", {"GUS03", "GU503"})
    assert (repaired, was_repaired) == ("GUS03", True)


def test_ambiguous_repair_is_refused():
    """Two confusable characters, two valid landing spots: refuse to guess.

    GUSOI can repair to GUSO1, GUS0I or GUS01. With two of those in the master
    list there is no defensible choice, so the value is left alone to fail the
    referential check loudly.
    """
    repaired, was_repaired = keys.repair_store_id("GUSOI", {"GUS01", "GUSO1"})
    assert was_repaired is False
    assert repaired == "GUSOI"


def test_repair_leaves_letters_that_are_not_digit_confusions():
    """B and S are genuine letters in store codes, never 8 and 5."""
    repaired, was_repaired = keys.repair_store_id("BHS01", {"8H501"})
    assert (repaired, was_repaired) == ("BHS01", False)


def test_store_id_normalisation_is_case_and_space_insensitive():
    assert keys.normalise_store_id("  gus03 ") == "GUS03"


# --------------------------------------------------------------------------
# size scales
# --------------------------------------------------------------------------

@pytest.mark.parametrize("size", [28, 30, 37, 41, 45, 48])
def test_eu_size_block(size):
    assert keys.classify_size_scale(size) == "EU"


@pytest.mark.parametrize("size", [83, 84, 86, 90])
def test_alt_size_block(size):
    """The unexplained 83-90 block must not be treated as EU."""
    assert keys.classify_size_scale(size) == "ALT"


def test_non_numeric_size_is_unknown():
    assert keys.classify_size_scale("XL") == "UNKNOWN"


def test_normalise_size_strips_float_artifacts():
    assert keys.normalise_size("41.0") == "41"
    assert keys.normalise_size(41) == "41"


# --------------------------------------------------------------------------
# dns_item splitting and zone folding
# --------------------------------------------------------------------------

def test_split_dns_item():
    assert keys.split_dns_item("14_1033") == ("14", "1033")


def test_split_dns_item_uses_first_separator_only():
    assert keys.split_dns_item("14_10_33") == ("14", "10_33")


def test_zone_folding_matches_across_case_and_suffix():
    assert keys.normalise_zone("SOUTH ZONE") == keys.normalise_zone("South Zone")
    assert keys.normalise_zone("East Zone") == "EAST"


def test_city_folding_matches_promotion_to_store_dim():
    assert keys.normalise_city("CHENNAI") == keys.normalise_city("Chennai")


# --------------------------------------------------------------------------
# bridges and variant detection
# --------------------------------------------------------------------------

def test_colour_map_bridges_code_to_name():
    pending = pd.DataFrame(
        {"color": ["C", "DN", "C"], "cname": ["BLACK", "BLUE/NAVY", "BLACK"]}
    )
    mapping = keys.build_colour_map(pending)
    lookup = dict(zip(mapping["colour_code"], mapping["colour_norm"]))
    assert lookup == {"C": "BLACK", "DN": "BLUE-NAVY"}
    assert not mapping["ambiguous"].any()


def test_colour_map_flags_a_code_with_two_names():
    pending = pd.DataFrame({"color": ["C", "C"], "cname": ["BLACK", "WHITE"]})
    assert keys.build_colour_map(pending)["ambiguous"].all()


def test_finds_the_loom_and_lace_brand_typo():
    brands = pd.Series(["LOOM & LACE", "LOOM & PACE", "VELTRIX", "METRO"])
    pairs = keys.find_near_duplicate_values(brands)
    assert ("LOOM & LACE", "LOOM & PACE") in pairs


def test_distinct_brands_are_not_flagged():
    brands = pd.Series(["VELTRIX", "METRO", "KHADIMS"])
    assert keys.find_near_duplicate_values(brands) == []


# --------------------------------------------------------------------------
# vectorised paths must agree with the scalar ones
# --------------------------------------------------------------------------

def test_vectorised_sku_uid_matches_scalar():
    frame = pd.DataFrame(
        {
            "dns": ["57", "900", "35"],
            "item": ["38", "1690", "205"],
            "colour": ["ROSE_GOLD", "BLUE/NAVY", "ANTIC GOLD"],
            "size": ["34", "84", "37"],
        }
    )
    vectorised = keys.make_sku_uid_series(
        frame["dns"], frame["item"], frame["colour"], frame["size"]
    )
    scalar = [
        keys.make_sku_uid(row.dns, row.item, row.colour, row.size)
        for row in frame.itertuples()
    ]
    assert vectorised.tolist() == scalar
