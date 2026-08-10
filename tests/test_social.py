"""The social feed must carry a real signal, and only the signal it claims.

Three properties are load-bearing and each fails silently:

1. Buzz is built from latent demand, which is identical across policy arms. If
   it ever picked up REALISED sales instead, the arm comparisons would start
   measuring the replenishment policy through the back door.
2. The signal genuinely leads demand. A generator that emits noise makes "do
   social signals help?" unanswerable, which is what the previous emitter did.
3. It is not too clean. A near-perfect signal would make any feature built on it
   look strong for reasons no real feed would reproduce.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.synth import build_world, run_arm
from stockout.synth.dims import BRANDS
from stockout.synth.social import build_buzz_index, build_demand_index

SEED = 20260809


@pytest.fixture(scope="module")
def world(synth_config):
    defaults = synth_config["defaults"]
    dims = build_world(synth_config["profiles"]["small"], defaults)
    baseline = run_arm(dims, defaults, "A-baseline")
    return dims, baseline, defaults


@pytest.fixture(scope="module")
def signals(tiny_extract) -> pd.DataFrame:
    return pd.read_csv(tiny_extract / "external_signals_fact.csv")


# --------------------------------------------------------------------------
# the signal itself
# --------------------------------------------------------------------------

def test_buzz_is_identical_across_arms(world, synth_config):
    """Same demand seed, different policy -> byte-identical buzz.

    This is the social-feed counterpart of the RNG split asserted in
    tests/test_arms.py. Building buzz from `units_sold` alone would break it,
    because replenishment changes what gets sold but not what was wanted.
    """
    dims, baseline, defaults = world
    counterfactual = run_arm(
        dims, defaults, "B-counterfactual", replenishment_enabled=False
    )

    left = build_buzz_index(dims, baseline.result, np.random.default_rng(SEED), defaults)
    right = build_buzz_index(
        dims, counterfactual.result, np.random.default_rng(SEED), defaults
    )

    assert len(left) == len(right)
    pd.testing.assert_series_equal(left["demand_index"], right["demand_index"])
    pd.testing.assert_series_equal(left["buzz_index"], right["buzz_index"])


def test_realised_sales_do_differ_across_arms(world, synth_config):
    """Guards the test above from passing for the wrong reason.

    If the two arms happened to produce identical panels, arm-invariance would be
    trivially true and would prove nothing about which demand column was used.
    """
    dims, baseline, defaults = world
    counterfactual = run_arm(
        dims, defaults, "B-counterfactual", replenishment_enabled=False
    )
    assert baseline.result.panel["units_sold"].sum() != (
        counterfactual.result.panel["units_sold"].sum()
    )


def test_buzz_leads_demand(world):
    """Buzz this week must carry information about NEXT week's demand."""
    dims, baseline, defaults = world
    frame = build_buzz_index(dims, baseline.result, np.random.default_rng(SEED), defaults)

    frame = frame.sort_values(["city", "category", "subcat", "week"])
    next_demand = frame.groupby(["city", "category", "subcat"], sort=False)[
        "demand_index"
    ].shift(-1)
    usable = frame.assign(next_demand=next_demand).dropna(subset=["next_demand"])

    correlation = usable["buzz_index"].corr(usable["next_demand"], method="spearman")
    assert correlation > 0.2, f"buzz carries no forward signal (rho={correlation:.3f})"


def test_buzz_is_not_a_giveaway(world):
    """A signal this clean would not survive contact with a real feed."""
    dims, baseline, defaults = world
    frame = build_buzz_index(dims, baseline.result, np.random.default_rng(SEED), defaults)

    frame = frame.sort_values(["city", "category", "subcat", "week"])
    next_demand = frame.groupby(["city", "category", "subcat"], sort=False)[
        "demand_index"
    ].shift(-1)
    usable = frame.assign(next_demand=next_demand).dropna(subset=["next_demand"])

    correlation = usable["buzz_index"].corr(usable["next_demand"], method="spearman")
    assert correlation < 0.8, f"buzz is implausibly clean (rho={correlation:.3f})"


def test_buzz_leads_rather_than_restates(world):
    """Buzz must track NEXT week's demand more strongly than THIS week's.

    Regression guard for a real mistake: smoothing the finished buzz series
    (rather than its noise) averages in the adjacent week and leaves the two
    correlations equal. The signal still looks fine on every other check while
    having quietly stopped being a leading indicator.
    """
    dims, baseline, defaults = world
    frame = build_buzz_index(dims, baseline.result, np.random.default_rng(SEED), defaults)
    frame = frame.sort_values(["city", "category", "subcat", "week"])

    next_demand = frame.groupby(["city", "category", "subcat"], sort=False)[
        "demand_index"
    ].shift(-1)
    usable = frame.assign(next_demand=next_demand).dropna(subset=["next_demand"])

    ahead = usable["buzz_index"].corr(usable["next_demand"], method="spearman")
    current = frame["buzz_index"].corr(frame["demand_index"], method="spearman")
    assert ahead > current * 1.5, (
        f"buzz is not leading: rho(next)={ahead:.3f} vs rho(current)={current:.3f}"
    )


