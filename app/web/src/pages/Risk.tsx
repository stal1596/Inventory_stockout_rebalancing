import { useState } from "react";
import { api, type Position, type PositionDetail } from "../lib/api";
import { exportUrl } from "../lib/api";
import { bandColor, days, featureLabel, money, num, pct } from "../lib/format";
import {
  BandBadge, Card, Empty, ErrorState, Loadable, Note, Spinner, Table,
} from "../components/ui";
import { DepletionChart, DriverWaterfall } from "../components/charts";
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
                options={[["", "All bands"],
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
                  (h) => [String(h), `${h}-day horizon`] as [string, string])} />
        <input
          value={filters.search ?? ""}
          onChange={(e) => set({ search: e.target.value || undefined })}
          placeholder="Search SKU or store…"
          aria-label="Search SKU or store"
          className="rounded-md px-3 py-1.5 text-[13px] w-[200px] outline-none"
          style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                   color: "var(--text-primary)" }}
        />
        <span className="ml-auto text-[12px] tnum" style={{ color: "var(--text-secondary)" }}>
          {positions.data
            ? `${num(positions.data.total)} positions · ${money(positions.data.exposure)} exposed`
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
          <Card title="Positions at risk" className="min-w-0"
                subtitle="Ranked by expected lost revenue. Select one to see why.">
            <Loadable state={positions} label="Scoring open positions…">
              {(data) => !data.rows.length ? (
                <Empty>No positions match these filters.</Empty>
              ) : (
                <>
                  <Table head={["SKU", "Store", "Band", "On hand", "Cover",
                                `P(out) ${horizon}d`, "In transit", "Lost units", "Exposure"]}>
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
          <Card title="What drives risk across the population"
                subtitle="How often each feature is the largest single contributor">
            <Loadable state={drivers} label="Ranking drivers…">
              {(data) => !data.drivers.length ? (
                <Empty>No driver summary available.</Empty>
              ) : (
                <Table head={["Feature", "Top driver for", "Share of positions", "Coefficient"]}>
                  {data.drivers.map((driver) => (
                    <tr key={driver.feature} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td className="py-2 pr-4">{featureLabel(driver.feature)}</td>
                      <td className="py-2 pr-4">{num(driver.times_top_driver)}</td>
                      <td className="py-2 pr-4">{pct(driver.share_of_rows, 1)}</td>
                      <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                        {num(driver.coefficient, 3)}
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </Loadable>
            <Note>
              A feature can top this list and still add little on its own —
              `store_stockout_rate_90d` carries the largest non-intercept
              coefficient and is a store fixed effect with no lever behind it.
            </Note>
          </Card>
        </div>

        <div className="flex flex-col gap-5 xl:sticky xl:top-[76px] min-w-0">
          {!selection ? (
            <Card title="Why is this SKU at risk?">
              <Empty>Select a position to see its drivers.</Empty>
            </Card>
          ) : detail.error ? (
            <Card title="Why is this SKU at risk?">
              <ErrorState message={detail.error} onRetry={detail.refetch} />
            </Card>
          ) : !detail.data ? (
            <Card title="Why is this SKU at risk?"><Spinner label="Explaining…" /></Card>
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
  if (filters.band) chips.push(["band", `Band: ${filters.band}`]);
  if (filters.storeId) chips.push(["storeId", `Store: ${filters.storeId}`]);
  if (filters.category) chips.push(["category", `Category: ${filters.category}`]);
  if (filters.horizon) chips.push(["horizon", `${horizon}-day horizon`]);
  if (filters.minProbability !== undefined)
    chips.push(["minProbability", `Risk ≥ ${pct(filters.minProbability)}`]);
  if (filters.coverage) chips.push(["coverage", "Inbound cover short"]);
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
      <Card title="Why is this SKU at risk?"
            subtitle={`${position.sku_uid} at ${position.store_id}`}
            right={<BandBadge band={position.risk_band} />}>
        <div className="grid grid-cols-4 gap-3 mb-4">
          <MiniStat label="On hand" value={num(position.stock_on_hand)} />
          <MiniStat label="Cover" value={days(position.cover_days_now)} />
          <MiniStat label={`P(out) ${horizon}d`} value={pct(probability)}
                    tone={(probability ?? 0) > 0.5 ? bandColor.Critical : undefined} />
          {/* This position's predicted stock life, which the panel never showed —
              only the typical position's, in the note below. */}
          <MiniStat label="Predicted life" value={days(detail.predicted_median_days)} />
        </div>

        <DriverWaterfall drivers={detail.drivers} />

        <Note>
          Each bar is that feature's exact contribution to predicted stock life,
          in days, against a typical position ({detail.reference_median_days}d).
          {" "}{detail.explanation}
        </Note>
      </Card>

      <Card title="Projected depletion"
            subtitle={outAt ? `Runs dry around day ${outAt.day} at the current rate`
                            : "Survives the 28-day window at the current rate"}>
        <DepletionChart data={detail.timeline} height={170} />
        <Note>
          A straight-line projection at the observed demand rate, with no
          replenishment and no uncertainty. The simulator adds both.
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

function MiniStat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
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
