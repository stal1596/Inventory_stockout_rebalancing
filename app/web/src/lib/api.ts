/** Typed client for the control-tower API. */

export type Band = "Critical" | "High" | "Medium" | "Low";

export interface KpiHorizon { positions: number; revenue: number }

export interface Kpis {
  as_of: string;
  positions_open: number;
  skus_at_risk: number;
  horizons: Record<"7" | "14" | "28", KpiHorizon>;
  inventory_on_hand_units: number;
  inventory_at_dc_units: number;
  inventory_inbound_units: number;
  inventory_value_at_risk: number;
  excess_inventory_units: number;
  excess_inventory_value: number;
  median_days_of_supply: number | null;
  inventory_turnover: number;
  open_replenishment_orders: number;
  supplier_on_time_rate: number | null;
  supplier_available: boolean;
  model: { c_index: number; spells_trained: number; features: number };
  bands: { band: Band; positions: number; lost_units: number; lost_revenue: number }[];
}

export interface Alert {
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  metric: number | null;
  link: { page: string; params: Record<string, string | number> };
}

export interface Position {
  store_id: string;
  sku_uid: string;
  category?: string;
  size_label?: string;
  risk_band: Band;
  risk_score: number;
  stock_on_hand: number;
  cover_days_now: number | null;
  start_stock: number;
  days_of_cover: number | null;
  trailing_demand_rate: number;
  p_stockout_7d: number | null;
  p_stockout_14d: number | null;
  p_stockout_28d: number | null;
  expected_days_out: number;
  expected_lost_units: number;
  expected_lost_revenue: number;
  intransit_units?: number | null;
  dc_stock_for_sku?: number | null;
  lead_time?: number | null;
}

export interface Driver {
  feature: string;
  days_effect: number;
  direction: "increases_risk" | "reduces_risk";
  actionable: boolean;
  value: number | string | null;
}

export interface PositionDetail {
  position: Position;
  as_of: string;
  predicted_median_days: number;
  reference_median_days: number;
  drivers: Driver[];
  timeline: { day: number; date: string; projected_stock: number }[];
  explanation: string;
}

export interface SimulationArm {
  p_stockout: number;
  days_to_stockout: { p10: number | null; p50: number | null; p90: number | null };
  expected_days_out: number;
  expected_unmet_units: number;
  by_day: {
    day: number; date: string; probability: number;
    p10_stock: number; p50_stock: number; p90_stock: number;
  }[];
  histogram: { day: number; paths: number; share: number }[];
}

export interface Simulation {
  store_id: string;
  sku_uid: string;
  horizon: number;
  paths: number;
  position: { start_stock: number; committed_units: number; demand_rate: number };
  baseline: SimulationArm;
  scenario: SimulationArm;
  calibration: {
    forecast_bias: number; forecast_sigma: number; dispersion: number;
    lead_mean: number; lead_sigma: number; lead_observations: number; note: string;
  };
}

export interface Recommendation {
  store_id: string;
  sku_uid: string;
  /** The lever CODE — `rebalance_from_store` etc. Keys ACTION_COLORS/ACTION_LABELS. */
  action: string;
  action_label: string;
  speed: string;
  donor: string | null;
  units_saved: number;
  net_value: number;
  margin_protected: number;
  baseline_lost_units: number;
  problem: string;
  evidence: string;
  /** The narrative sentence. Distinct from `action`, which is the code. */
  action_text: string;
  impact: string;
}

export interface RecommendationDetail
  extends Omit<Recommendation, "action" | "action_label" | "speed"> {
  recommended: string;
  recommended_label: string;
  options: {
    action: string; label: string; speed: string;
    feasible: boolean; net_value: number | null; chosen: boolean;
  }[];
}

export interface ActionMix {
  recommended_action: string;
  positions: number;
  units_saved?: number;
  net_value?: number;
  margin_protected?: number;
  share?: number;
}

export interface Feed {
  horizon: number;
  total: number;
  rows: Recommendation[];
  mix: ActionMix[];
  no_action_share: number;
  total_net_value: number;
  caveat: string;
}

export interface ScenarioFeed extends Feed {
  scenario: true;
  positions: number;
  defaults: { horizon: number; n_paths: number; margin_rate: number; costs: Record<string, number> };
  applied: { horizon: number; n_paths: number; margin_rate: number; costs: Record<string, number> | null };
  delta_vs_default: {
    no_action_share_default: number | null;
    no_action_share_scenario: number;
    net_value_default: number | null;
    net_value_scenario: number;
    note: string;
  };
}

/* ---------------------------------------------------------------- */
/* Reorder policy                                                    */
/* ---------------------------------------------------------------- */

export type Estimator = "lead_time_demand" | "model_inversion";

