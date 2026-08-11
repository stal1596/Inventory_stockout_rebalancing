import type { Band } from "./api";

export const num = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${(value * 100).toFixed(digits)}%`;

/** Money is compacted because exposure runs into the millions and a control
 *  tower is read at a glance, not audited from. Exact figures live in tables. */
export const money = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${(value / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(value / 1e5).toFixed(1)}L`;
  if (abs >= 1e3) return `₹${(value / 1e3).toFixed(0)}k`;
  return `₹${value.toFixed(0)}`;
};

export const days = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(digits)}d`;

/** Status colours, reserved. Never used for a chart series. */
export const bandColor: Record<Band, string> = {
  Critical: "var(--status-critical)",
  High: "var(--status-serious)",
  Medium: "var(--status-warning)",
  Low: "var(--status-good)",
};

export const severityColor: Record<string, string> = {
  critical: "var(--status-critical)",
  warning: "var(--status-warning)",
  info: "var(--series-1)",
};

/** Feature names are engineering identifiers; planners read English. */
const FEATURE_LABELS: Record<string, string> = {
  log_days_of_cover: "Days of cover",
  days_of_cover: "Days of cover",
  log_start_stock: "Stock on hand",
  log_trailing_demand: "Demand rate",
  trailing_demand_rate: "Demand rate",
  demand_acceleration: "Demand accelerating",
  demand_cv: "Demand volatility",
  intermittency: "Intermittent demand",
  size_run_completeness: "Size run broken",
  size_extremity: "Size at run edge",
  intransit_units: "Stock in transit",
  dc_stock_for_sku: "DC stock",
  log_dc_stock: "DC stock",
  open_order_qty: "Recently ordered",
  days_since_last_receipt: "Days since delivery",
  prior_stockouts_90d: "Past stockouts",
  prior_stockout_rate: "Stockout history",
  store_stockout_rate_90d: "Store performance",
  promo_days_ahead: "Promotion ahead",
  holiday_days_ahead: "Holiday ahead",
  seasonality_index: "Seasonality",
  starts_on_weekend: "Weekend start",
  forecast_units_month: "Forecast volume",
  forecast_vs_trailing: "Forecast vs actual",
  lead_time: "Supplier lead time",
  log_price: "Unit price",
  tier_rank: "Store tier",
  demand_rate_imputed: "Demand estimated",
};

export const featureLabel = (name: string) =>
  FEATURE_LABELS[name] ??
  name.replace(/^log_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const ACTION_COLORS: Record<string, string> = {
  rebalance_from_store: "var(--series-3)",
  expedite_from_dc: "var(--series-1)",
  expedite_from_supplier: "var(--series-2)",
  no_action: "var(--text-muted)",
};

export const ACTION_LABELS: Record<string, string> = {
  rebalance_from_store: "Transfer between stores",
  expedite_from_dc: "Expedite from DC",
  expedite_from_supplier: "Expedite supplier",
  no_action: "No action",
};
