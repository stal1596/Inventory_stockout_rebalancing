import { useState } from "react";
import { api, exportUrl, type Estimator } from "../lib/api";
import { days, money, num, pct } from "../lib/format";
import {
  Card, DownloadCsv, Empty, Kpi, Loadable, Note, Table, TermLabel,
} from "../components/ui";
import { DistributionChart } from "../components/charts";
import { useApi } from "../lib/useApi";

/**
 * Where to set the reorder point — and the one screen that could quietly undo a
 * load-bearing verdict of this project.
 *
 * Inverting the fitted survival model to find the stock level at which risk
 * falls below a threshold is the obvious move and it FAILED: the incumbent rule
 * reorders at 12 days of cover, so almost nothing in the data shows a position
 * allowed to run lower. That is off-policy extrapolation, and backtested it lost
 * 59% more units for 13% less inventory. So the validated lead-time-demand
 * estimator is the default, the failed one is opt-in, and choosing it puts a
 * banner across the page rather than a footnote under it.
 */

// A select, not a slider. Each distinct value mints a ~4-second cache entry on
// the server, and the derived-cache LRU holds 32 -- dragging a slider would
// evict the 10.6s validation run and the 8.3s KM-bias measurement that other
// pages depend on.
const SERVICE_LEVELS = [0.9, 0.95, 0.98, 0.99];