export interface LeadTime {
  observed: { n: number; mean: number; std: number; p50: number; p90: number } | null;
  inferred: { n: number; mean: number | null; std: number | null; p95: number | null };
  histogram: { days: number; receipts: number }[];
  note?: string;
  by_store?: { store_id: string; n: number; mean: number; std: number; p90: number }[];
}

export interface ReorderRow {
  store_id: string;
  sku_uid: string;
  category?: string;
  stock_on_hand: number;
  cover_days_now: number | null;
  trailing_demand_rate: number;
  recommended_reorder_point: number;
  recommended_cover_days: number;
  safety_stock: number;
  expected_demand_over_lead: number;
  textbook_reorder_point: number;
  below_reorder_point: boolean;
}

export interface ReorderPolicy {
  estimator: Estimator;
  estimator_label: string;
  /** False for the model-inversion estimator, which failed its backtest. */
  validated: boolean;
  warning: string | null;
  basis: string;
  service_level: number;
  protection_days: number | null;
  dispersion_k: number | null;
  lead_time: LeadTime;
  incumbent: { rule: string; cover_days: number };
  total: number;
  positions_below_reorder_point: number;
  rows: ReorderRow[];
  verdict: string;
  caveat: string;
}

/* ---------------------------------------------------------------- */
/* Model evidence                                                    */
/* ---------------------------------------------------------------- */

export interface ModelEvaluation {
  models: {
    model: string; n_train: number; n_test: number;
    events_train: number; events_test: number;
    c_index_train: number; c_index_test: number;
    brier_7d: number; brier_14d: number; brier_28d: number;
    calibration_max_gap: number;
  }[];
  primary: string;
  split_date: string;
  note: string;
  comparability: string;
}

export interface CalibrationBin {
  bin: number; n: number; predicted_mean: number; observed_km: number; gap: number;
}

export interface Calibration {
  horizon: number;
  bins: CalibrationBin[];
  max_gap: number | null;
  brier: number;
  n_test: number;
  note: string;
}

export type KmBias =
  | { available: false; reason: string }
  | {
      available: true;
      reason: string;
      median_naive: number;
      median_true: number;
      median_gap_days: number;
      max_vertical_gap: number;
      gap_at: number;
      direction: "optimistic" | "pessimistic";
      n_naive: number;
      n_true: number;
      censored_share: number;
      curve: { t: number; naive: number; true: number; difference: number }[];
      summary: string;
      question: string;
    };

export interface CompetingRisks {
  partition_error: number;
  curve: {
    t: number; cif_stockout: number; cif_replenished: number;
    survival_any: number; total: number;
  }[];
  aj_vs_empirical_max_gap: number;
  aj_vs_empirical_days: number;
  question: string;
  note: string;
}

export interface Coefficients {
  family: string;
  scale: string;
  coefficients: {
    feature: string; coefficient: number | null; group: string;
    actionable: boolean;
    /** Set when the sign misleads even though a lever exists. */
    caution: string | null;
    reference_mean: number | null;
  }[];
  n_features: number;
  note: string;
  cover_coefficient: number | null;
  cover_note: string;
}

export interface FeatureRegistry {
  features: {
    name: string; group: string; kind: string; fillna: unknown;
    requires: string[]; depends: string[]; in_model: boolean; description: string;
  }[];
  n_registered: number;
  n_fitted: number;
  groups: { group: string; n: number }[];
  encoded: string[];
  note: string;
  windows: { trailing_window_days: number; burn_in_days: number; note: string };
}

/* ---------------------------------------------------------------- */
/* Data quality                                                      */
/* ---------------------------------------------------------------- */

export interface Finding {
  check: string; table: string; passed: boolean; severity: string;
  summary: string; n_bad: number; n_total: number; bad_rate: number;
  examples: string; detail: string;
}

export interface Validation {
  checks: Finding[];
  n_checks: number;
  n_failed: number;
  n_blocking: number;
  n_shown: number;
  scope: { module: string; note: string };
}

export interface Movement {
  transitions: number;
  unexplained_loss_events: number;
  unexplained_loss_units: number;
  unexplained_share_of_sales: number;
  worst_single_loss: number;
  instrument: string;
  note: string;
  why_metrics_will_not_warn_you: string;
}

export interface DcStructure {
  verdict: string;
  varying_share: number;
  n_groups: number;
  groups: unknown;
  note: string;
}

/* ---------------------------------------------------------------- */
/* Backtests                                                         */
/* ---------------------------------------------------------------- */

/**
 * Every statistic is optional: `score_against_truth` returns `{n: 0}` alone when
 * nothing in the window was observable, and non-finite values serialise as null.
 */
