"""Social-listening feed generated from the simulation's own latent demand.

The previous emitter drew every signal column — sentiment, trend, mentions,
share of voice — from independent uniforms. That makes the table useless for the
one question it exists to answer: *do social signals improve stockout
prediction?* A feature built on noise can only ever return "no", and the answer
would be an artifact of the generator rather than a finding.

Here the buzz is a **noisy, forward-shifted observation of latent demand**:

    demand_index[city, line, week]  = sum(units_sold + lost_units) / its own mean
    buzz_index[week]                = demand_index[week + lead] * exp(N(0, sigma))

Three properties make this safe to build features against.

**Arm-invariance.** ``units_sold`` alone differs between policy arms because
stockouts censor it. ``units_sold + lost_units`` does not — ``demand_rng`` draws
latent demand and nothing else, so two arms see byte-identical demand (the same
invariant ``arms.total_demand`` relies on). Buzz built from the sum keeps every
arm comparison measuring the policy rather than noise.

**It leads.** ``lead_weeks`` shifts demand backwards in time so buzz arrives
*before* the demand it describes. A signal that merely restates history is not a
feature, and building one would silently reward leakage.

**It is deliberately noisy.** ``buzz_noise_sigma`` is tuned so that buzz
correlates with NEXT week's demand at Spearman rho ~0.35, while its correlation
with the CURRENT week stays near 0.2 — a leading indicator, not a restatement. A
clean signal would make any feature built on it look strong for reasons no real
feed would reproduce.

One asymmetry is intentional: the ``Complaint`` intent share rises with own-brand
``lost_units``, which makes it a *lagging* stockout signal — a trap for a feature
build that does not check the direction of causation. Note that ``lost_units``
IS arm-dependent, unlike the buzz channel. This table is emitted once, from the
baseline arm via ``emit.emit_all`` (``emit_counterfactual`` writes only
ground-truth parquets), so nothing is inconsistent today. If per-arm extracts are
ever emitted, hold this channel fixed at the baseline arm.

The table stays at **category grain and never carries a sku_uid or a size**.
That external signals cannot be joined at SKU level is a real property of the
source data, not an artifact to be smoothed away.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from stockout.synth.dims import BRANDS
from stockout.synth.simulate import SimulationResult

ISO_DATETIME = "%Y-%m-%dT%H:%M:%SZ"

# Competitor brands seen in the real feed. Own brands (dims.BRANDS) are emitted
# alongside them so own-vs-competitor share of voice is computable, which every
# real listening tool provides.
COMPETITOR_BRANDS = ["Bata", "Relaxo", "Paragon", "Mochi", "Red Chief", "Khadims"]

SENTIMENTS = ["Positive", "Neutral", "Negative"]
TREND_SIGNALS = ["Trending Up", "Stable", "Trending Down"]
INTENTS = ["Product Inquiry", "Purchase Intent", "Comparison", "Complaint", "Recommendation"]
PLATFORMS = ["Instagram", "X", "YouTube", "Facebook", "Reddit"]
PLATFORM_WEIGHTS = [0.42, 0.23, 0.14, 0.15, 0.06]
POST_TYPES = ["Reel", "Image", "Story", "Video", "Text"]
POST_TYPE_WEIGHTS = [0.34, 0.28, 0.14, 0.13, 0.11]
AUTHOR_TYPES = ["Customer", "Influencer", "Brand", "Retailer"]
AUTHOR_WEIGHTS = [0.62, 0.21, 0.10, 0.07]

# Month -> season tag, so the calendar and the feed agree rather than drifting.
SEASON_BY_MONTH = {
    1: "Winter", 2: "Marathon Season", 3: "Marathon Season",
    4: "Back-to-School", 5: "Back-to-School", 6: "Monsoon",
    7: "Monsoon", 8: "Monsoon", 9: "Festive",
    10: "Festive", 11: "Festive", 12: "Winter",
}
CAMPAIGN_BY_SEASON = {
    "Winter": "Comfort First",
    "Marathon Season": "Street Style",
    "Back-to-School": "Back To School",
    "Monsoon": "Monsoon Ready",
    "Festive": "Festive Collection",
}

LANGUAGE_BY_STATE = {
    "Tamil Nadu": "Tamil", "Karnataka": "Kannada", "Telangana": "Telugu",
    "Kerala": "Malayalam", "Maharashtra": "Marathi", "Gujarat": "Gujarati",
    "West Bengal": "Bengali", "Punjab": "Punjabi", "Assam": "Assamese",
    "Odisha": "Odia",
}

# Engagement rates by platform, as a fraction of reach. Ordering matches the
# platform list and reflects the usual ranking (short video > feed > forum).
LIKE_RATE_BY_PLATFORM = {
    "Instagram": 0.042, "X": 0.011, "YouTube": 0.028,
    "Facebook": 0.016, "Reddit": 0.021,
}
REACH_SHARE_BY_POST_TYPE = {
    "Reel": 0.55, "Video": 0.38, "Image": 0.26, "Story": 0.14, "Text": 0.19,
}

SOCIAL_DEFAULTS = {
    "buzz_lead_weeks": 1,
    "buzz_noise_sigma": 0.9,
    "buzz_smoothing_weeks": 2,
    "trend_threshold": 0.65,
    "base_mentions": 220,
    "posts_per_group_mean": 1.6,
    "max_posts": 25000,
    "complaint_sensitivity": 2.5,
    "follower_growth_weekly": 0.004,
}

COLUMNS = [
    # The 24 columns of the real extract, in its order, so the same validation
    # runs against synthetic and real data without knowing the difference.
    "Brand", "Country", "State", "City", "Handle", "Footwear_Type", "Shoe_Type",
    "Category", "Sub_Category", "Seasonality", "Campaign_Name", "Post_Content",
    "Sentiment", "Trend_Signal", "Customer_Intent", "Mention_Count",
    "Share_of_Voice_Pct", "Influencer_Mention", "Competitor_Mention",
    "page_follower_count", "post_like_count", "post_comment_count",
    "engagement_rate_pct", "post_datetime",
    # Fields a real platform export carries that the supplied sample lacks.
    "post_id", "platform", "post_type", "author_type", "is_verified", "language",
    "hashtags", "reach", "impressions", "post_share_count", "post_save_count",
    "is_repost", "parent_post_id", "brand_is_own",
]


def social_config(defaults: dict | None) -> dict:
    """Social block from the profile config, over the module defaults."""
    config = dict(SOCIAL_DEFAULTS)
    config.update((defaults or {}).get("social", {}) or {})
    return config


def week_start(dates: pd.Series) -> pd.Series:
    """Monday of the week each date falls in."""
    dates = pd.to_datetime(dates)
    return dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")


# --------------------------------------------------------------------------
# the demand signal
# --------------------------------------------------------------------------

def build_demand_index(dims, result: SimulationResult) -> pd.DataFrame:
    """Weekly latent demand per city x product line, normalised to its own mean.

    Latent demand is ``units_sold + lost_units``: what customers wanted, not what
    the shelf happened to allow. That distinction is what makes this identical
    across policy arms.
    """
    panel = result.panel
    city_of_store = dims.stores.set_index("storeid")["city"]

    frame = pd.DataFrame(
        {
            "city": panel["storeid"].map(city_of_store),
            "category": panel["category"],
            "subcat": panel["subcat"],
            "week": week_start(panel["date"]),
            "latent_units": panel["units_sold"].to_numpy() + panel["lost_units"].to_numpy(),
            "lost_units": panel["lost_units"].to_numpy(),
        }
    )
    grouped = frame.groupby(["city", "category", "subcat", "week"], as_index=False)[
        ["latent_units", "lost_units"]
    ].sum()

    line_mean = grouped.groupby(["city", "category", "subcat"])["latent_units"].transform("mean")
    grouped["demand_index"] = grouped["latent_units"] / line_mean.clip(lower=1e-6)
    # A line with no demand at all in a city carries no information; centre it.
    grouped["demand_index"] = grouped["demand_index"].fillna(1.0)
    return grouped


def build_buzz_index(
    dims, result: SimulationResult, rng: np.random.Generator, defaults: dict | None = None
) -> pd.DataFrame:
    """Demand index shifted forward in time and blurred, plus its trend label.

    Returns one row per city x line x week with ``demand_index`` (the truth),
    ``buzz_index`` (what the feed sees) and ``trend_signal``.
    """
    config = social_config(defaults)
    lead = int(config["buzz_lead_weeks"])
    sigma = float(config["buzz_noise_sigma"])

    frame = build_demand_index(dims, result).sort_values(
        ["city", "category", "subcat", "week"]
    ).reset_index(drop=True)

    group = frame.groupby(["city", "category", "subcat"], sort=False)
    # Negative shift pulls FUTURE demand back onto this week, which is what makes
    # buzz a leading indicator rather than a restatement of history.
    leading = group["demand_index"].shift(-lead)
    # The last weeks have no future to draw on. Carry the last known value rather
    # than emitting NaN -- a real feed does not go blank at the window edge.
    leading = leading.fillna(frame["demand_index"])

    # Autocorrelate the NOISE, not the buzz. Independent per-week noise makes the
    # reported series swing wildly, which no listening tool would show -- but
    # smoothing the finished buzz would average in the adjacent week's demand and
    # destroy the lead, leaving buzz correlated with the current week just as
    # strongly as with the next one. Smoothing only the error term keeps buzz[w]
    # a function of demand[w+lead] alone. Rescaling by sqrt(window) holds the
    # noise variance roughly constant so `sigma` still means what it says.
    smoothing = max(int(config["buzz_smoothing_weeks"]), 1)
    frame["_noise"] = rng.normal(0.0, sigma, size=len(frame))
    if smoothing > 1:
        frame["_noise"] = frame.groupby(
            ["city", "category", "subcat"], sort=False
        )["_noise"].transform(
            lambda values: values.rolling(smoothing, min_periods=1).mean()
        ) * np.sqrt(smoothing)

    frame["buzz_index"] = (
        leading.to_numpy() * np.exp(frame["_noise"].to_numpy())
    ).clip(0.05, 12.0)
    frame = frame.drop(columns="_noise")

    threshold = float(config["trend_threshold"])
    previous = frame.groupby(["city", "category", "subcat"], sort=False)["buzz_index"].shift(1)
    change = (frame["buzz_index"] - previous) / previous.clip(lower=1e-6)
    frame["buzz_wow"] = change.fillna(0.0)
    frame["trend_signal"] = np.where(
        frame["buzz_wow"] > threshold, "Trending Up",
        np.where(frame["buzz_wow"] < -threshold, "Trending Down", "Stable"),
    )
    return frame


# --------------------------------------------------------------------------
# the handle dimension
# --------------------------------------------------------------------------

def build_handles(rng: np.random.Generator) -> pd.DataFrame:
    """Accounts that post, with a follower count that belongs to the ACCOUNT.

    The previous emitter redrew ``page_follower_count`` on every row, so one
    handle could have 9M followers in the morning and 600k in the afternoon.
    Follower counts are a slow-moving property of an account, so they are built
    once here and drift upward over the window.
    """
    rows = []
    for brand in list(BRANDS) + COMPETITOR_BRANDS:
        slug = brand.lower().replace(" & ", "").replace(" ", "")
        rows.append(
            {
                "Brand": brand,
                "Handle": f"@{slug}",
                "author_type": "Brand",
                "is_verified": "Yes",
                "base_followers": int(rng.integers(800_000, 9_000_000)),
            }
        )
        for index in range(3):
            rows.append(
                {
                    "Brand": brand,
                    "Handle": f"@{slug}_creator{index + 1}",
                    "author_type": "Influencer",
                    "is_verified": "Yes" if rng.random() < 0.7 else "No",
                    "base_followers": int(rng.integers(40_000, 900_000)),
                }
            )
        for index in range(4):
            rows.append(
                {
                    "Brand": brand,
                    "Handle": f"@shopper_{slug}{index + 1}",
                    "author_type": "Customer",
                    "is_verified": "No",
                    "base_followers": int(rng.integers(200, 25_000)),
                }
            )
        rows.append(
            {
                "Brand": brand,
                "Handle": f"@store_{slug}",
                "author_type": "Retailer",
                "is_verified": "No",
                "base_followers": int(rng.integers(3_000, 120_000)),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# emission
# --------------------------------------------------------------------------

def _weighted_choice(rng, options: list[str], weights: list[float], size: int) -> np.ndarray:
    return np.asarray(options)[rng.choice(len(options), size=size, p=weights)]


def _build_groups(dims, buzz: pd.DataFrame) -> pd.DataFrame:
    """One row per brand x city x line x week -- the aggregate reporting grain."""
    brands = pd.DataFrame(
        {"Brand": list(BRANDS) + COMPETITOR_BRANDS}
    ).assign(brand_is_own=lambda f: f["Brand"].isin(BRANDS).map({True: "Yes", False: "No"}))
    states = dims.stores[["city", "state"]].drop_duplicates()

    groups = buzz.merge(states, on="city", how="left")
    groups = groups.merge(brands, how="cross")
    return groups


def _mention_counts(rng, groups: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Mention volume per brand x city x line x week, and share of voice.

    Share of voice is a ratio of these counts, so it sums to 100 within a
    city x line x week by construction rather than by luck.
    """
    # Own brands hold a smaller share of a feed dominated by larger competitors.
    weight = np.where(groups["brand_is_own"].to_numpy() == "Yes", 0.7, 1.0)
    mean = np.clip(
        float(config["base_mentions"]) * groups["buzz_index"].to_numpy() * weight, 1.0, None
    )
    dispersion = 3.0
    probability = dispersion / (dispersion + mean)
    groups = groups.copy()
    groups["Mention_Count"] = rng.negative_binomial(dispersion, probability) + 1

    total = groups.groupby(["city", "category", "subcat", "week"])["Mention_Count"].transform("sum")
    groups["Share_of_Voice_Pct"] = (groups["Mention_Count"] / total * 100).round(2)
    return groups


