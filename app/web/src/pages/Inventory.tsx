import { api } from "../lib/api";
import { days, money, num, pct } from "../lib/format";
import {
  Card, Empty, ErrorState, InfoHint, Kpi, Note, Spinner, Table, TermLabel,
} from "../components/ui";
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
  if (!state.data) return <Spinner label="Adding up what you're holding…" />;

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
        <Kpi label="In stores" value={num(summary.on_hand_units)} sub="units on shop floors" />
        <Kpi label="At the warehouse" value={num(summary.dc_units)} sub="units held back"
             hint="Stock at the distribution centres. This is the cover behind the stores — the first place to look when one shop runs short." />
        <Kpi label="On the way" value={num(summary.intransit_units)} sub="units already shipped"
             hint="Units dispatched and expected to land. Stock ordered but not yet dispatched is not counted." />
        <Kpi label="Overstocked" value={num(summary.excess_units)} sub="beyond 60 days of selling"
             hint="Units that will not sell for two months at the current rate. Often the best source for a transfer to a store that is running short." />
        <Kpi name="inventory_turnover" label="Stock turnover" value={`${summary.turnover}×`}
             sub={`typical product has ${summary.median_days_of_supply ?? "—"} days left`} />
      </div>

      <Card id="demand" title="Stock and sales"
            subtitle="Across every store, over the last 180 days">
        {trendFailure ?? <>
          <TrendChart data={trend} height={230} />
          <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
              Units in stores
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
              Units sold
            </span>
          </div>
        </>}
      </Card>

      <Card id="supply" title="Stock coming in"
            subtitle="What arrived in stores, and how much cover sat behind it at the warehouse">
        {trendFailure ?? <>
          <SupplyChart data={trend} height={200} />
          <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
              Units delivered to stores
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
              Units at the warehouse
            </span>
          </div>
        </>}
        <Note>
          Deliveries are worked out by spotting the days a store's stock jumped
          up, because the records say when an order was placed but never when it
          landed.
        </Note>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="How long stock will last"
              subtitle="How many products fall into each band of days remaining">
          <DistributionChart data={summary.cover_distribution} xKey="bucket" yKey="positions"
                             colors={coverColors} height={200} />
          <Note>
            Days left is simply the stock on the shelf divided by how fast it has
            been selling. Anything under 7 days is unlikely to be reached by a
            normal delivery cycle in time.
          </Note>
        </Card>

        <Card title="Forecast versus what actually sold"
              subtitle={forecast?.available
                ? <span className="inline-flex flex-wrap items-center gap-x-1">
                    The forecast runs {forecast.bias ? `${forecast.bias.toFixed(2)}×` : "—"} actual sales
                    and is typically {pct(forecast.mape, 0)} out
                    <InfoHint
                      text="Below 1.00× the forecast under-calls demand; above it, over-calls. The second figure is how far off it usually lands, either way."
                      technical={`bias ${forecast.bias?.toFixed(2)}× · MAPE ${pct(forecast.mape, 0)}`} />
                  </span>
                : "Not available"}>
          {forecast?.available
            ? <ForecastChart data={forecast.weeks} height={200} />
            : <Empty>No store-week forecast in this extract.</Empty>}
          <Note>
            The original forecast is monthly and covers the whole country. What
            you see here is that same plan split down to each store and week
            using its usual share of sales — so it carries the national
            forecast's error rather than pretending to a better one.
          </Note>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Are suppliers keeping their promises?"
              subtitle={supplier.available
                ? "What each supplier promised against what they actually delivered"
                : "Cannot be measured from this data"}>
          {!supplier.available ? (
            <div className="rounded-md p-4 text-[13px] leading-relaxed"
                 style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
              {supplier.reason}
            </div>
          ) : (
            <Table head={[
              "Supplier", "On time", "Promised", "Actually took",
              <TermLabel key="swing" name="lead_sigma" label="Swing" />,
              "Deliveries",
            ]}>
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
            This needs a recorded delivery date for every shipment. Where that
            is missing from the source data, supplier performance cannot be
            measured at all and this panel says so rather than guessing.
          </Note>
        </Card>

        <Card id="lead-time" title="How long deliveries take, warehouse to store"
              subtitle="Two independent ways of measuring it, as a cross-check">
          {lead.histogram?.length
            ? <DistributionChart data={lead.histogram} xKey="days" yKey="receipts" height={180} />
            : <Empty>No receipts to chart.</Empty>}
          <div className="grid grid-cols-2 gap-3 mt-3">
            <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
              <p className="text-[10px] uppercase tracking-wider inline-flex items-center gap-1"
                 style={{ color: "var(--text-muted)" }}>
                From delivery records
                <InfoHint text="Taken straight from recorded goods-receipt dates." />
              </p>
              <p className="text-[15px] font-semibold tnum">
                {lead.observed ? `${lead.observed.mean}d ± ${lead.observed.std}` : "—"}
              </p>
            </div>
            <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
              <p className="text-[10px] uppercase tracking-wider inline-flex items-center gap-1"
                 style={{ color: "var(--text-muted)" }}>
                From stock movements
                <InfoHint text="Worked out by spotting the days stock jumped up in a store. This is the figure the model uses, because a real extract rarely records delivery dates at all — the two agreeing this closely is what makes it trustworthy." />
              </p>
              <p className="text-[15px] font-semibold tnum">
                {lead.inferred.mean ? `${lead.inferred.mean}d ± ${lead.inferred.std}` : "—"}
              </p>
            </div>
          </div>
          <Note>{lead.note}</Note>
        </Card>
      </div>

      <Card title="Stock by store" subtitle="Where the stock sits, and where it is sitting still">
        <Table head={["Store", "Products", "In store", "Overstocked", "Share overstocked", ""]}>
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