export interface SimulationBacktest {
  as_of: string; panel_end: string; horizon: number; n_paths: number;
  n_positions: number; n: number;
  coverage_p10_p90?: number | null;
  breach_below_p10?: number | null;
  breach_above_p90?: number | null;
  median_error_days?: number | null;
  p_stockout_mean?: number | null;
  actual_stockout_rate?: number | null;
  expected: { coverage_p10_p90: number; breach_below_p10: number; breach_above_p90: number };
  note: string;
}

/**
 * `precision`/`recall` are null when nothing was acted on, and
 * `stockout_rate_when_not` is null when everything was — both legitimate, and
 * both reached the wire as NaN until the API routed them through `jsonable`.
 */
export interface DecisionBacktest {
  as_of: string; panel_end: string; horizon: number; n_paths: number;
  n_scored: number; n: number;
  acted_share?: number | null;
  precision?: number | null;
  recall?: number | null;
  stockout_rate_when_acted?: number | null;
  stockout_rate_when_not?: number | null;
  base_rate?: number | null;
  mix: ActionMix[];
  note: string;
  read_as: string;
}

/* ---------------------------------------------------------------- */
/* Population simulation                                             */
/* ---------------------------------------------------------------- */

export interface PopulationSimulation {
  as_of: string; horizon: number; paths: number; positions: number;
  aggregate: {
    p_stockout_mean: number;
    positions_likely_out: number;
    expected_days_out_mean: number;
    expected_unmet_units: number;
    by_horizon: { day: number; share: number }[];
  };
  rows: {
    store_id: string; sku_uid: string; stock_on_hand: number;
    committed_units: number; trailing_demand_rate: number;
    mc_p_stockout: number;
    mc_days_to_stockout_p10: number | null;
    mc_days_to_stockout_p50: number | null;
    mc_days_to_stockout_p90: number | null;
    mc_expected_days_out: number;
    expected_unmet_units: number;
  }[];
  calibration: {
    forecast_bias: number; forecast_sigma: number; dispersion: number;
    lead_mean: number; lead_sigma: number; summary: string;
  };
  note: string;
}

/* ---------------------------------------------------------------- */
/* Descriptive views that used to be `any`                           */
/* ---------------------------------------------------------------- */

export interface Supplier {
  available: boolean;
  reason: string;
  vendors: {
    vendor: string; receipts: number; on_time_rate: number;
    lead_days_promised: number; lead_days_actual: number;
    lead_days_std: number; days_late_p90: number; units: number;
  }[];
}

export interface InventorySummary {
  on_hand_units: number;
  dc_units: number;
  intransit_units: number;
  excess_units: number;
  turnover: number | null;
  median_days_of_supply: number | null;
  by_store: { store_id: string; on_hand: number; skus: number; excess: number }[];
  cover_distribution: { bucket: string; positions: number }[];
  supplier: Supplier;
  lead_time: LeadTime;
  forecast: {
    available: boolean;
    weeks: { week: string; forecast: number; actual: number; error: number }[];
    /** Ratio of forecast to actual. Null when the window has no actuals. */
    bias: number | null;
    mape: number | null;
  };
}

/** `config/network.yaml` transfers block, passed through verbatim. */
export interface TransferPolicy {
  enabled?: boolean;
  scope?: string;
  lead_days?: number[];
  cost_per_unit?: number;
  min_donor_cover_days?: number;
}

export interface Topology {
  vendors: {
    id: string; type: "vendor"; name: string;
    lead_time_days: number; lead_time_sigma: number; reliability: number;
    on_time_rate: number | null; receipts: number;
  }[];
  dcs: {
    id: string; type: "dc"; name: string; zones: string[];
    fill_rate: number; lead_days: number[]; stores: string[]; on_hand: number;
  }[];
  stores: {
    id: string; type: "store"; city: string; zone: string; tier: string;
    dc: string | null; positions: number; at_risk: number;
    exposure: number; on_hand: number;
  }[];
  transfers: TransferPolicy;
  recovered: string;
}

export interface Provenance {
  tables: {
    table: string; file: string; rows: number;
    in_synthetic: boolean; in_supplied_extract: boolean;
    synthesized_note: string | null; description: string;
  }[];
  model: {
    family: string; c_index: number; spells_train: number;
    spells_test: number; features: string[]; split_date: string;
  };
  lead_time: LeadTime;
  note: string;
}

type Params = Record<string, string | number | boolean | undefined>;

/**
 * Read the error body, don't discard it.
 *
 * FastAPI puts the useful sentence in `detail`, and two endpoints depend on it
 * being seen: the backtest 400 names the latest date that leaves room to observe
 * an outcome, and the population simulation's 422 names which knob to reduce.
 * Throwing `"400 /api/backtest/simulation"` turns specific, actionable guidance
 * into a status code.
 */
