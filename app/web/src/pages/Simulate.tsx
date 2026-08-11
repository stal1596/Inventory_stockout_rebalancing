import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Simulation } from "../lib/api";
import { bandColor, days, money, num, pct } from "../lib/format";
import { Card, Delta, Empty, Note, Spinner } from "../components/ui";
import { FanChart, ProbabilityCurve, StockoutHistogram } from "../components/charts";
import { useStore } from "../store";

interface Knobs {
  forecast_sigma?: number;
  demand_rate?: number;
  lead_mean?: number;
  lead_sigma?: number;
  start_stock?: number;
  committed_units?: number;
  horizon: number;
  n_paths: number;
}

export function Simulate() {
  const { selection, focus } = useStore();
  const navigate = useNavigate();
  const [result, setResult] = useState<Simulation | null>(null);
  const [knobs, setKnobs] = useState<Knobs>({ horizon: 42, n_paths: 4000 });
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const request = useRef(0);

  // Reset the knobs when the position changes, or a slider set for one SKU
  // silently applies to the next.
  useEffect(() => { setKnobs({ horizon: 42, n_paths: 4000 }); setTouched(false); }, [selection?.skuUid, selection?.storeId]);

  useEffect(() => {
    if (!selection) return;
    const id = ++request.current;
    setBusy(true);
    api.simulate({ store_id: selection.storeId, sku_uid: selection.skuUid, ...knobs })
      .then((r) => { if (id === request.current) setResult(r); })
      .catch(() => {})
      .finally(() => { if (id === request.current) setBusy(false); });
  }, [selection, knobs]);

  if (!selection) {
    return (
      <Card title="Monte Carlo simulation">
        <Empty>
          <div className="text-center">
            <p>Pick a position on the Stockout Risk page to simulate it.</p>
            <button onClick={() => navigate("/risk")}
                    className="mt-3 rounded-md px-3 py-1.5 text-[13px]"
                    style={{ background: "var(--series-1)", color: "#fff" }}>
              Go to Stockout Risk
            </button>
          </div>
        </Empty>
      </Card>
    );
  }

  if (!result) return <Spinner label="Running simulations…" />;

  const set = (patch: Partial<Knobs>) => { setTouched(true); setKnobs({ ...knobs, ...patch }); };
  const calibration = result.calibration;
  const base = result.baseline;
  const scenario = result.scenario;

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)] gap-5 items-start">
        <div className="flex flex-col gap-5 xl:sticky xl:top-[76px]">
          <Card title="Assumptions"
                subtitle="Baseline values are measured from this extract, not assumed">
            <div className="flex flex-col gap-4">
              <Slider label="Demand rate" unit=" /day"
                      value={knobs.demand_rate ?? result.position.demand_rate}
                      min={0} max={Math.max(result.position.demand_rate * 4, 2)} step={0.05}
                      baseline={result.position.demand_rate}
                      onChange={(v) => set({ demand_rate: v })} />
              <Slider label="Forecast error" unit=" σ"
                      value={knobs.forecast_sigma ?? calibration.forecast_sigma}
                      min={0} max={1.2} step={0.02}
                      baseline={calibration.forecast_sigma}
                      onChange={(v) => set({ forecast_sigma: v })} />
              <Slider label="Supplier lead time" unit=" days"
                      value={knobs.lead_mean ?? calibration.lead_mean}
                      min={0} max={45} step={0.5}
                      baseline={calibration.lead_mean}
                      onChange={(v) => set({ lead_mean: v })} />
              <Slider label="Lead-time variability" unit=" σ"
                      value={knobs.lead_sigma ?? calibration.lead_sigma}
                      min={0} max={20} step={0.25}
                      baseline={calibration.lead_sigma}
                      onChange={(v) => set({ lead_sigma: v })} />
              <Slider label="Starting inventory" unit=" units"
                      value={knobs.start_stock ?? result.position.start_stock}
                      min={0} max={Math.max(result.position.start_stock * 4, 60)} step={1}
                      baseline={result.position.start_stock}
                      onChange={(v) => set({ start_stock: v })} />
              <Slider label="Inbound quantity" unit=" units"
                      value={knobs.committed_units ?? result.position.committed_units}
                      min={0} max={Math.max(result.position.committed_units * 4, 60)} step={1}
                      baseline={result.position.committed_units}
                      onChange={(v) => set({ committed_units: v })} />
              <div className="grid grid-cols-2 gap-3 pt-1">
                <Slider label="Horizon" unit="d" value={knobs.horizon} min={14} max={90} step={7}
                        onChange={(v) => set({ horizon: v })} compact />
                <Slider label="Runs" unit="" value={knobs.n_paths} min={1000} max={20000} step={1000}
                        onChange={(v) => set({ n_paths: v })} compact />
              </div>
              {touched && (
                <button onClick={() => { setKnobs({ horizon: 42, n_paths: 4000 }); setTouched(false); }}
                        className="text-[12px] underline underline-offset-2 self-start"
                        style={{ color: "var(--text-muted)" }}>
                  reset to measured values
                </button>
              )}
            </div>
            <Note>{calibration.note}</Note>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Compare label="Probability of stockout"
                     baseline={pct(base.p_stockout, 1)} scenario={pct(scenario.p_stockout, 1)}
                     delta={<Delta from={base.p_stockout} to={scenario.p_stockout} />}
                     tone={scenario.p_stockout > 0.5 ? bandColor.Critical : undefined} />
            <Compare label="Expected stockout date"
                     baseline={base.days_to_stockout.p50 !== null ? `day ${base.days_to_stockout.p50}` : "beyond horizon"}
                     scenario={scenario.days_to_stockout.p50 !== null ? `day ${scenario.days_to_stockout.p50}` : "beyond horizon"} />
            <Compare label="Unmet demand"
                     baseline={`${num(base.expected_unmet_units, 1)} units`}
                     scenario={`${num(scenario.expected_unmet_units, 1)} units`} />
          </div>

          <Card title="Probability of stockout by day"
                subtitle={`${num(result.paths)} simulated runs · baseline versus your assumptions`}>
            <ProbabilityCurve baseline={base.by_day} scenario={scenario.by_day} />
            <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5" style={{ background: "var(--series-1)" }} />Baseline (measured)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5" style={{ background: "var(--series-2)",
                        borderTop: "2px dashed var(--series-2)" }} />Scenario
              </span>
            </div>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card title="Inventory trajectory"
                  subtitle="Median with a P10–P90 band, under your assumptions">
              <FanChart data={scenario.by_day} height={210} />
              <Note>
                The band widens with time because uncertainty compounds. Where it
                touches zero, some runs have already stocked out.
              </Note>
            </Card>

            <Card title="When does it run out?"
                  subtitle={`P10 ${fmtDay(scenario.days_to_stockout.p10)} · P50 ${fmtDay(scenario.days_to_stockout.p50)} · P90 ${fmtDay(scenario.days_to_stockout.p90)}`}>
              <StockoutHistogram data={scenario.histogram} height={210} />
              <Note>
                A percentile reads as "—" when too few runs reach a stockout to
                identify it, rather than being pinned to the horizon.
              </Note>
            </Card>
          </div>

          <button onClick={() => focus(selection, "prescribe")}
                  className="rounded-md py-2.5 text-[13px] font-medium transition-opacity hover:opacity-90 self-start px-5"
                  style={{ background: "var(--series-1)", color: "#fff" }}>
            What should we do about it? →
          </button>
        </div>
      </div>
      {busy && (
        <span className="fixed bottom-5 right-6 text-[12px] rounded-full px-3 py-1.5"
              style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
          simulating…
        </span>
      )}
    </div>
  );
}