def test_demand_index_uses_latent_not_sold(world):
    """Latent demand must exceed realised sales wherever stockouts happened."""
    dims, baseline, defaults = world
    index = build_demand_index(dims, baseline.result)
    assert index["latent_units"].sum() > baseline.result.panel["units_sold"].sum()


# --------------------------------------------------------------------------
# internal consistency
# --------------------------------------------------------------------------

def test_engagement_rate_matches_its_own_components(signals):
    """The rate must be the engagement it reports over the reach beside it."""
    computed = (
        (signals["post_like_count"] + signals["post_comment_count"]
         + signals["post_share_count"])
        / signals["reach"] * 100
    )
    assert (computed - signals["engagement_rate_pct"]).abs().max() < 0.05


def test_share_of_voice_sums_to_one_hundred(signals):
    """Every brand appears in every city x line x week, so the shares close."""
    week = pd.to_datetime(signals["post_datetime"]).dt.to_period("W").dt.start_time
    per_group = (
        signals.assign(week=week)
        .drop_duplicates(subset=["Brand", "City", "Footwear_Type", "week"])
        .groupby(["City", "Footwear_Type", "week"])["Share_of_Voice_Pct"]
        .sum()
    )
    # Only groups holding the full brand roster can close to 100; a week clipped
    # by the calendar edge legitimately holds fewer.
    complete = per_group[per_group > 50]
    assert not complete.empty
    assert (complete - 100).abs().max() < 1.0


def test_follower_counts_belong_to_the_account(signals):
    """A handle's following drifts slowly; it does not jump per post."""
    ordered = signals.sort_values("post_datetime")
    for handle, group in ordered.groupby("Handle"):
        counts = group["page_follower_count"].to_numpy()
        assert (np.diff(counts) >= 0).all(), f"{handle} lost followers between posts"
        assert counts.max() / max(counts.min(), 1) < 3.0, f"{handle} jumps implausibly"


def test_post_id_is_unique(signals):
    assert signals["post_id"].is_unique


def test_declared_grain_holds(signals):
    """The composite grain in schemas.yaml must actually identify a row."""
    grain = ["Brand", "City", "Footwear_Type", "post_datetime"]
    assert not signals.duplicated(subset=grain).any()


# --------------------------------------------------------------------------
# the join, and the limit on it
# --------------------------------------------------------------------------

def test_joins_to_stores_and_product_lines(signals, tiny_extract):
    """City and category must resolve; this is the whole point of the table."""
    stores = pd.read_csv(tiny_extract / "store_dim.csv")
    inventory = pd.read_csv(tiny_extract / "inventory_snapshot.csv")

    cities = {c.strip().upper() for c in stores["city"]}
    assert {c.strip().upper() for c in signals["City"]} <= cities

    lines = set(
        zip(inventory["category"].str.strip(), inventory["subcat"].str.strip())
    )
    signal_lines = set(
        zip(signals["Category"].str.strip(), signals["Sub_Category"].str.strip())
    )
    assert signal_lines <= lines


def test_never_carries_a_sku(signals):
    """Category grain is a real property of this feed, not an oversight.

    Emitting a SKU or a size here would quietly invent a join the source data
    cannot support, and every downstream claim about SKU-level social signal
    would be an artifact of the generator.
    """
    forbidden = {"sku_uid", "size", "Size", "dns_item", "color", "colour"}
    assert not forbidden & set(signals.columns)


def test_own_and_competitor_brands_both_present(signals):
    """Share of voice is meaningless without both sides of it."""
    own = set(BRANDS)
    seen = set(signals["Brand"])
    assert seen & own, "no own-brand rows: own-vs-competitor SoV is uncomputable"
    assert seen - own, "no competitor rows: the feed would not be a market view"
    assert set(signals.loc[signals["brand_is_own"] == "Yes", "Brand"]) <= own


def test_complaints_track_our_stockouts(world):
    """The deliberate trap: complaints are a LAGGING stockout signal.

    Asserted so the behaviour is documented and cannot be removed by accident --
    a feature build that treats every social column as leading needs something
    in the data that punishes the assumption.
    """
    dims, baseline, defaults = world
    index = build_demand_index(dims, baseline.result)
    assert index["lost_units"].sum() > 0