export function Policy() {
  const [serviceLevel, setServiceLevel] = useState(0.95);
  const [estimator, setEstimator] = useState<Estimator>("lead_time_demand");
  const [storeId, setStoreId] = useState("");
  const [belowOnly, setBelowOnly] = useState(false);
  const [offset, setOffset] = useState(0);

  const options = useApi(() => api.filters(), []);
  const policy = useApi(
    () => api.reorderPoints({
      service_level: serviceLevel, estimator,
      store_id: storeId || undefined, below_only: belowOnly || undefined,
      limit: 200, offset,
    }),
    [serviceLevel, estimator, storeId, belowOnly, offset],
  );

  const change = <T,>(setter: (v: T) => void) => (value: T) => { setOffset(0); setter(value); };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={String(serviceLevel)}
                onChange={(v) => change(setServiceLevel)(Number(v))}
                options={SERVICE_LEVELS.map(
                  (s) => [String(s), `${pct(s, s >= 0.99 ? 1 : 0)} service level`] as [string, string])} />
        <Select value={estimator} onChange={(v) => change(setEstimator)(v as Estimator)}
                options={[
                  ["lead_time_demand", "Standard method (recommended)"],
                  ["model_inversion", "Working backwards from the risk model — NOT VALIDATED"],
                ]} />
        <Select value={storeId} onChange={change(setStoreId)}
                options={[["", "All stores"],
                          ...(options.data?.stores ?? []).map(
                            (s) => [s.store_id, `${s.store_id} · ${s.city}`] as [string, string])]} />
        <label className="flex items-center gap-2 text-[13px] rounded-md px-2.5 py-1.5 cursor-pointer"
               style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
          <input type="checkbox" checked={belowOnly}
                 onChange={(e) => change(setBelowOnly)(e.target.checked)} />
          Only products due a reorder
        </label>
        <span className="ml-auto">
          <DownloadCsv href={exportUrl.policy({
            service_level: serviceLevel, estimator,
            store_id: storeId || undefined, below_only: belowOnly || undefined,
          })} />
        </span>
      </div>

      <Loadable state={policy} label="Working out when to reorder…">
        {(data) => (
          <>
            {/* Not a footnote. Choosing the failed estimator has to look like a
                warning before any number on the page is read. */}
            {!data.validated && data.warning && (
              <div className="rounded-lg px-4 py-3 text-[13px] leading-relaxed"
                   style={{ background: "color-mix(in srgb, var(--status-critical) 10%, transparent)",
                            border: "1px solid var(--status-critical)",
                            color: "var(--text-primary)" }}>
                <p className="font-semibold mb-1" style={{ color: "var(--status-critical)" }}>
                  NOT VALIDATED — {data.estimator_label}
                </p>
                {data.warning}
              </div>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Kpi label="Due a reorder now" value={num(data.positions_below_reorder_point)}
                   tone={data.positions_below_reorder_point ? "var(--status-serious)" : undefined}
                   sub={`of ${num(data.total)} products`}
                   hint="Products already at or below the level where an order should go in." />
              <Kpi name="protection_days" value={days(data.protection_days)}
                   sub={data.lead_time.inferred.mean !== null
                     ? `delivery takes ${data.lead_time.inferred.mean}d ± ${data.lead_time.inferred.std}`
                     : "delivery time cannot be worked out"} />
              {/* The raw `estimator_label` read "Lead-time demand (negative
                  binomial)" here while the picker above it now says "Standard
                  method" -- the same choice, named two different ways on one
                  screen. The server's wording moves into the hint. */}
              <Kpi name="service_level" value={pct(data.service_level, 1)}
                   sub={data.validated
                     ? "how often you want to avoid running short"
                     : "NOT VALIDATED — see the warning above"}
                   hint={`Aiming to have stock in hand ${pct(data.service_level, 1)} of the times a delivery is due. Method: ${data.estimator_label}.`}
                   tone={data.validated ? undefined : "var(--status-critical)"} />
              <Kpi name="incumbent_rule" label="Rule in force today"
                   value={`${data.incumbent.cover_days}d of cover`}
                   sub="what the business does now"
                   hint="Reorder when stock falls to this many days of selling. Any recommendation has to beat this rule at the same level of inventory to be worth adopting." />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,360px)] gap-5 items-start">
              <Card title="When to reorder each product"
                    subtitle="The stock level that should trigger the next order">
                {!data.rows.length ? (
                  <Empty>No products match these filters.</Empty>
                ) : (
                  <>
                    <Table head={[
                      "Product", "Store",
                      <TermLabel key="stock" name="stock_on_hand" />,
                      <TermLabel key="cover" name="cover_days_now" label="Days left" />,
                      <TermLabel key="rate" name="trailing_demand_rate" label="Sells a day" />,
                      <TermLabel key="rop" name="recommended_reorder_point" label="Reorder at" />,
                      "That's days of cover",
                      <TermLabel key="safety" name="safety_stock" label="Buffer" />,
                      <TermLabel key="tb" name="textbook_reorder_point" label="Textbook" />,
                      "",
                    ]}>
                      {data.rows.map((row) => (
                        <tr key={`${row.store_id}-${row.sku_uid}`}
                            style={{ borderBottom: "1px solid var(--border)" }}>
                          <td className="py-2 pr-4 font-medium">{row.sku_uid}</td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                            {row.store_id}
                          </td>
                          <td className="py-2 pr-4">{num(row.stock_on_hand)}</td>
                          <td className="py-2 pr-4">{days(row.cover_days_now)}</td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                            {num(row.trailing_demand_rate, 2)}
                          </td>
                          <td className="py-2 pr-4 font-medium">
                            {num(row.recommended_reorder_point)}
                          </td>
                          <td className="py-2 pr-4">{days(row.recommended_cover_days)}</td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                            {num(row.safety_stock, 1)}
                          </td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-muted)" }}>
                            {num(row.textbook_reorder_point)}
                          </td>
                          {/* A word, never colour alone. */}
                          <td className="py-2 pr-4 text-[12px]"
                              style={{ color: row.below_reorder_point
                                ? "var(--status-critical)" : "var(--text-muted)" }}>
                            {row.below_reorder_point ? "order now" : "fine"}
                          </td>
                        </tr>
                      ))}
                    </Table>
                    <Pager total={data.total} offset={offset} shown={data.rows.length}
                           onOffset={setOffset} />
                  </>
                )}
                <Note>{data.caveat}</Note>
              </Card>

              <div className="flex flex-col gap-5 xl:sticky xl:top-[96px] min-w-0">
                <Card title="The bottom line">
                  <p className="text-[13px] leading-relaxed">{data.verdict}</p>
                </Card>

                <Card title="How this is worked out">
                  {/* A plain lead ABOVE the server's own wording, not instead of
                      it. The precise version is the one an analyst will want to
                      check, so it stays on the page in full. */}
                  <p className="text-[13px] leading-relaxed mb-3">
                    Add up how much you expect to sell while waiting for the
                    delivery, then add a buffer for the weeks that run hot. The
                    buffer is sized from how bursty demand actually is here, not
                    from an assumption that it arrives evenly.
                  </p>
                  <p className="text-[12px] leading-relaxed mb-3"
                     style={{ color: "var(--text-muted)" }}>
                    {data.basis}
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <Fact name="dispersion_k"
                          value={data.dispersion_k === null ? "—" : num(data.dispersion_k, 3)} />
                    <Fact name="protection_days" label="Protection"
                          value={days(data.protection_days)} />
                  </div>
                  <Note>
                    Real demand arrives in bursts, and the standard formula
                    assumes it does not. Keeping the burstiness in matters most
                    on slow-moving sizes — which is exactly where a size run
                    breaks first.
                  </Note>
                </Card>

                <Card title="How long deliveries take"
                      subtitle="Worked out from stock movements, since no delivery dates are recorded">
                  {data.lead_time.histogram?.length ? (
                    <DistributionChart data={data.lead_time.histogram}
                                       xKey="days" yKey="receipts" height={150} />
                  ) : <Empty>No receipts to chart.</Empty>}
                  <div className="grid grid-cols-2 gap-2 mt-3">
                    <Fact name="lead_time" label="From records"
                          value={data.lead_time.observed
                            ? `${data.lead_time.observed.mean}d ± ${data.lead_time.observed.std}`
                            : "—"} />
                    <Fact name="lead_time" label="From stock moves"
                          value={data.lead_time.inferred.mean !== null
                            ? `${data.lead_time.inferred.mean}d ± ${data.lead_time.inferred.std}`
                            : "—"} />
                  </div>
                  <Note>{data.lead_time.note}</Note>
                </Card>
              </div>
            </div>
          </>
        )}
      </Loadable>
    </div>
  );
}

function Pager({ total, offset, shown, onOffset }: {
  total: number; offset: number; shown: number; onOffset: (next: number) => void;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = offset + shown;
  return (
    <div className="flex items-center justify-between mt-3 text-[12px]"
         style={{ color: "var(--text-muted)" }}>
      <span className="tnum">Showing {num(first)}–{num(last)} of {num(total)}</span>
      <span className="flex gap-2">
        <button disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - shown))}
                className="rounded-md px-2 py-1 disabled:opacity-40"
                style={{ border: "1px solid var(--border)" }}>
          Previous
        </button>
        <button disabled={last >= total} onClick={() => onOffset(offset + shown)}
                className="rounded-md px-2 py-1 disabled:opacity-40"
                style={{ border: "1px solid var(--border)" }}>
          Next
        </button>
      </span>
    </div>
  );
}

function Fact({ name, label, value }: { name: string; label?: string; value: string }) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        <TermLabel name={name} label={label} />
      </p>
      <p className="text-[14px] font-medium tnum mt-0.5">{value}</p>
    </div>
  );
}

function Select({ value, onChange, options }: {
  value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
            className="rounded-md px-2.5 py-1.5 text-[13px] outline-none cursor-pointer"
            style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                     color: "var(--text-primary)" }}>
      {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
}