async function failure(response: Response, path: string): Promise<Error> {
  let detail = "";
  try {
    const body = await response.json();
    detail = typeof body?.detail === "string"
      ? body.detail
      : Array.isArray(body?.detail)
        // FastAPI validation errors are a list of {loc, msg, type}.
        ? body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
        : "";
  } catch {
    // A non-JSON body (a proxy timeout, an HTML error page) leaves detail empty.
  }
  return new Error(detail || `${response.status} ${path}`);
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw await failure(response, path);
  return response.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response, path);
  return response.json();
}

export const api = {
  kpis: () => get<Kpis>("/api/overview/kpis"),
  alerts: () => get<{ alerts: Alert[]; as_of: string }>("/api/overview/alerts"),
  trend: (days = 120) =>
    get<{ series: { date: string; on_hand: number; units_sold: number; received: number; dc_stock: number }[] }>(
      `/api/overview/trend?days=${days}`,
    ),

  positions: (params: Params) =>
    get<{ total: number; exposure: number; bands: Kpis["bands"]; rows: Position[] }>(
      `/api/risk/positions${query(params)}`,
    ),
  position: (storeId: string, skuUid: string) =>
    get<PositionDetail>(`/api/risk/positions/${storeId}/${skuUid}`),
  driverSummary: () =>
    get<{ drivers: { feature: string; times_top_driver: number; coefficient: number; share_of_rows: number }[] }>(
      "/api/risk/drivers/summary",
    ),

  simulate: (body: Record<string, unknown>) => post<Simulation>("/api/simulate/position", body),
  simulatePopulation: (body: Record<string, unknown>) =>
    post<PopulationSimulation>("/api/simulate/population", body),
  simulationCalibration: () =>
    get<PopulationSimulation["calibration"] & { lead_observations: number; weekday_factor: number[] }>(
      "/api/simulate/calibration",
    ),

  recommendations: (params: Params = {}) =>
    get<Feed>(`/api/prescribe/recommendations${query(params)}`),
  recommendation: (storeId: string, skuUid: string) =>
    get<RecommendationDetail>(`/api/prescribe/${storeId}/${skuUid}`),
  prescribeScenario: (body: Record<string, unknown>) =>
    post<ScenarioFeed>("/api/prescribe/run", body),

  reorderPoints: (params: Params = {}) =>
    get<ReorderPolicy>(`/api/policy/reorder-points${query(params)}`),
  leadTime: (by: "none" | "store" = "none") =>
    get<LeadTime>(`/api/policy/lead-time${query({ by })}`),

  modelEvaluation: () => get<ModelEvaluation>("/api/model/evaluation"),
  modelCalibration: (horizon = 14, bins = 10) =>
    get<Calibration>(`/api/model/calibration${query({ horizon, bins })}`),
  kmBias: () => get<KmBias>("/api/model/km-bias"),
  competingRisks: () => get<CompetingRisks>("/api/model/competing-risks"),
  coefficients: () => get<Coefficients>("/api/model/coefficients"),
  featureRegistry: () => get<FeatureRegistry>("/api/model/features"),

  validation: (params: Params = {}) => get<Validation>(`/api/data/validation${query(params)}`),
  movement: () => get<Movement>("/api/data/movement"),
  dcStructure: () => get<DcStructure>("/api/data/dc-structure"),

  backtestSimulation: (params: Params = {}) =>
    get<SimulationBacktest>(`/api/backtest/simulation${query(params)}`),
  backtestDecisions: (params: Params = {}) =>
    get<DecisionBacktest>(`/api/backtest/decisions${query(params)}`),

  filters: () =>
    get<{
      stores: { store_id: string; city: string; zone: string; tier: string }[];
      categories: string[]; bands: Band[]; horizons: number[]; as_of: string;
    }>("/api/catalog/filters"),
  topology: () => get<Topology>("/api/network/topology"),
  provenance: () => get<Provenance>("/api/data/provenance"),
  inventory: () => get<InventorySummary>("/api/inventory/summary"),
  health: () =>
    get<{ status: string; as_of: string; positions: number; c_index: number; load_seconds: number }>(
      "/api/health",
    ),
};

/**
 * CSV exports are a plain link, not a fetch.
 *
 * The response carries `Content-Disposition: attachment`, so the browser saves it
 * and names the file from the header. Fetching it into a blob would work but
 * would throw that filename away and hold the whole file in memory for nothing.
 */
export const exportUrl = {
  risk: (params: Params = {}) => `/api/export/risk.csv${query(params)}`,
  prescriptions: (params: Params = {}) => `/api/export/prescriptions.csv${query(params)}`,
  policy: (params: Params = {}) => `/api/export/policy.csv${query(params)}`,
  validation: () => "/api/export/validation.csv",
};