const fmtDay = (value: number | null) => (value === null ? "—" : `${value}d`);

function Compare({ label, baseline, scenario, delta, tone }: {
  label: string; baseline: string; scenario: string;
  delta?: React.ReactNode; tone?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <div className="flex items-baseline gap-2">
        <span className="text-[22px] font-semibold" style={{ color: tone }}>{scenario}</span>
        {delta && <span className="text-[12px]">{delta}</span>}
      </div>
      <p className="text-[12px] mt-1" style={{ color: "var(--text-muted)" }}>
        baseline {baseline}
      </p>
    </div>
  );
}

function Slider({ label, unit, value, min, max, step, baseline, onChange, compact }: {
  label: string; unit: string; value: number; min: number; max: number; step: number;
  baseline?: number; onChange: (v: number) => void; compact?: boolean;
}) {
  const moved = baseline !== undefined && Math.abs(value - baseline) > step / 2;
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-baseline justify-between text-[12px]">
        <span style={{ color: "var(--text-secondary)" }}>{label}</span>
        <span className="tnum" style={{ color: moved ? "var(--series-2)" : "var(--text-primary)" }}>
          {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}{unit}
        </span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full accent-[var(--series-1)] cursor-pointer" />
      {!compact && baseline !== undefined && (
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
          measured: {baseline.toLocaleString(undefined, { maximumFractionDigits: 2 })}{unit}
        </span>
      )}
    </label>
  );
}