def _post_counts(rng, groups: pd.DataFrame, config: dict) -> np.ndarray:
    """Posts to emit per group: at least one, more when buzz is high.

    The floor of one keeps every brand present in every group, which is what lets
    share of voice sum to 100 among the emitted rows.
    """
    extra = rng.poisson(
        np.clip(float(config["posts_per_group_mean"]) * groups["buzz_index"].to_numpy(), 0, 12)
    )
    counts = 1 + extra

    cap = int(config["max_posts"])
    if counts.sum() > cap and len(counts):
        # Trim the extras proportionally; never drop the floor of one per group.
        surplus = counts.sum() - cap
        removable = counts - 1
        if removable.sum() > 0:
            share = removable / removable.sum()
            counts = counts - np.minimum(removable, np.round(share * surplus)).astype(int)
    return np.maximum(counts, 1)


def _sentiment(rng, buzz: np.ndarray) -> np.ndarray:
    """Positive share rises with buzz; negative falls. Never degenerate."""
    positive = np.clip(0.34 + 0.30 * (buzz - 1.0), 0.08, 0.80)
    negative = np.clip(0.30 - 0.22 * (buzz - 1.0), 0.06, 0.60)
    neutral = np.clip(1.0 - positive - negative, 0.05, None)
    stacked = np.vstack([positive, negative, neutral])
    stacked = stacked / stacked.sum(axis=0)

    draw = rng.random(len(buzz))
    out = np.where(
        draw < stacked[0], "Positive",
        np.where(draw < stacked[0] + stacked[1], "Negative", "Neutral"),
    )
    return out


