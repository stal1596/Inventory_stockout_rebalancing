/**
 * One place where every number on screen gets a plain-English name.
 *
 * The product is read by store and merchandising planners, not by the people who
 * fitted the model. A column header reading `P(out) 14d`, a slider labelled
 * `Forecast error σ` or a footnote naming `store_stockout_rate_90d` is not wrong
 * — it is addressed to the wrong reader, and unfamiliar notation on a screen
 * that is asking someone to move stock costs trust rather than building it.
 *
 * So: the plain label goes front of house, and `technical` keeps the real name
 * one hover away, so anyone reconciling a screen against `docs/model_report.md`
 * or a CSV export can still find their footing. Nothing is hidden, only ordered.
 *
 * Keys are the API field names, so a tooltip is looked up with the same string
 * the row is read with and the two cannot drift apart. `/glossary` renders from
 * this same map for the same reason.
 */

export interface Term {
  /** What the planner reads. */
  label: string;
  /** One or two sentences, no notation. Answers "so what?", not "how?". */
  help: string;
  /** The real name and method, for whoever wants to check our working. */
  technical?: string;
  group: TermGroup;
}

export type TermGroup =
  | "Risk"
  | "Stock"
  | "Money"
  | "What could happen"
  | "Actions"
  | "Reorder policy"
  | "What drives risk"
  | "Model";

/** Section order on the glossary page — most-used first. */
export const GROUP_ORDER: TermGroup[] = [
  "Risk",
  "Stock",
  "Money",
  "What could happen",
  "Actions",
  "Reorder policy",
  "What drives risk",
  "Model",
];

export const GROUP_BLURB: Record<TermGroup, string> = {
  Risk: "How likely a product is to run out, and how urgent that makes it.",
  Stock: "What you have, where it is, and how long it lasts.",
  Money: "What running out costs, and what acting is worth.",
  "What could happen":
    "The simulator plays the next few weeks out thousands of times over. These describe the spread of what it saw.",
  Actions: "The four things you can do about a position, and what each is worth.",
  "Reorder policy":
    "The standing rule that stops the same product running short again next month.",
  "What drives risk":
    "The things the model reads about a position before it forms a view. Each one nudges the predicted stock life up or down.",
  Model: "How much to trust any of this.",
};

