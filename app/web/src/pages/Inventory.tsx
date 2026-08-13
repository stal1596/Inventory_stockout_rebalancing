import { api } from "../lib/api";
import { days, money, num, pct } from "../lib/format";
import { Card, Empty, ErrorState, Kpi, Note, Spinner, Table } from "../components/ui";
import { useApi } from "../lib/useApi";
import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { DistributionChart, ForecastChart, SupplyChart, TrendChart } from "../components/charts";

export function Inventory() {
  const state = useApi(() => api.inventory(), []);
  const trendState = useApi(() => api.trend(180), []);
  const trend = trendState.data?.series ?? [];

  // A failed trend fetch used to fall through to `?? []` and render two empty
  // charts with nothing saying why — the same blank panel a genuinely flat
  // network would produce. Two cards depend on it, so the failure is stated once
  // and reused in both.
  const trendFailure = trendState.error ? (
    <ErrorState message={trendState.error} onRetry={trendState.refetch} />
  ) : null;

  // The alert feed deep-links here as `/inventory#lead-time`. React Router does
  // not scroll to a fragment, and the target card does not exist until the
  // summary resolves — so this waits for the data rather than firing on mount,
  // which is why the link previously did nothing at all.
  const { hash } = useLocation();
  const loaded = Boolean(state.data);
  useEffect(() => {
    if (!hash || !loaded) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
  }, [hash, loaded]);

  if (state.error) return <ErrorState message={state.error} onRetry={state.refetch} />;
  if (!state.data) return <Spinner label="Aggregating the panel…" />;

  const summary = state.data;
  const supplier = summary.supplier;
  const lead = summary.lead_time;
  const forecast = summary.forecast;

  // Cover buckets are ordered, so they take a sequential ramp rather than
  // categorical hues — magnitude, not identity.
  const coverColors = ["var(--status-critical)", "var(--status-serious)",
                       "var(--status-warning)", "var(--series-3)", "var(--seq-250)"];

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Kpi label="On hand" value={num(summary.on_hand_units)} sub="units in stores" />
        <Kpi label="At DC" value={num(summary.dc_units)} sub="units upstream" />
        <Kpi label="In transit" value={num(summary.intransit_units)} sub="units inbound" />
        <Kpi label="Excess" value={num(summary.excess_units)} sub="beyond 60 days of cover" />
        <Kpi label="Turnover" value={`${summary.turnover}×`}
             sub={`median cover ${summary.median_days_of_supply ?? "—"}d`} />
      </div>

      <Card id="demand" title="Inventory and demand" subtitle="Network totals, last 180 days">
        {trendFailure ?? <>
          <TrendChart data={trend} height={230} />
          <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
              Units on hand
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
              Units sold
            </span>
          </div>
        </>}
      </Card>

      <Card id="supply" title="Supply into the network"
            subtitle="Goods received, and the DC depth behind them">
        {trendFailure ?? <>
          <SupplyChart data={trend} height={200} />
          <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
              Units received
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
              DC stock
            </span>
          </div>
        </>}
        <Note>
          Both series arrive with the demand panel and were previously fetched
          and discarded. Receipts are INFERRED from consecutive-day stock rises,
          not read from order dates — the extract records when an order was
          placed, never when it landed.
        </Note>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Days of supply" subtitle="How many positions sit in each cover band">
          <DistributionChart data={summary.cover_distribution} xKey="bucket" yKey="positions"
                             colors={coverColors} height={200} />
          <Note>
            Cover is stock divided by the trailing demand rate. Positions under 7
            days are the ones a replenishment cycle may not reach in time.
          </Note>
        </Card>

        <Card title="Forecast versus actual"
              subtitle={forecast?.available
                ? `Bias ${forecast.bias?.toFixed(2)}× · median absolute error ${pct(forecast.mape, 0)}`
                : "Not available"}>
          {forecast?.available
            ? <ForecastChart data={forecast.weeks} height={200} />
            : <Empty>No store-week forecast in this extract.</Empty>}
          <Note>
            The source forecast is monthly and national. This is that plan
            allocated to store × week by each store's historical demand share, so
            it inherits the national forecast's error rather than inventing a
            better one.
          </Note>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Supplier performance"
              subtitle={supplier.available
                ? "Promised against actual, from goods receipts"
                : "Cannot be measured"}>
          {!supplier.available ? (
            <div className="rounded-md p-4 text-[13px] leading-relaxed"
                 style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
              {supplier.reason}
            </div>
          ) : (
            <Table head={["Vendor", "On time", "Promised", "Actual", "σ", "Receipts"]}>
              {supplier.vendors.map((vendor: any) => (
                <tr key={vendor.vendor} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td className="py-2 pr-4">{vendor.vendor}</td>
                  <td className="py-2 pr-4"
                      style={{ color: vendor.on_time_rate < 0.8
                        ? "var(--status-critical)" : "var(--text-primary)" }}>
                    {pct(vendor.on_time_rate)}
                  </td>
                  <td className="py-2 pr-4">{days(vendor.lead_days_promised, 0)}</td>
                  <td className="py-2 pr-4">{days(vendor.lead_days_actual, 0)}</td>
                  <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                    ±{vendor.lead_days_std}
                  </td>
                  <td className="py-2 pr-4">{num(vendor.receipts)}</td>
                </tr>
              ))}
            </Table>
          )}
          <Note>
            The supplied extract has no goods-receipt date, so this is not
            computable there at all. The synthetic feed emits one, which is what
            makes on-time performance measurable here.
          </Note>
        </Card>

        <Card id="lead-time" title="Lead time, DC to store"
              subtitle="Observed against inferred — two routes to the same number">
          {lead.histogram?.length
            ? <DistributionChart data={lead.histogram} xKey="days" yKey="receipts" height={180} />
            : <Empty>No receipts to chart.</Empty>}
          <div className="grid grid-cols-2 gap-3 mt-3">
            <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Observed
              </p>
              <p className="text-[15px] font-semibold tnum">
                {lead.observed ? `${lead.observed.mean}d ± ${lead.observed.std}` : "—"}
              </p>
            </div>
            <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Inferred
              </p>
              <p className="text-[15px] font-semibold tnum">
                {lead.inferred.mean ? `${lead.inferred.mean}d ± ${lead.inferred.std}` : "—"}
              </p>
            </div>
          </div>
          <Note>{lead.note}</Note>
        </Card>
      </div>

      <Card title="Inventory by store" subtitle="Where the stock and the excess sit">
        <Table head={["Store", "SKUs", "On hand", "Excess units", "Excess share", ""]}>
          {summary.by_store.map((store) => (
            <tr key={store.store_id} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-2 pr-4 font-medium">{store.store_id}</td>
              <td className="py-2 pr-4">{num(store.skus)}</td>
              <td className="py-2 pr-4">{num(store.on_hand)}</td>
              <td className="py-2 pr-4">{num(store.excess, 1)}</td>
              <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                {pct(store.on_hand ? store.excess / store.on_hand : 0)}
              </td>
              {/* The row already knows the store; without this it was a dead end. */}
              <td className="py-2 pr-4">
                <Link to={`/risk?at=${encodeURIComponent(store.store_id)}`}
                      className="text-[12px] underline underline-offset-2"
                      style={{ color: "var(--series-1)" }}>
                  risk →
                </Link>
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
