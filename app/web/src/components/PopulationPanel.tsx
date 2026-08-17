import { useState } from "react";
import { api } from "../lib/api";
import { days, num, pct } from "../lib/format";
import { Card, Empty, ErrorState, InfoHint, Kpi, Note, Spinner, Table, TermLabel } from "./ui";
import { StockoutHistogram } from "./charts";
import { useApi } from "../lib/useApi";
import { useStore } from "../store";

/**
 * The single-position simulator answers "when does THIS run out". This answers
 * "how much of the book is exposed, and when" — the question a planner usually
 * opens the page with, and which previously needed a terminal.
 *
 * The budget guard is server-side and returns which knob to reduce, so its
 * message is rendered rather than replaced with a generic failure. It is also
 * mirrored here — see PATH_DAY_BUDGET.
 */

/**
 * `PATH_DAY_BUDGET` in `app/api/routers/simulate.py`.
 *
 * Four of this panel's 36 selectable combinations exceeded it and could only
 * ever 422 — 500 positions × 56 days × 2,000 paths asks for 56M path-days
 * against a 20M ceiling. A control that offers a setting which cannot succeed
 * is a broken control, however good the resulting error message is. So the
 * options are disabled here and the server guard stays as the backstop.
 */
const PATH_DAY_BUDGET = 20_000_000;
const affordable = (positions: number, horizon: number, paths: number) =>
  positions * horizon * paths <= PATH_DAY_BUDGET;

