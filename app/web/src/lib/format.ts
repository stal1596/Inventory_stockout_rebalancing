import type { Band } from "./api";
import { prettify, term } from "./glossary";

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

/**
 * Feature names are engineering identifiers; planners read English.
 *
 * The map itself now lives in `glossary.ts` alongside every other label, because
 * four of these names (`trailing_demand_rate`, `intransit_units`,
 * `dc_stock_for_sku`, `lead_time`) are also risk-table columns and were being
 * named twice, in two files, with nothing keeping the two spellings in step.
 */
export const featureLabel = (name: string) => term(name)?.label ?? prettify(name);

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
