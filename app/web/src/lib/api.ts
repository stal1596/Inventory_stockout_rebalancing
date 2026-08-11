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
  impact: string;
}

export interface RecommendationDetail extends Omit<Recommendation, "action_label" | "speed"> {
  recommended: string;
  recommended_label: string;
  options: {
    action: string; label: string; speed: string;
    feasible: boolean; net_value: number | null; chosen: boolean;
  }[];
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

export const api = {
  kpis: () => get<Kpis>("/api/overview/kpis"),
  alerts: () => get<{ alerts: Alert[]; as_of: string }>("/api/overview/alerts"),
  trend: (days = 120) =>
    get<{ series: { date: string; on_hand: number; units_sold: number; received: number; dc_stock: number }[] }>(
      `/api/overview/trend?days=${days}`,
    ),

  positions: (params: Record<string, string | number | undefined>) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return get<{ total: number; exposure: number; bands: Kpis["bands"]; rows: Position[] }>(
      `/api/risk/positions?${query}`,
    );
  },
  position: (storeId: string, skuUid: string) =>
    get<PositionDetail>(`/api/risk/positions/${storeId}/${skuUid}`),
  driverSummary: () =>
    get<{ drivers: { feature: string; times_top_driver: number; coefficient: number; share_of_rows: number }[] }>(
      "/api/risk/drivers/summary",
    ),

  simulate: (body: Record<string, unknown>) => post<Simulation>("/api/simulate/position", body),

  recommendations: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return get<{
      rows: Recommendation[];
      mix: { recommended_action: string; positions: number; units_saved: number; net_value: number }[];
      no_action_share: number;
      total_net_value: number;
      caveat: string;
    }>(`/api/prescribe/recommendations?${query}`);
  },
  recommendation: (storeId: string, skuUid: string) =>
    get<RecommendationDetail>(`/api/prescribe/${storeId}/${skuUid}`),

  filters: () =>
    get<{
      stores: { store_id: string; city: string; zone: string; tier: string }[];
      categories: string[]; bands: Band[]; horizons: number[]; as_of: string;
    }>("/api/catalog/filters"),
  topology: () => get<any>("/api/network/topology"),
  provenance: () => get<any>("/api/data/provenance"),
  inventory: () => get<any>("/api/inventory/summary"),
  health: () => get<{ status: string; positions: number; c_index: number }>("/api/health"),
};