def _intent(rng, buzz: np.ndarray, complaint_pressure: np.ndarray, is_own: np.ndarray,
            sensitivity: float) -> np.ndarray:
    """Purchase intent tracks buzz; complaints track OUR stockouts.

    The complaint channel is a lagging signal deliberately left in the data: a
    feature build that treats every social column as leading will pick it up and
    be wrong in a way that only a directional check catches.
    """
    n = len(buzz)
    weights = np.tile(np.array([0.26, 0.20, 0.18, 0.14, 0.22]), (n, 1))
    weights[:, 1] *= np.clip(buzz, 0.3, 3.0)                       # Purchase Intent
    weights[:, 3] *= 1.0 + sensitivity * complaint_pressure * is_own  # Complaint
    weights = weights / weights.sum(axis=1, keepdims=True)

    cumulative = weights.cumsum(axis=1)
    draw = rng.random((n, 1))
    return np.asarray(INTENTS)[(draw > cumulative).sum(axis=1)]


def _post_content(trend: np.ndarray, intent: np.ndarray, line: np.ndarray) -> np.ndarray:
    """Short mined-text stand-ins, varied by what the post is actually doing."""
    templates = {
        "Complaint": "Could not find {line} in my size at the store again",
        "Purchase Intent": "Looking to pick up {line} this week, any recommendations",
        "Comparison": "Comparing {line} options before buying, thoughts",
        "Recommendation": "Really happy with my {line} purchase, would recommend",
        "Product Inquiry": "Anyone know when {line} restocks in store",
    }
    rising = "Discussions increasing around {line} among footwear shoppers"
    out = np.empty(len(intent), dtype=object)
    for index, (this_intent, this_trend, this_line) in enumerate(zip(intent, trend, line)):
        text = rising if this_trend == "Trending Up" and this_intent == "Product Inquiry" \
            else templates[this_intent]
        out[index] = text.format(line=this_line.lower())
    return out


