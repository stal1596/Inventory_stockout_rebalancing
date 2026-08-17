import { useState } from "react";
import { api, type Position, type PositionDetail } from "../lib/api";
import { exportUrl } from "../lib/api";
import { bandColor, days, featureLabel, money, num, pct } from "../lib/format";
import {
  BandBadge, Card, Empty, ErrorState, InfoHint, Loadable, Note, Spinner, Table, TermLabel,
} from "../components/ui";
import { DepletionChart, DriverWaterfall } from "../components/charts";
import { term } from "../lib/glossary";
import { useApi, useDebounced } from "../lib/useApi";
import { DEFAULT_HORIZON, useStore } from "../store";

const PAGE_SIZE = 150;
const HORIZONS = [7, 14, 28];

export function Risk() {
  const { selection, focus, filters, setFilters, clearFilters } = useStore();
  const [offset, setOffset] = useState(0);

  const horizon = filters.horizon ?? DEFAULT_HORIZON;
  // The search box types faster than the API answers.
  const search = useDebounced(filters.search, 250);

  const options = useApi(() => api.filters(), []);
  const positions = useApi(
    () =>
      api.positions({
        band: filters.band, store_id: filters.storeId, category: filters.category,
        horizon, min_probability: filters.minProbability, coverage: filters.coverage,
        search, limit: PAGE_SIZE, offset,
      }),
    [filters.band, filters.storeId, filters.category, horizon,
     filters.minProbability, filters.coverage, search, offset],
  );
  const detail = useApi<PositionDetail | null>(
    () => (selection ? api.position(selection.storeId, selection.skuUid) : Promise.resolve(null)),
    [selection?.storeId, selection?.skuUid],
  );
  const drivers = useApi(() => api.driverSummary(), []);

  const set = (patch: Parameters<typeof setFilters>[0]) => { setOffset(0); setFilters(patch); };
  const probabilityColumn = `p_stockout_${horizon}d` as keyof Position;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={filters.band ?? ""} onChange={(v) => set({ band: v || undefined })}
                options={[["", "All priorities"],
                          ...(options.data?.bands ?? []).map((b) => [b, b] as [string, string])]} />
        <Select value={filters.storeId ?? ""} onChange={(v) => set({ storeId: v || undefined })}
                options={[["", "All stores"],
                          ...(options.data?.stores ?? []).map((s) => [s.store_id, `${s.store_id} · ${s.city}`] as [string, string])]} />
        <Select value={filters.category ?? ""} onChange={(v) => set({ category: v || undefined })}
                options={[["", "All categories"],
                          ...(options.data?.categories ?? []).map((c) => [c, c] as [string, string])]} />
        {/* The horizon the risk column and the probability filter both read.
            Without it the 7-day and 28-day alerts opened a 14-day table. */}
        <Select value={String(horizon)} onChange={(v) => set({ horizon: Number(v) })}
                options={(options.data?.horizons ?? HORIZONS).map(
                  (h) => [String(h), `Looking ${h} days ahead`] as [string, string])} />
        <input
          value={filters.search ?? ""}
          onChange={(e) => set({ search: e.target.value || undefined })}
          placeholder="Search a product or store…"
          aria-label="Search a product or store"
          className="rounded-md px-3 py-1.5 text-[13px] w-[200px] outline-none"
          style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                   color: "var(--text-primary)" }}
        />
        <span className="ml-auto text-[12px] tnum" style={{ color: "var(--text-secondary)" }}>
          {positions.data
            ? `${num(positions.data.total)} products · ${money(positions.data.exposure)} of sales at stake`
            : ""}
        </span>
        {/* The DEBOUNCED search, the same value the table was built from. Reading
            `filters.search` here meant the href led the table by up to 250ms, so
            a click landed mid-keystroke exported a different set of rows than the
            one on screen. */}
        <a href={exportUrl.risk({
             band: filters.band, store_id: filters.storeId, category: filters.category,
             horizon, min_probability: filters.minProbability, coverage: filters.coverage,
             search,
           })}
           className="text-[12px] rounded-md px-2.5 py-1.5"
           style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
          Export CSV
        </a>
      </div>

      {/* Every active filter is visible and individually removable. The
          probability and coverage filters used to be settable only by an alert
          drill-through, with nothing on screen to say why the row count fell. */}
      <FilterChips filters={filters} horizon={horizon} onRemove={set} onClear={() => { setOffset(0); clearFilters(); }} />

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)] gap-5 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <Card title="Products at risk" className="min-w-0"
                subtitle="Worst first, by the money at stake. Pick one to see why it is at risk.">
            <Loadable state={positions} label="Working out what is at risk…">
              {(data) => !data.rows.length ? (
                <Empty>
                  No products match these filters. Try widening the priority or
                  clearing the search.
                </Empty>
              ) : (
                <>
                  <Table head={[
                    "Product", "Store",
                    <TermLabel key="band" name="risk_band" />,
                    <TermLabel key="stock" name="stock_on_hand" />,
                    <TermLabel key="cover" name="cover_days_now" label="Days left" />,
                    <TermLabel key="p" name={`p_stockout_${horizon}d`}
                               label={`Runs out in ${horizon}d`} />,
                    <TermLabel key="transit" name="intransit_units" label="On its way" />,
                    <TermLabel key="lost" name="expected_lost_units" label="Units we'd miss" />,
                    <TermLabel key="rev" name="expected_lost_revenue" label="Revenue at risk" />,
                  ]}>
                    {data.rows.map((row) => {
                      const active = selection?.storeId === row.store_id &&
                                     selection?.skuUid === row.sku_uid;
                      const probability = row[probabilityColumn] as number | null;
                      const select = () => focus({ storeId: row.store_id, skuUid: row.sku_uid });
                      return (
                        <tr key={`${row.store_id}-${row.sku_uid}`}
                            onClick={select}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
                            }}
                            tabIndex={0}
                            role="button"
                            aria-pressed={active}
                            aria-label={`${row.sku_uid} at ${row.store_id}`}
                            className="cursor-pointer transition-colors focus:outline-none focus-visible:ring-2"
                            style={{ background: active ? "var(--surface-3)" : undefined,
                                     borderBottom: "1px solid var(--border)" }}>
                          <td className="py-2 pr-4 font-medium">{row.sku_uid}</td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                            {row.store_id}
                          </td>
                          <td className="py-2 pr-4"><BandBadge band={row.risk_band} small /></td>
                          <td className="py-2 pr-4">{num(row.stock_on_hand)}</td>
                          <td className="py-2 pr-4">{days(row.cover_days_now)}</td>
                          <td className="py-2 pr-4"
                              style={{ color: (probability ?? 0) > 0.5
                                ? bandColor.Critical : "var(--text-primary)" }}>
                            {pct(probability)}
                          </td>
                          <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                            {num(row.intransit_units)}
                          </td>
                          <td className="py-2 pr-4">{num(row.expected_lost_units, 1)}</td>
                          <td className="py-2 pr-4">{money(row.expected_lost_revenue)}</td>
                        </tr>
                      );
                    })}
                  </Table>
                  <Pager total={data.total} offset={offset} shown={data.rows.length}
                         onOffset={setOffset} />
                </>
              )}
            </Loadable>
          </Card>

          {/* What drives risk across the whole book, not just the selected SKU.
              The endpoint existed and no page called it. */}
          <Card title="What is driving risk overall"
                subtitle="The reasons that come up most often across everything you sell">
            <Loadable state={drivers} label="Working out the main reasons…">
              {(data) => !data.drivers.length ? (
                <Empty>Not enough scored products to summarise yet.</Empty>
              ) : (
                <Table head={["Reason", "Main reason for", "Share of products", "Pushes risk"]}>
                  {data.drivers.map((driver) => (
                    <tr key={driver.feature} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td className="py-2 pr-4">
                        <DriverName feature={driver.feature} />
                      </td>
                      <td className="py-2 pr-4">{num(driver.times_top_driver)} products</td>
                      <td className="py-2 pr-4">{pct(driver.share_of_rows, 1)}</td>
                      {/* The raw coefficient meant nothing standing alone in a
                          column; direction and strength is what a planner reads
                          it for, and the number stays in the hint. */}
                      <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                        <span className="inline-flex items-center gap-1.5">
                          {driver.coefficient < 0 ? "up" : "down"}
                          <Strength value={Math.abs(driver.coefficient)} />
                          <InfoHint
                            text={driver.coefficient < 0
                              ? "A higher value here shortens how long the stock lasts."
                              : "A higher value here makes the stock last longer."}
                            technical={`coefficient ${num(driver.coefficient, 3)} on the log-days scale`} />
                        </span>
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </Loadable>
            <Note>
              A reason can top this list and still be little help. “
              {featureLabel("store_stockout_rate_90d")}” is the clearest example:
              it marks stores that run out more often than the rest, which is
              worth knowing, but there is no lever behind it — you cannot fix one
              product by fixing that number.
            </Note>
          </Card>
        </div>

        <div className="flex flex-col gap-5 xl:sticky xl:top-[96px] min-w-0">
          {!selection ? (
            <Card title="Why is this at risk?">
              <Empty>Pick a row on the left to see what is driving it.</Empty>
            </Card>
          ) : detail.error ? (
            <Card title="Why is this at risk?">
              <ErrorState message={detail.error} onRetry={detail.refetch} />
            </Card>
          ) : !detail.data ? (
            <Card title="Why is this at risk?"><Spinner label="Working out why…" /></Card>
          ) : (
            <DetailPanel detail={detail.data} horizon={horizon}
                         onSimulate={() => focus(selection, "simulate")}
                         onPrescribe={() => focus(selection, "prescribe")} />
          )}
        </div>
      </div>
    </div>
  );
}

function FilterChips({ filters, horizon, onRemove, onClear }: {
  filters: ReturnType<typeof useStore>["filters"];
  horizon: number;
  onRemove: (patch: Record<string, undefined>) => void;
  onClear: () => void;
}) {
  const chips: [string, string][] = [];
  if (filters.band) chips.push(["band", `Priority: ${filters.band}`]);
  if (filters.storeId) chips.push(["storeId", `Store: ${filters.storeId}`]);
  if (filters.category) chips.push(["category", `Category: ${filters.category}`]);
  if (filters.horizon) chips.push(["horizon", `Looking ${horizon} days ahead`]);
  if (filters.minProbability !== undefined)
    chips.push(["minProbability", `At least ${pct(filters.minProbability)} chance of running out`]);
  if (filters.coverage) chips.push(["coverage", "Not enough stock on the way"]);
  if (filters.search) chips.push(["search", `“${filters.search}”`]);
  if (!chips.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 -mt-2">
      {chips.map(([key, label]) => (
        <button key={key} onClick={() => onRemove({ [key]: undefined })}
                className="rounded-full px-2.5 py-1 text-[11.5px] flex items-center gap-1.5"
                style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
          {label}
          <span aria-hidden style={{ color: "var(--text-muted)" }}>×</span>
          <span className="sr-only">remove filter</span>
        </button>
      ))}
      <button onClick={onClear} className="text-[12px] underline underline-offset-2"
              style={{ color: "var(--text-muted)" }}>
        clear all
      </button>
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
      {/* The header used to print the full total beside 150 rows with nothing
          saying the rest were unreachable. */}
      <span className="tnum">Showing {num(first)}–{num(last)} of {num(total)}</span>
      <span className="flex gap-2">
        <button disabled={offset === 0}
                onClick={() => onOffset(Math.max(0, offset - shown))}
                className="rounded-md px-2 py-1 disabled:opacity-40"
                style={{ border: "1px solid var(--border)" }}>
          Previous
        </button>
        <button disabled={last >= total}
                onClick={() => onOffset(offset + shown)}
                className="rounded-md px-2 py-1 disabled:opacity-40"
                style={{ border: "1px solid var(--border)" }}>
          Next
        </button>
      </span>
    </div>
  );
}

function DetailPanel({ detail, horizon, onSimulate, onPrescribe }: {
  detail: PositionDetail; horizon: number; onSimulate: () => void; onPrescribe: () => void;
}) {
  const position = detail.position;
  const outAt = detail.timeline.find((t) => t.projected_stock <= 0);
  const probability = position[`p_stockout_${horizon}d` as keyof PositionDetail["position"]] as number | null;

  return (
    <>
      <Card title="Why is this at risk?"
            subtitle={`${position.sku_uid} at ${position.store_id}`}
            right={<BandBadge band={position.risk_band} />}>
        <div className="grid grid-cols-4 gap-3 mb-4">
          <MiniStat name="stock_on_hand" value={num(position.stock_on_hand)} />
          <MiniStat name="cover_days_now" label="Days left"
                    value={days(position.cover_days_now)} />
          {/* Four tiles in a narrow panel — a longer label truncates. The
              horizon is already in the card the user came from. */}
          <MiniStat name={`p_stockout_${horizon}d`} label="Runs out"
                    value={pct(probability)}
                    tone={(probability ?? 0) > 0.5 ? bandColor.Critical : undefined} />
          {/* This position's predicted stock life, which the panel never showed —
              only the typical position's, in the note below. */}
          <MiniStat name="predicted_median_days" label="Should last"
                    value={days(detail.predicted_median_days)} />
        </div>

        <DriverWaterfall drivers={detail.drivers} />

        <Note>
          Each bar is how many days that one reason adds to, or takes off, how
          long the stock should last — measured against a typical product, which
          lasts {detail.reference_median_days} days.{" "}{detail.explanation}
        </Note>
      </Card>

      <Card title="If nothing changes"
            subtitle={outAt ? `The shelf empties around day ${outAt.day} at today's selling rate`
                            : "Stock holds out for the next four weeks at today's selling rate"}>
        <DepletionChart data={detail.timeline} height={170} />
        <Note>
          A straight line at the current selling rate, with no deliveries and no
          allowance for a busy week. The simulator adds both.
        </Note>
        <div className="grid grid-cols-2 gap-2 mt-3">
          <button onClick={onSimulate}
                  className="rounded-md py-2 text-[13px] font-medium transition-opacity hover:opacity-90"
                  style={{ background: "var(--series-1)", color: "#fff" }}>
            Simulate →
          </button>
          <button onClick={onPrescribe}
                  className="rounded-md py-2 text-[13px] font-medium transition-opacity hover:opacity-90"
                  style={{ border: "1px solid var(--border)", color: "var(--text-primary)" }}>
            What to do →
          </button>
        </div>
      </Card>
    </>
  );
}

/** A driver's plain name, with its glossary explanation on the icon beside it. */
function DriverName({ feature }: { feature: string }) {
  const found = term(feature);
  return (
    <span className="inline-flex items-center gap-1.5">
      {featureLabel(feature)}
      {found && <InfoHint text={found.help} technical={found.technical} />}
    </span>
  );
}

/**
 * Three dots instead of a number.
 *
 * The coefficient is on the log-days scale, so `0.601` is not a quantity a
 * planner can do anything with; how hard this reason pushes, relative to the
 * others, is. The number itself stays one hover away.
 */
function Strength({ value }: { value: number }) {
  const filled = value >= 0.4 ? 3 : value >= 0.15 ? 2 : 1;
  return (
    <span className="inline-flex gap-[3px]" aria-label={`strength ${filled} of 3`}>
      {[0, 1, 2].map((i) => (
        <span key={i} className="w-[5px] h-[5px] rounded-full"
              style={{ background: i < filled ? "var(--series-1)" : "var(--surface-3)" }} />
      ))}
    </span>
  );
}

function MiniStat({ name, label, value, tone }: {
  name: string; label?: string; value: string; tone?: string;
}) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        <TermLabel name={name} label={label} />
      </p>
      <p className="text-[16px] font-semibold tnum" style={{ color: tone }}>{value}</p>
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