export const TERMS: Record<string, Term> = {
  // ---------------------------------------------------------------- Risk ---
  risk_band: {
    label: "Priority",
    help: "How urgently this needs you. It combines how likely the product is to run out with how much it costs when it does, so a slow seller that is certain to empty ranks below a best-seller that probably will.",
    technical:
      "risk_band — Critical / High / Medium / Low, from the 14-day stockout probability crossed with the value at stake",
    group: "Risk",
  },
  risk_score: {
    label: "Risk score",
    help: "A 0–100 number used only to sort the list. It is not a percentage chance — a score of 70 does not mean a 70% chance of running out.",
    technical: "risk_score = 100 × (0.6 × probability + 0.4 × value rank)",
    group: "Risk",
  },
  p_stockout: {
    label: "Chance of running out",
    help: "Of 100 products in this exact position, how many we would expect to sell out before the window closes.",
    technical:
      "p_stockout_14d — conditional stockout probability from the log-normal AFT survival model",
    group: "Risk",
  },
  expected_days_out: {
    label: "Days with empty shelves",
    help: "How many days of the window we expect this product to be unavailable to buy.",
    technical: "expected_days_out",
    group: "Risk",
  },
  predicted_median_days: {
    label: "Expected to last",
    help: "How long the current stock should hold out, for a typical position that looks like this one.",
    technical: "predicted_median_days — the AFT model's median predicted survival time",
    group: "Risk",
  },
  expected_lost_units: {
    label: "Units we'd miss",
    help: "Sales we expect to lose because the shelf is empty when someone comes to buy.",
    technical: "expected_lost_units",
    group: "Risk",
  },

  // --------------------------------------------------------------- Stock ---
  stock_on_hand: {
    label: "On hand",
    help: "Units sitting in the store right now.",
    technical: "stock_on_hand — resolved as of the scoring date, not at spell start",
    group: "Stock",
  },
  cover_days_now: {
    label: "Days left",
    help: "How many days the stock on hand lasts at the rate it has been selling.",
    technical: "cover_days_now = stock_on_hand ÷ trailing demand rate",
    group: "Stock",
  },
  days_of_cover: {
    label: "Days of cover",
    help: "How many days of selling the stock covers.",
    technical: "days_of_cover",
    group: "Stock",
  },
  trailing_demand_rate: {
    label: "Selling per day",
    help: "Average units sold per day recently. Everything about timing is worked out from this rate.",
    technical: "trailing_demand_rate — mean daily units over a 56-day trailing window",
    group: "Stock",
  },
  intransit_units: {
    label: "On its way",
    help: "Units already shipped and expected to land. Stock that has been ordered but not yet dispatched does not count.",
    technical: "intransit_units — committed supply only",
    group: "Stock",
  },
  dc_stock_for_sku: {
    label: "At the warehouse",
    help: "Units of this product sitting at the distribution centre that serves this store.",
    technical: "dc_stock_for_sku",
    group: "Stock",
  },
  open_order_qty: {
    label: "Recently ordered",
    help: "Units on order that are not yet due to arrive.",
    technical: "open_order_qty",
    group: "Stock",
  },
  open_replenishment_orders: {
    label: "Orders on the way",
    help: "Order lines placed but not yet due to land, judged against how long delivery normally takes.",
    technical: "open_replenishment_orders",
    group: "Stock",
  },
  inventory_on_hand_units: {
    label: "Units on the shelf",
    help: "Everything sitting in stores across the network.",
    group: "Stock",
  },
  excess_inventory_units: {
    label: "Overstocked",
    help: "Units beyond 60 days of selling. This is money tied up in stock that will not move for two months.",
    group: "Stock",
  },
  median_days_of_supply: {
    label: "Typical days of stock",
    help: "The middle product has this many days of selling on the shelf. Half have more, half have less.",
    technical: "median_days_of_supply",
    group: "Stock",
  },
  inventory_turnover: {
    label: "Stock turnover",
    help: "How many times a year the stock sells through and is replaced. Higher means leaner stock; too high means you are running on empty.",
    technical:
      "inventory_turnover — units sold ÷ average units held over 90 days, annualised. Sanity-check against your own figures before leaning on it.",
    group: "Stock",
  },
  fill_rate: {
    label: "Orders filled",
    help: "Share of store orders the warehouse could satisfy straight from its own shelves. A low figure here pushes the shortage down to the shops.",
    technical: "fill_rate",
    group: "Stock",
  },
  supplier_on_time_rate: {
    label: "Supplier on time",
    help: "Share of deliveries that arrived by the date the supplier promised.",
    group: "Stock",
  },
  lead_time: {
    label: "Delivery time",
    help: "How long stock takes to arrive once it is ordered.",
    technical: "lead_time — days from order placed to goods received",
    group: "Stock",
  },
  positions_open: {
    label: "Product–store combinations",
    help: "Every product being sold in every store is watched separately, because the same shoe can be fine in one store and about to run out in another.",
    technical: "open store × SKU spells",
    group: "Stock",
  },

  // --------------------------------------------------------------- Money ---
  expected_lost_revenue: {
    label: "Revenue at risk",
    help: "The sales we expect to lose if nothing changes — units we would have missed, at their selling price.",
    technical: "expected_lost_revenue = expected_lost_units × unit price",
    group: "Money",
  },
  inventory_value_at_risk: {
    label: "Revenue at risk",
    help: "Total sales the network expects to lose over the next 14 days if nothing is done about it.",
    group: "Money",
  },
  excess_inventory_value: {
    label: "Overstock value",
    help: "What the excess stock cost to buy — capital sitting still.",
    group: "Money",
  },
  margin_protected: {
    label: "Margin protected",
    help: "The profit kept by acting. Counted at margin, not at ticket price: stock you never sold also never cost you anything to buy.",
    group: "Money",
  },
  net_value: {
    label: "Net value",
    help: "Margin protected, less what the move costs in freight. Negative means the action costs more than it saves.",
    group: "Money",
  },

  // --------------------------------------------- What could happen (sim) ---
  monte_carlo: {
    label: "What could happen",
    help: "We play the next few weeks out thousands of times, each with slightly different demand and delivery timings, and count how those runs ended. It answers 'when', where the risk score answers 'which'.",
    technical: "Monte Carlo forward simulation (montecarlo.py)",
    group: "What could happen",
  },
  days_to_stockout_p10: {
    label: "Earliest likely",
    help: "Things went badly in 1 run out of 10 and the shelf was empty by this day. This is the one to plan against — running out earlier than this is what catches a planner out.",
    technical: "P10 of the simulated time-to-stockout distribution",
    group: "What could happen",
  },
  days_to_stockout_p50: {
    label: "Typical",
    help: "Half the runs had emptied by this day and half had not. The middle outcome.",
    technical: "P50 / median of the simulated time-to-stockout distribution",
    group: "What could happen",
  },
  days_to_stockout_p90: {
    label: "Latest likely",
    help: "Only 1 run in 10 lasted longer than this. Real positions often beat it, because the simulation deliberately ignores orders you have not placed yet.",
    technical: "P90 of the simulated time-to-stockout distribution",
    group: "What could happen",
  },
  forecast_sigma: {
    label: "Forecast error",
    help: "How far demand normally lands from the forecast. Higher means demand is harder to call, so the range of outcomes widens.",
    technical: "forecast_sigma — log-scale standard deviation of forecast error",
    group: "What could happen",
  },
  lead_mean: {
    label: "Delivery time",
    help: "How many days a delivery usually takes, measured from this data rather than assumed.",
    technical: "lead_mean",
    group: "What could happen",
  },
  lead_sigma: {
    label: "Delivery reliability",
    help: "How much delivery times swing about. A supplier averaging 6 days but ranging 2 to 14 needs far more safety stock than one that is always 6.",
    technical: "lead_sigma — standard deviation of observed lead time, in days",
    group: "What could happen",
  },
  dispersion: {
    label: "Demand lumpiness",
    help: "Whether sales trickle steadily or arrive in bursts. Lumpy demand empties a shelf without warning.",
    technical: "dispersion — the negative binomial k",
    group: "What could happen",
  },
  n_paths: {
    label: "Simulation runs",
    help: "How many times we replay the next few weeks. More runs give a steadier answer and take slightly longer.",
    technical: "n_paths",
    group: "What could happen",
  },
  expected_unmet_units: {
    label: "Sales we'd miss",
    help: "Units customers would have bought but could not, averaged across every run.",
    group: "What could happen",
  },
  committed_units: {
    label: "Already on its way",
    help: "Stock in transit today. Orders you might place later are deliberately excluded — otherwise this stops being 'when does it run out' and becomes a test of your ordering policy.",
    group: "What could happen",
  },

  // ------------------------------------------------------------- Actions ---
  recommended_action: {
    label: "Action",
    help: "The best of the four options for this position: move stock from another store, pull it forward from the warehouse, chase the supplier, or leave it alone.",
    group: "Actions",
  },
  no_action_share: {
    label: "Left alone",
    help: "Share of positions where every option costs more than it saves. A tool that always finds something to do is not really choosing.",
    group: "Actions",
  },
  units_saved: {
    label: "Units saved",
    help: "Sales the action rescues, out of the sales that would otherwise be lost.",
    group: "Actions",
  },
  speed: {
    label: "How fast",
    help: "Roughly how long the action takes to put stock on the shelf.",
    group: "Actions",
  },
  donor: {
    label: "From",
    help: "The store the stock would come from — one nearby with more than it needs.",
    group: "Actions",
  },

  // ------------------------------------------------------- Reorder policy ---
  recommended_reorder_point: {
    label: "Reorder at",
    help: "When stock falls to this many units, place the order. It covers expected selling until the delivery lands, plus a buffer for the weeks that run hot.",
    technical: "recommended_reorder_point = lead-time demand + safety stock",
    group: "Reorder policy",
  },
  safety_stock: {
    label: "Buffer",
    help: "The extra units held back to absorb a busy week or a late delivery.",
    technical: "safety_stock",
    group: "Reorder policy",
  },
  service_level: {
    label: "Service level",
    help: "How often you want to avoid running out while waiting for a delivery. 95% means accepting a shortfall in about 1 delivery cycle in 20 — chasing 99% costs a lot more stock.",
    group: "Reorder policy",
  },
  protection_days: {
    label: "Protection window",
    help: "The stretch of time the buffer has to cover: from placing the order to the goods landing.",
    group: "Reorder policy",
  },
  textbook_reorder_point: {
    label: "Textbook figure",
    help: "What the standard formula gives, for comparison. It assumes demand is neat and evenly spread, which shoe sizes are not.",
    technical: "textbook_reorder_point — normal-approximation reorder point",
    group: "Reorder policy",
  },
  dispersion_k: {
    label: "Demand lumpiness",
    help: "How bursty demand is. Keeping this in the maths matters most on slow-moving sizes, which is exactly where a size run breaks first.",
    technical: "dispersion_k — the negative binomial k",
    group: "Reorder policy",
  },
  incumbent_rule: {
    label: "Rule in force today",
    help: "The reordering rule currently being followed, so any recommendation can be judged against it.",
    group: "Reorder policy",
  },

  // --------------------------------------------------------------- Model ---
  c_index: {
    label: "Ranking accuracy",
    help: "Given two products, how often the model correctly picks the one that runs out first — tested on data it never saw while learning. 50% would be a coin flip.",
    technical: "c_index — held-out concordance of the log-normal AFT survival model",
    group: "Model",
  },

  // ----------------------------------------------------- What drives risk ---
  // Absorbed from the old FEATURE_LABELS map so a feature name has exactly one
  // plain label, whether it is read as a table column or as a driver bar.
  log_days_of_cover: {
    label: "Days of cover",
    help: "How long the stock lasts at the current selling rate. This is the strongest single driver of risk, and the one you have most control over.",
    technical: "log_days_of_cover",
    group: "What drives risk",
  },
  log_start_stock: {
    label: "Stock on hand",
    help: "How many units were on the shelf when we started watching this position.",
    technical: "log_start_stock",
    group: "What drives risk",
  },
  log_trailing_demand: {
    label: "Selling rate",
    help: "How fast the product has been selling recently.",
    technical: "log_trailing_demand",
    group: "What drives risk",
  },
  demand_acceleration: {
    label: "Selling faster",
    help: "Whether the product is picking up speed compared with a few weeks ago.",
    group: "What drives risk",
  },
  demand_cv: {
    label: "Choppy demand",
    help: "How much sales bounce around week to week. Steady sellers are easier to keep in stock.",
    group: "What drives risk",
  },
  intermittency: {
    label: "Sells in fits and starts",
    help: "Days with no sales at all between days with several. Common on end sizes.",
    group: "What drives risk",
  },
  size_run_completeness: {
    label: "Broken size run",
    help: "Whether neighbouring sizes of the same shoe are already missing. A broken run costs sales beyond the size that ran out.",
    group: "What drives risk",
  },
  size_extremity: {
    label: "Edge size",
    help: "How far this size sits from the middle of the run. The smallest and largest sizes behave differently.",
    group: "What drives risk",
  },
  log_dc_stock: {
    label: "Warehouse stock",
    help: "Units at the distribution centre — cover behind the store, if it can be moved in time.",
    technical: "log_dc_stock",
    group: "What drives risk",
  },
  days_since_last_receipt: {
    label: "Days since delivery",
    help: "How long since this store last received the product.",
    group: "What drives risk",
  },
  prior_stockouts_90d: {
    label: "Past stockouts",
    help: "How often this product has already run out here in the last three months.",
    group: "What drives risk",
  },
  prior_stockout_rate: {
    label: "Stockout history",
    help: "How often this position has run out before.",
    group: "What drives risk",
  },
  store_stockout_rate_90d: {
    label: "Store's track record",
    help: "How often this store runs out across everything it sells. It marks stores that struggle, but there is no lever behind it — you cannot fix a position by fixing this number.",
    technical: "store_stockout_rate_90d — a store fixed effect, not an actionable cause",
    group: "What drives risk",
  },
  promo_days_ahead: {
    label: "Promotion coming",
    help: "A promotion is due, which will pull demand forward.",
    group: "What drives risk",
  },
  holiday_days_ahead: {
    label: "Holiday coming",
    help: "A holiday falls inside the window, lifting demand.",
    group: "What drives risk",
  },
  seasonality_index: {
    label: "Season",
    help: "Whether this time of year usually runs hot or quiet for this product.",
    group: "What drives risk",
  },
  starts_on_weekend: {
    label: "Weekend start",
    help: "The window opens on a weekend, when shops are busier.",
    group: "What drives risk",
  },
  forecast_units_month: {
    label: "Forecast volume",
    help: "What the demand forecast expects this product to sell.",
    group: "What drives risk",
  },
  forecast_vs_trailing: {
    label: "Forecast vs actual",
    help: "Whether recent sales are running ahead of or behind the forecast.",
    group: "What drives risk",
  },
  log_price: {
    label: "Price",
    help: "The unit price. It sets what each missed sale costs.",
    technical: "log_price",
    group: "What drives risk",
  },
  tier_rank: {
    label: "Store tier",
    help: "How big and busy this store is compared with the rest.",
    group: "What drives risk",
  },
  demand_rate_imputed: {
    label: "Selling rate estimated",
    help: "There was too little sales history here, so the rate was filled in from similar products. Treat the position with more caution.",
    group: "What drives risk",
  },
};

