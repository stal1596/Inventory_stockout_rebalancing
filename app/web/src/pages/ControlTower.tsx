import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Alert, type Kpis } from "../lib/api";
import { bandColor, money, num, pct, severityColor } from "../lib/format";
import { BandBadge, Card, Empty, Kpi, Note, Spinner } from "../components/ui";
import { TrendChart } from "../components/charts";
import { useStore } from "../store";

export function ControlTower() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [trend, setTrend] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.kpis(), api.alerts(), api.trend(120)])
      .then(([k, a, t]) => { setKpis(k); setAlerts(a.alerts); setTrend(t.series); })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <Empty>Could not reach the API. {error}</Empty>;
  if (!kpis) return <Spinner label="Loading the network position…" />;

  const h7 = kpis.horizons["7"];
  const h14 = kpis.horizons["14"];
  const h28 = kpis.horizons["28"];

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        <Kpi label="Positions at risk" value={num(kpis.skus_at_risk)}
             tone={bandColor.High}
             sub={`of ${num(kpis.positions_open)} open store × SKU`}
             hint="Critical or High band: likely to run out AND expensive when it does." />
        <Kpi label="Value at risk" value={money(kpis.inventory_value_at_risk)}
             sub="expected lost revenue, 14 days"
             hint="Expected days out of stock × demand rate × price." />
        <Kpi label="Stock out ≤ 7 days" value={num(h7.positions)}
             tone={bandColor.Critical} sub={money(h7.revenue) + " exposed"} />
        <Kpi label="Stock out ≤ 14 days" value={num(h14.positions)}
             sub={money(h14.revenue) + " exposed"} />
        <Kpi label="Stock out ≤ 28 days" value={num(h28.positions)}
             sub={money(h28.revenue) + " exposed"} />

        <Kpi label="On hand" value={num(kpis.inventory_on_hand_units)}
             sub={`${num(kpis.inventory_at_dc_units)} at DC · ${num(kpis.inventory_inbound_units)} inbound`} />
        <Kpi label="Median days of supply" value={kpis.median_days_of_supply ?? "—"}
             sub={`turnover ${kpis.inventory_turnover}× annualised`} />
        <Kpi label="Excess inventory" value={num(kpis.excess_inventory_units)}
             sub="units beyond 60 days of cover" />
        <Kpi label="Open replenishment" value={num(kpis.open_replenishment_orders)}
             sub="order lines in the window" />
        <Kpi label="Supplier on-time"
             value={kpis.supplier_available ? pct(kpis.supplier_on_time_rate) : "n/a"}
             tone={kpis.supplier_on_time_rate && kpis.supplier_on_time_rate < 0.8
               ? bandColor.High : undefined}
             sub={kpis.supplier_available ? "across all vendors" : "needs goods-receipt date"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-5">
        <AlertPanel alerts={alerts} />

        <div className="flex flex-col gap-5">
          <Card title="Risk profile" subtitle="Every open position, banded by likelihood and consequence">
            <div className="flex flex-col gap-3">
              {kpis.bands.map((band) => {
                const share = kpis.positions_open ? band.positions / kpis.positions_open : 0;
                return (
                  <div key={band.band} className="flex items-center gap-3">
                    <div className="w-[86px] shrink-0">
                      <BandBadge band={band.band} small />
                    </div>
                    <div className="flex-1 h-2.5 rounded-full" style={{ background: "var(--surface-3)" }}>
                      <div className="h-2.5 rounded-full"
                           style={{ width: `${Math.max(share * 100, 1)}%`,
                                    background: bandColor[band.band] }} />
                    </div>
                    <span className="w-[52px] text-right text-[13px] tnum">{num(band.positions)}</span>
                    <span className="w-[64px] text-right text-[12px] tnum"
                          style={{ color: "var(--text-secondary)" }}>
                      {money(band.lost_revenue)}
                    </span>
                  </div>
                );
              })}
            </div>
            <Note>
              A band combines likelihood with consequence. Ranking on probability alone
              sends planners at the SKUs most likely to run out rather than the ones
              whose running out matters — measured on this data, the top-15 lists by
              risk and by revenue share 0 SKUs.
            </Note>
          </Card>

          <Card title="Inventory and demand" subtitle="Network totals, last 120 days">
            <TrendChart data={trend} height={200} />
            <div className="flex items-center gap-4 mt-2 text-[11px]"
                 style={{ color: "var(--text-muted)" }}>
              <Legend color="var(--series-1)" label="Units on hand" />
              <Legend color="var(--series-2)" label="Units sold" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

function AlertPanel({ alerts }: { alerts: Alert[] }) {
  const navigate = useNavigate();
  const { focus, setFilters } = useStore();

  const open = (alert: Alert) => {
    const { page, params } = alert.link;
    if (page === "risk-detail" && params.store_id && params.sku_uid) {
      focus({ storeId: String(params.store_id), skuUid: String(params.sku_uid) }, "risk");
      return;
    }
    if (page === "risk") {
      setFilters({
        band: params.band ? String(params.band) : undefined,
        minProbability: params.min_probability ? Number(params.min_probability) : undefined,
        coverage: params.coverage ? String(params.coverage) : undefined,
      });
      navigate("/risk");
      return;
    }
    navigate(page === "prescribe" ? "/prescribe" : page === "network" ? "/network" : "/inventory");
  };

  return (
    <Card title="Risk feed" subtitle="Generated from the scored population — every item drills through">
      {!alerts.length && <Empty>Nothing needs attention.</Empty>}
      <div className="flex flex-col">
        {alerts.map((alert, index) => (
          <button
            key={index}
            onClick={() => open(alert)}
            className="text-left flex gap-3 py-3 group transition-colors"
            style={{ borderTop: index ? "1px solid var(--border)" : undefined }}
          >
            <span className="mt-1.5 w-2 h-2 rounded-full shrink-0"
                  style={{ background: severityColor[alert.severity] }} aria-hidden />
            <span className="flex-1 min-w-0">
              <span className="flex items-center gap-2">
                <span className="text-[13px] font-medium">{alert.title}</span>
                <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
                      style={{ color: severityColor[alert.severity],
                               background: `color-mix(in srgb, ${severityColor[alert.severity]} 14%, transparent)` }}>
                  {alert.severity}
                </span>
              </span>
              <span className="block text-[12px] mt-0.5 leading-relaxed"
                    style={{ color: "var(--text-secondary)" }}>
                {alert.detail}
              </span>
            </span>
            <span className="self-center text-[12px] opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: "var(--series-1)" }}>
              open →
            </span>
          </button>
        ))}
      </div>
    </Card>
  );
}
