import { useEffect, useMemo, useState } from "react";
import { api, type Position, type PositionDetail } from "../lib/api";
import { bandColor, days, money, num, pct } from "../lib/format";
import { BandBadge, Card, Empty, Kpi, Note, Spinner, Table } from "../components/ui";
import { DepletionChart, DriverWaterfall } from "../components/charts";
import { useStore } from "../store";

export function Risk() {
  const { selection, focus, filters, setFilters } = useStore();
  const [data, setData] = useState<{ total: number; exposure: number; rows: Position[] } | null>(null);
  const [detail, setDetail] = useState<PositionDetail | null>(null);
  const [options, setOptions] = useState<{ stores: any[]; categories: string[] } | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => { api.filters().then(setOptions).catch(() => {}); }, []);

  useEffect(() => {
    api.positions({
      band: filters.band, store_id: filters.storeId, category: filters.category,
      min_probability: filters.minProbability, coverage: filters.coverage,
      search: filters.search, limit: 150,
    }).then(setData).catch(() => setData(null));
  }, [filters]);

  useEffect(() => {
    if (!selection) { setDetail(null); return; }
    setLoadingDetail(true);
    api.position(selection.storeId, selection.skuUid)
      .then(setDetail).catch(() => setDetail(null))
      .finally(() => setLoadingDetail(false));
  }, [selection]);

  return (
    <div className="flex flex-col gap-5">
      {/* Filters in one row above the content. */}
      <div className="flex flex-wrap items-center gap-2">
        <Select value={filters.band ?? ""} onChange={(v) => setFilters({ ...filters, band: v || undefined })}
                options={[["", "All bands"], ["Critical", "Critical"], ["High", "High"],
                          ["Medium", "Medium"], ["Low", "Low"]]} />
        <Select value={filters.storeId ?? ""}
                onChange={(v) => setFilters({ ...filters, storeId: v || undefined })}
                options={[["", "All stores"],
                          ...(options?.stores ?? []).map((s) => [s.store_id, `${s.store_id} · ${s.city}`] as [string, string])]} />
        <Select value={filters.category ?? ""}
                onChange={(v) => setFilters({ ...filters, category: v || undefined })}
                options={[["", "All categories"],
                          ...(options?.categories ?? []).map((c) => [c, c] as [string, string])]} />
        <input
          value={filters.search ?? ""}
          onChange={(e) => setFilters({ ...filters, search: e.target.value || undefined })}
          placeholder="Search SKU or store…"
          className="rounded-md px-3 py-1.5 text-[13px] w-[200px] outline-none"
          style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                   color: "var(--text-primary)" }}
        />
        {Object.values(filters).some(Boolean) && (
          <button onClick={() => setFilters({})} className="text-[12px] underline underline-offset-2"
                  style={{ color: "var(--text-muted)" }}>
            clear filters
          </button>
        )}
        <span className="ml-auto text-[12px] tnum" style={{ color: "var(--text-secondary)" }}>
          {data ? `${num(data.total)} positions · ${money(data.exposure)} exposed` : ""}
        </span>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)] gap-5 items-start">
        <Card title="Positions at risk" className="min-w-0"
              subtitle="Ranked by expected lost revenue. Select one to see why.">
          {!data ? <Spinner /> : !data.rows.length ? (
            <Empty>No positions match these filters.</Empty>
          ) : (
            <Table head={["SKU", "Store", "Band", "Cover", "P(out) 14d", "Lost units", "Exposure"]}>
              {data.rows.map((row) => {
                const active = selection?.storeId === row.store_id &&
                               selection?.skuUid === row.sku_uid;
                return (
                  <tr key={`${row.store_id}-${row.sku_uid}`}
                      onClick={() => focus({ storeId: row.store_id, skuUid: row.sku_uid })}
                      className="cursor-pointer transition-colors"
                      style={{ background: active ? "var(--surface-3)" : undefined,
                               borderBottom: "1px solid var(--border)" }}>
                    <td className="py-2 pr-4 font-medium">{row.sku_uid}</td>
                    <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                      {row.store_id}
                    </td>
                    <td className="py-2 pr-4"><BandBadge band={row.risk_band} small /></td>
                    <td className="py-2 pr-4">{days(row.cover_days_now)}</td>
                    <td className="py-2 pr-4"
                        style={{ color: (row.p_stockout_14d ?? 0) > 0.5
                          ? bandColor.Critical : "var(--text-primary)" }}>
                      {pct(row.p_stockout_14d)}
                    </td>
                    <td className="py-2 pr-4">{num(row.expected_lost_units, 1)}</td>
                    <td className="py-2 pr-4">{money(row.expected_lost_revenue)}</td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Card>

        <div className="flex flex-col gap-5 xl:sticky xl:top-[76px] min-w-0">
          {!selection ? (
            <Card title="Why is this SKU at risk?">
              <Empty>Select a position to see its drivers.</Empty>
            </Card>
          ) : loadingDetail || !detail ? (
            <Card title="Why is this SKU at risk?"><Spinner label="Explaining…" /></Card>
          ) : (
            <DetailPanel detail={detail} onSimulate={() => focus(selection, "simulate")} />
          )}
        </div>
      </div>
    </div>
  );
}

function DetailPanel({ detail, onSimulate }: { detail: PositionDetail; onSimulate: () => void }) {
  const position = detail.position;
  const outAt = detail.timeline.find((t) => t.projected_stock <= 0);

  return (
    <>
      <Card title="Why is this SKU at risk?"
            subtitle={`${position.sku_uid} at ${position.store_id}`}
            right={<BandBadge band={position.risk_band} />}>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <MiniStat label="On hand" value={num(position.stock_on_hand)} />
          <MiniStat label="Cover" value={days(position.cover_days_now)} />
          <MiniStat label="P(out) 14d" value={pct(position.p_stockout_14d)}
                    tone={(position.p_stockout_14d ?? 0) > 0.5 ? bandColor.Critical : undefined} />
        </div>

        <DriverWaterfall drivers={detail.drivers} />

        <Note>
          Each bar is that feature's exact contribution to predicted stock life,
          in days, against a typical position ({detail.reference_median_days}d).
          They are contributions, not causes — a driver says where the risk comes
          from, not which lever fixes it.
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
        <button onClick={onSimulate}
                className="mt-3 w-full rounded-md py-2 text-[13px] font-medium transition-opacity hover:opacity-90"
                style={{ background: "var(--series-1)", color: "#fff" }}>
          Simulate this position under uncertainty →
        </button>
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