/**
 * Horizon-suffixed and prefixed variants resolve to the same term.
 *
 * `p_stockout_7d`, `p_stockout_14d` and `p_stockout_28d` are one idea measured
 * over three windows, and the simulator prefixes its own copies with `mc_`.
 * Without this, every horizon would need its own near-identical entry and they
 * would drift apart the first time one of them was edited.
 */
const normalise = (key: string) => key.replace(/^mc_/, "").replace(/_\d+d$/, "");

/**
 * One-hot encoded categories cannot be listed above: there is one per zone and
 * one per product category, and the set is whatever the extract happens to
 * contain. They reached the driver panel reading "Zonecat SOUTH", so they are
 * expanded by rule instead.
 */
const ONE_HOT: Record<string, { label: string; help: string }> = {
  zonecat: {
    label: "Zone",
    help: "Which part of the country the store sits in. Zones differ in how fast stock sells and in how quickly it can be moved between shops.",
  },
  prodcat: {
    label: "Product type",
    help: "The kind of product this is. Types sell at different speeds and are restocked on different cycles.",
  },
};

const oneHot = (key: string) => {
  const cut = key.indexOf("_");
  if (cut < 1) return undefined;
  const family = ONE_HOT[key.slice(0, cut)];
  const value = key.slice(cut + 1);
  return family && value ? { family, value } : undefined;
};

const titleCase = (text: string) =>
  text.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

export const term = (key: string): Term | undefined => {
  const found = TERMS[key] ?? TERMS[normalise(key)];
  if (found) return found;
  const hot = oneHot(key);
  if (!hot) return undefined;
  return {
    label: `${hot.family.label}: ${titleCase(hot.value)}`,
    help: hot.family.help,
    technical: key,
    group: "What drives risk",
  };
};

/** Title-case an unmapped identifier rather than showing raw snake_case. */
export const prettify = (key: string) => {
  const hot = oneHot(key);
  if (hot) return `${hot.family.label}: ${titleCase(hot.value)}`;
  return titleCase(key.replace(/^(log|mc)_/, ""));
};
