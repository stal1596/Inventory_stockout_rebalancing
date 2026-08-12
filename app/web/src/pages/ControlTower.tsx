import { useNavigate } from "react-router-dom";
import { api, type Alert } from "../lib/api";
import { bandColor, money, num, pct, severityColor } from "../lib/format";
import { BandBadge, Card, Empty, Kpi, Loadable, Note } from "../components/ui";
import { TrendChart } from "../components/charts";
import { useApi } from "../lib/useApi";
import { useStore } from "../store";

export function ControlTower() {
  // Three independent calls, not one Promise.all. Bundled, a dead trend endpoint
  // erased the KPIs and the alert feed with it -- the two things a control tower
  // exists to show.
  const kpis = useApi(() => api.kpis(), []);
  const alerts = useApi(() => api.alerts(), []);
  const trend = useApi(() => api.trend(120), []);

  return (
    <div className="flex flex-col gap-5">
      <Loadable state={kpis} label="Loading the network position…">
        {(data) => {
          const h7 = data.horizons["7"];
          const h14 = data.horizons["14"];
          const h28 = data.horizons["28"];
          return (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                <Kpi label="Positions at risk" value={num(data.skus_at_risk)}
                     tone={bandColor.High}
                     sub={`of ${num(data.positions_open)} open store × SKU`}
                     hint="Critical or High band: likely to run out AND expensive when it does." />
                <Kpi label="Value at risk" value={money(data.inventory_value_at_risk)}
                     sub="expected lost revenue, 14 days"
                     hint="Expected days out of stock × demand rate × price." />
                <Kpi label="Stock out ≤ 7 days" value={num(h7.positions)}
                     tone={bandColor.Critical} sub={money(h7.revenue) + " exposed"} />
                <Kpi label="Stock out ≤ 14 days" value={num(h14.positions)}
                     sub={money(h14.revenue) + " exposed"} />
                <Kpi label="Stock out ≤ 28 days" value={num(h28.positions)}
                     sub={money(h28.revenue) + " exposed"} />

                <Kpi label="On hand" value={num(data.inventory_on_hand_units)}
                     sub={`${num(data.inventory_at_dc_units)} at DC · ${num(data.inventory_inbound_units)} inbound`} />
                <Kpi label="Median days of supply" value={data.median_days_of_supply ?? "—"}
                     sub={`turnover ${data.inventory_turnover}× annualised`} />
                {/* The value was fetched and never shown; units alone do not say
                    how much capital the excess ties up. */}
                <Kpi label="Excess inventory" value={num(data.excess_inventory_units)}
                     sub={`${money(data.excess_inventory_value)} · beyond 60 days of cover`} />
                <Kpi label="Open replenishment" value={num(data.open_replenishment_orders)}
                     sub="order lines in the window" />
                <Kpi label="Supplier on-time"
                     value={data.supplier_available ? pct(data.supplier_on_time_rate) : "n/a"}
                     tone={data.supplier_on_time_rate && data.supplier_on_time_rate < 0.8
                       ? bandColor.High : undefined}
                     sub={data.supplier_available ? "across all vendors" : "needs goods-receipt date"} />
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-5 mt-5">
                <Card title="Risk feed"
                      subtitle="Generated from the scored population — every item drills through">
                  <Loadable state={alerts} label="Reading the feed…">
                    {(feed) => <AlertList alerts={feed.alerts} />}
                  </Loadable>
                </Card>

                <div className="flex flex-col gap-5">
                  <Card title="Risk profile"
                        subtitle="Every open position, banded by likelihood and consequence">
                    <div className="flex flex-col gap-3">
                      {data.bands.map((band) => {
                        const share = data.positions_open
                          ? band.positions / data.positions_open : 0;
                        return (
                          <div key={band.band} className="flex items-center gap-3">
                            <div className="w-[86px] shrink-0">
                              <BandBadge band={band.band} small />
                            </div>
                            <div className="flex-1 h-2.5 rounded-full"
                                 style={{ background: "var(--surface-3)" }}>
                              <div className="h-2.5 rounded-full"
                                   style={{ width: `${Math.max(share * 100, 1)}%`,
                                            background: bandColor[band.band] }} />
                            </div>
                            <span className="w-[52px] text-right text-[13px] tnum">
                              {num(band.positions)}
                            </span>
                            <span className="w-[76px] text-right text-[12px] tnum"
                                  style={{ color: "var(--text-secondary)" }}>
                              {num(band.lost_units, 1)}u
                            </span>
                            <span className="w-[64px] text-right text-[12px] tnum"
                                  style={{ color: "var(--text-secondary)" }}>
                              {money(band.lost_revenue)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    <Note>
                      A band combines likelihood with consequence. Ranking on
                      probability alone sends planners at the SKUs most likely to
                      run out rather than the ones whose running out matters —
                      the two orderings pick largely different SKUs, which is the
                      reason to band rather than sort.
                    </Note>
                  </Card>

                  <Card title="Inventory and demand" subtitle="Network totals, last 120 days">
                    <Loadable state={trend} label="Aggregating the panel…">
                      {(series) => (
                        <>
                          <TrendChart data={series.series} height={200} />
                          <div className="flex items-center gap-4 mt-2 text-[11px]"
                               style={{ color: "var(--text-muted)" }}>
                            <Legend color="var(--series-1)" label="Units on hand" />
                            <Legend color="var(--series-2)" label="Units sold" />
                          </div>
                        </>
                      )}
                    </Loadable>
                  </Card>
                </div>
              </div>
            </>
          );
        }}
      </Loadable>
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

function AlertList({ alerts }: { alerts: Alert[] }) {
  const navigate = useNavigate();
  const { focus } = useStore();

  /**
   * Carry the whole link, not the half of it we happened to read.
   *
   * Four of the six alert kinds used to lose their params entirely, and the risk
   * alerts silently dropped `horizon` -- so "12 SKUs within 7 days" opened a
   * table filtered at 14 days and the two counts disagreed by construction.
   */
  const open = (alert: Alert) => {
    const { page, params } = alert.link;

    if (page === "risk-detail" && params.store_id && params.sku_uid) {
      focus({ storeId: String(params.store_id), skuUid: String(params.sku_uid) }, "risk");
      return;
    }
    if (page === "risk") {
      // The filters must ride ON the navigation. Writing them to the current
      // URL and then navigating drops them, because the new location carries
      // its own (empty) search string -- which is how this drill-through
      // silently arrived unfiltered.
      const search = new URLSearchParams();
      const carry = (key: string, param: string) => {
        const value = params[param];
        if (value !== undefined && value !== "") search.set(key, String(value));
      };
      carry("band", "band");
      carry("p", "min_probability");
      carry("cover", "coverage");
      carry("h", "horizon");
      navigate({ pathname: "/risk", search: `?${search}` });
      return;
    }
    if (page === "prescribe") {
      navigate(`/prescribe${params.action ? `?action=${params.action}` : ""}`);
      return;
    }
    if (page === "network") {
      navigate(`/network${params.vendor ? `?vendor=${encodeURIComponent(String(params.vendor))}` : ""}`);
      return;
    }
    if (page === "inventory") {
      navigate(`/inventory${params.view ? `#${params.view}` : ""}`);
      return;
    }
    // An unrecognised page is a backend addition this build does not know about.
    // Landing silently on Inventory made that look like a working link.
    navigate("/");
  };

  if (!alerts.length) return <Empty>Nothing needs attention.</Empty>;

  return (
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
          {/* focus-within, so a keyboard user gets the same affordance a mouse
              user gets on hover. */}
          <span className="self-center text-[12px] opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"
                style={{ color: "var(--series-1)" }}>
            open →
          </span>
        </button>
      ))}
    </div>
  );
}