def emit_external_signals(
    dims,
    result: SimulationResult,
    rng: np.random.Generator,
    out: Path,
    defaults: dict | None = None,
) -> None:
    """Write ``external_signals_fact.csv``: one row per post, category grain."""
    config = social_config(defaults)
    buzz = build_buzz_index(dims, result, rng, defaults)
    groups = _build_groups(dims, buzz)
    groups = _mention_counts(rng, groups, config)

    # Complaint pressure: this city-week's lost units as a share of its own worst
    # week, so the scale is comparable across cities of different sizes.
    peak_loss = groups.groupby("city")["lost_units"].transform("max").clip(lower=1.0)
    groups["complaint_pressure"] = (groups["lost_units"] / peak_loss).clip(0.0, 1.0)

    counts = _post_counts(rng, groups, config)
    posts = groups.loc[groups.index.repeat(counts)].reset_index(drop=True)
    n = len(posts)

    # One handle per post, drawn from the accounts that speak for that brand.
    # Indexed rather than sampled per group: a merge on (Brand, handle_index)
    # stays vectorised and keeps row order aligned with `posts`.
    handles = build_handles(rng)
    handles["handle_index"] = handles.groupby("Brand").cumcount()
    pool_size = posts["Brand"].map(handles.groupby("Brand").size()).to_numpy()
    handle_index = (rng.random(n) * pool_size).astype(int)
    handle_rows = pd.DataFrame(
        {"Brand": posts["Brand"].to_numpy(), "handle_index": handle_index}
    ).merge(handles, on=["Brand", "handle_index"], how="left")

    platform = _weighted_choice(rng, PLATFORMS, PLATFORM_WEIGHTS, n)
    post_type = _weighted_choice(rng, POST_TYPES, POST_TYPE_WEIGHTS, n)

    # --- timing: a real feed clusters at the end of the week and in the evening
    day_offset = rng.choice(7, size=n, p=[0.11, 0.11, 0.12, 0.13, 0.18, 0.19, 0.16])
    hour = rng.choice(
        24, size=n,
        p=np.array([1, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5, 6,
                    6, 5, 5, 5, 6, 8, 10, 12, 12, 9, 6, 3], dtype=float)
        / np.array([1, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5, 6,
                    6, 5, 5, 5, 6, 8, 10, 12, 12, 9, 6, 3], dtype=float).sum(),
    )
    posted = (
        posts["week"]
        + pd.to_timedelta(day_offset, unit="D")
        + pd.to_timedelta(hour, unit="h")
        + pd.to_timedelta(rng.integers(0, 60, size=n), unit="m")
    )
    # Weeks start on Monday, so the first and last weeks can spill outside the
    # simulated calendar. Clip rather than emit posts dated to days no other
    # table has ever heard of.
    calendar = pd.to_datetime(dims.calendar["date"])
    posted = posted.clip(
        lower=calendar.min(), upper=calendar.max() + pd.Timedelta(hours=23, minutes=59)
    )
    # The declared grain is (Brand, City, Footwear_Type, post_datetime), and two
    # posts drawn into the same minute would break it. A real feed stamps each
    # post to the second, so spread collisions out that way rather than widening
    # the grain -- which would cost the equivalent check on the real extract,
    # where post_datetime is all this table has to identify a row.
    posted = posted.dt.floor("min")
    collision = pd.DataFrame(
        {
            "brand": posts["Brand"].to_numpy(),
            "city": posts["city"].to_numpy(),
            "category": posts["category"].to_numpy(),
            "subcat": posts["subcat"].to_numpy(),
            "minute": posted.to_numpy(),
        }
    )
    posted = posted + pd.to_timedelta(
        collision.groupby(list(collision.columns), sort=False).cumcount(), unit="s"
    )

    # --- engagement, internally consistent -----------------------------------
    weeks_elapsed = (
        (posts["week"] - posts["week"].min()).dt.days / 7.0
    ).to_numpy()
    followers = (
        handle_rows["base_followers"].to_numpy()
        * (1.0 + float(config["follower_growth_weekly"])) ** weeks_elapsed
    ).astype(np.int64)

    reach_share = pd.Series(post_type).map(REACH_SHARE_BY_POST_TYPE).to_numpy()
    reach = np.maximum(
        (followers * reach_share * rng.uniform(0.55, 1.45, size=n)).astype(np.int64), 25
    )
    impressions = (reach * rng.uniform(1.1, 1.9, size=n)).astype(np.int64)

    like_rate = pd.Series(platform).map(LIKE_RATE_BY_PLATFORM).to_numpy()
    likes = np.maximum((reach * like_rate * rng.uniform(0.5, 1.6, size=n)).astype(np.int64), 1)
    comments = np.maximum((likes * rng.uniform(0.02, 0.12, size=n)).astype(np.int64), 0)
    shares = np.maximum((likes * rng.uniform(0.01, 0.15, size=n)).astype(np.int64), 0)
    saves = np.maximum((likes * rng.uniform(0.02, 0.20, size=n)).astype(np.int64), 0)
    # The identity the previous emitter broke: this is now checkable.
    engagement = ((likes + comments + shares) / reach * 100).round(2)

    buzz_values = posts["buzz_index"].to_numpy()
    sentiment = _sentiment(rng, buzz_values)
    intent = _intent(
        rng,
        buzz_values,
        posts["complaint_pressure"].to_numpy(),
        (posts["brand_is_own"].to_numpy() == "Yes").astype(float),
        float(config["complaint_sensitivity"]),
    )

    footwear_type = posts["category"].str.cat(posts["subcat"], sep=" - ")
    season = posted.dt.month.map(SEASON_BY_MONTH)
    campaign = season.map(CAMPAIGN_BY_SEASON)
    is_repost = rng.random(n) < 0.08

    frame = pd.DataFrame(
        {
            "Brand": posts["Brand"].to_numpy(),
            "Country": "India",
            "State": posts["state"].to_numpy(),
            "City": posts["city"].to_numpy(),
            "Handle": handle_rows["Handle"].to_numpy(),
            "Footwear_Type": footwear_type.to_numpy(),
            "Shoe_Type": posts["subcat"].str.title().to_numpy(),
            "Category": posts["category"].to_numpy(),
            "Sub_Category": posts["subcat"].to_numpy(),
            "Seasonality": season.to_numpy(),
            "Campaign_Name": campaign.to_numpy(),
            "Post_Content": _post_content(
                posts["trend_signal"].to_numpy(), intent, footwear_type.to_numpy()
            ),
            "Sentiment": sentiment,
            "Trend_Signal": posts["trend_signal"].to_numpy(),
            "Customer_Intent": intent,
            "Mention_Count": posts["Mention_Count"].to_numpy(),
            "Share_of_Voice_Pct": posts["Share_of_Voice_Pct"].to_numpy(),
            "Influencer_Mention": np.where(
                handle_rows["author_type"].to_numpy() == "Influencer", "Yes", "No"
            ),
            "Competitor_Mention": np.where(rng.random(n) < 0.45, "Yes", "No"),
            "page_follower_count": followers,
            "post_like_count": likes,
            "post_comment_count": comments,
            "engagement_rate_pct": engagement,
            "post_datetime": posted.dt.strftime(ISO_DATETIME).to_numpy(),
            "post_id": [f"P{index:09d}" for index in range(n)],
            "platform": platform,
            "post_type": post_type,
            "author_type": handle_rows["author_type"].to_numpy(),
            "is_verified": handle_rows["is_verified"].to_numpy(),
            "language": np.where(
                rng.random(n) < 0.55,
                "English",
                pd.Series(posts["state"].to_numpy()).map(LANGUAGE_BY_STATE).fillna("Hindi"),
            ),
            "hashtags": (
                "#" + posts["subcat"].str.lower().str.replace(" ", "", regex=False)
                + "|#" + campaign.str.lower().str.replace(" ", "", regex=False).to_numpy()
                + "|#footwear"
            ).to_numpy(),
            "reach": reach,
            "impressions": impressions,
            "post_share_count": shares,
            "post_save_count": saves,
            "is_repost": np.where(is_repost, "Yes", "No"),
            "parent_post_id": np.where(
                is_repost, [f"P{max(index - 1, 0):09d}" for index in range(n)], ""
            ),
            "brand_is_own": posts["brand_is_own"].to_numpy(),
        }
    )
    frame[COLUMNS].to_csv(out / "external_signals_fact.csv", index=False)