export function PopulationPanel() {
  const { filters } = useStore();
  const [limit, setLimit] = useState(200);
  const [horizon, setHorizon] = useState(28);
  const [paths, setPaths] = useState(500);

  const population = useApi(
    () => api.simulatePopulation({
      band: filters.band, store_id: filters.storeId, category: filters.category,
      min_probability: filters.minProbability, coverage: filters.coverage,
      // The caption below promises the risk table's filters apply. `search` is
      // one of them and the endpoint accepts it, so dropping it made the promise
      // false the moment anyone typed in the search box.
      search: filters.search,
      limit, horizon, n_paths: paths,
    }),
    [filters.band, filters.storeId, filters.category, filters.minProbability,
     filters.coverage, filters.search, limit, horizon, paths],
  );

  const pathDays = limit * horizon * paths;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <Select label="Products" value={String(limit)} onChange={(v) => setLimit(Number(v))}
                options={[50, 200, 500].map((n) => [String(n), String(n), affordable(n, horizon, paths)])} />
        <Select label="Look ahead" value={String(horizon)} onChange={(v) => setHorizon(Number(v))}
                options={[14, 28, 56].map((n) => [String(n), `${n} days`, affordable(limit, n, paths)])} />
        <Select label="Runs each" value={String(paths)} onChange={(v) => setPaths(Number(v))}
                options={[200, 500, 1000, 2000].map(
                  (n) => [String(n), n.toLocaleString(), affordable(limit, horizon, n)])} />
        <span className="text-[11px] inline-flex items-center gap-1.5"
              style={{ color: "var(--text-muted)" }}>
          Worst first, by money at stake. Filters from the risk table apply here.
          <InfoHint
            text={`Bigger settings take longer. This run is using ${(pathDays / 1e6).toFixed(1)}M of the ${PATH_DAY_BUDGET / 1e6}M we allow in one go — options past the limit are greyed out rather than left to fail.`}
            technical={`${limit} positions × ${horizon} days × ${paths} paths (path-day budget)`} />
        </span>
      </div>

      {/* The 422 names the knob to reduce; showing "422" instead would strand
          the user on a control they cannot reason about. */}
      {population.error && (
        <ErrorState message={population.error} onRetry={population.refetch} />
      )}
      {!population.error && !population.data && <Spinner label="Playing every product forward…" />}

      {population.data && !population.error && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Average chance of running out"
                 value={pct(population.data.aggregate.p_stockout_mean, 1)}
                 sub={`in the next ${population.data.horizon} days`}
                 hint="Averaged across every product in this slice. A single product's own chance can be far higher or lower." />
            <Kpi label="More likely than not to run out"
                 value={num(population.data.aggregate.positions_likely_out)}
                 tone="var(--status-serious)"
                 sub={`of ${num(population.data.positions)} played forward`} />
            <Kpi name="expected_unmet_units" label="Sales we'd miss"
                 value={num(population.data.aggregate.expected_unmet_units)}
                 sub="units across this slice" />
            <Kpi label="Days with empty shelves"
                 value={days(population.data.aggregate.expected_days_out_mean)}
                 sub="per product, on average"
                 hint="How many days of the window a typical product in this slice spends unavailable to buy." />
          </div>

          <Card title="How the exposure builds up"
                subtitle="Share of this slice expected to have run out by each point">
            {population.data.aggregate.by_horizon.length ? (
              <StockoutHistogram
                data={population.data.aggregate.by_horizon.map((h) => ({
                  day: h.day, share: h.share,
                }))}
                height={180} />
            ) : <Empty>Nothing runs out inside this window.</Empty>}
            <Note>{population.data.note}</Note>
          </Card>

          <Card title="Product by product"
                subtitle={`${num(population.data.positions)} products · ${num(population.data.paths)} runs each`}>
            <Table head={[
              "Product", "Store",
              <TermLabel key="stock" name="stock_on_hand" />,
              <TermLabel key="transit" name="committed_units" label="On its way" />,
              <TermLabel key="rate" name="trailing_demand_rate" label="Sells a day" />,
              <TermLabel key="p" name="p_stockout" label="Runs out" />,
              <TermLabel key="p10" name="days_to_stockout_p10" label="Earliest" />,
              <TermLabel key="p50" name="days_to_stockout_p50" label="Typical" />,
              <TermLabel key="p90" name="days_to_stockout_p90" label="Latest" />,
              <TermLabel key="unmet" name="expected_unmet_units" label="Missed" />,
            ]}>
              {population.data.rows.map((row) => (
                <tr key={`${row.store_id}-${row.sku_uid}`}
                    style={{ borderBottom: "1px solid var(--border)" }}>
                  <td className="py-2 pr-4 font-medium">{row.sku_uid}</td>
                  <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                    {row.store_id}
                  </td>
                  <td className="py-2 pr-4">{num(row.stock_on_hand)}</td>
                  <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                    {num(row.committed_units)}
                  </td>
                  <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                    {num(row.trailing_demand_rate, 2)}
                  </td>
                  <td className="py-2 pr-4"
                      style={{ color: row.mc_p_stockout > 0.5
                        ? "var(--status-critical)" : "var(--text-primary)" }}>
                    {pct(row.mc_p_stockout)}
                  </td>
                  {/* A percentile deeper than the observed failure share is not
                      identified, and the API returns null rather than pinning it
                      to the horizon. */}
                  <td className="py-2 pr-4">{days(row.mc_days_to_stockout_p10)}</td>
                  <td className="py-2 pr-4">{days(row.mc_days_to_stockout_p50)}</td>
                  <td className="py-2 pr-4">{days(row.mc_days_to_stockout_p90)}</td>
                  <td className="py-2 pr-4">{num(row.expected_unmet_units, 1)}</td>
                </tr>
              ))}
            </Table>
            <Note>
              A dash under Earliest, Typical or Latest means too few runs sold
              out to put a date on it. Quoting one would be inventing it.
            </Note>
          </Card>
        </>
      )}
    </div>
  );
}

/** Options are `[value, label, enabled]`; a disabled one is over the path-day budget. */
function Select({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string, boolean][];
}) {
  return (
    <label className="flex items-center gap-2 text-[12px]" style={{ color: "var(--text-secondary)" }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="rounded-md px-2.5 py-1.5 text-[13px] outline-none cursor-pointer"
              style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                       color: "var(--text-primary)" }}>
        {options.map(([v, text, enabled]) => (
          <option key={v} value={v} disabled={!enabled}>
            {enabled ? text : `${text} — over budget`}
          </option>
        ))}
      </select>
    </label>
  );
}
