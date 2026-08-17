import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { bandColor, days, money, num, pct } from "../lib/format";
import {
  Card, Delta, Empty, ErrorState, InfoHint, Note, Spinner, TermLabel,
} from "../components/ui";
import { FanChart, ProbabilityCurve, StockoutHistogram } from "../components/charts";
import { PopulationPanel } from "../components/PopulationPanel";
import { useApi, useDebounced } from "../lib/useApi";
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
  const [knobs, setKnobs] = useState<Knobs>({ horizon: 42, n_paths: 4000 });
  const [touched, setTouched] = useState(false);
  const [mode, setMode] = useState<"position" | "population">("position");

  // Reset the knobs when the position changes, or a slider set for one SKU
  // silently applies to the next.
  useEffect(() => { setKnobs({ horizon: 42, n_paths: 4000 }); setTouched(false); }, [selection?.skuUid, selection?.storeId]);

  // One POST used to fire per `onChange` of a range input, at up to 20,000
  // paths. Debouncing the knobs rather than the request keeps the position the
  // user actually stopped on.
  const settled = useDebounced(knobs, 250);
  const simulation = useApi(
    () =>
      selection
        ? api.simulate({ store_id: selection.storeId, sku_uid: selection.skuUid, ...settled })
        : Promise.resolve(null),
    [selection?.storeId, selection?.skuUid, JSON.stringify(settled)],
  );
  const result = simulation.data;
  const busy = simulation.loading || settled !== knobs;

  const modeSwitch = (
    <div className="flex items-center gap-1 rounded-md p-0.5 w-fit"
         style={{ background: "var(--surface-3)" }}>
      {(["position", "population"] as const).map((option) => (
        <button key={option} onClick={() => setMode(option)}
                aria-pressed={mode === option}
                className="rounded px-3 py-1.5 text-[13px] transition-colors"
                style={{ background: mode === option ? "var(--surface-1)" : "transparent",
                         color: mode === option ? "var(--text-primary)" : "var(--text-secondary)",
                         fontWeight: mode === option ? 600 : 450 }}>
          {option === "position" ? "This product" : "Everything at once"}
        </button>
      ))}
    </div>
  );

  if (mode === "population") {
    return (
      <div className="flex flex-col gap-5">
        {modeSwitch}
        <PopulationPanel />
      </div>
    );
  }

  if (!selection) {
    return (
      <div className="flex flex-col gap-5">
        {modeSwitch}
        <Card title="What could happen">
          <Empty>
            <div className="text-center">
              <p>Pick a product on the Stockout Risk page to play it forward.</p>
              <p className="mt-1 text-[12px]">
                Or switch to <strong>Everything at once</strong> to run a whole
                slice of the range together.
              </p>
              <button onClick={() => navigate("/risk")}
                      className="mt-3 rounded-md px-3 py-1.5 text-[13px]"
                      style={{ background: "var(--series-1)", color: "#fff" }}>
                Go to Stockout Risk
              </button>
            </div>
          </Empty>
        </Card>
      </div>
    );
  }

  // An error clears the result rather than leaving the previous numbers on
  // screen under changed sliders -- the failure mode that let a user read
  // results which did not correspond to the visible inputs.
  if (simulation.error) {
    return (
      <Card title="What could happen">
        <ErrorState message={simulation.error} onRetry={simulation.refetch} />
      </Card>
    );
  }
  if (!result) return <Spinner label="Playing the next few weeks out…" />;

  const set = (patch: Partial<Knobs>) => { setTouched(true); setKnobs({ ...knobs, ...patch }); };
  const calibration = result.calibration;
  const base = result.baseline;
  const scenario = result.scenario;

  return (
    <div className="flex flex-col gap-5">
      {modeSwitch}
      <div className="grid grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)] gap-5 items-start">
        <div className="flex flex-col gap-5 xl:sticky xl:top-[96px]">
          <Card title="What if…"
                subtitle="Every starting value below is measured from your own data. Drag one to ask what changes.">
            <div className="flex flex-col gap-4">
              <Slider name="trailing_demand_rate" label="Selling rate" unit=" a day"
                      value={knobs.demand_rate ?? result.position.demand_rate}
                      min={0} max={Math.max(result.position.demand_rate * 4, 2)} step={0.05}
                      baseline={result.position.demand_rate}
                      onChange={(v) => set({ demand_rate: v })} />
              <Slider name="forecast_sigma" label="Forecast error" unit=""
                      value={knobs.forecast_sigma ?? calibration.forecast_sigma}
                      min={0} max={1.2} step={0.02}
                      baseline={calibration.forecast_sigma}
                      onChange={(v) => set({ forecast_sigma: v })} />
              <Slider name="lead_mean" label="Delivery time" unit=" days"
                      value={knobs.lead_mean ?? calibration.lead_mean}
                      min={0} max={45} step={0.5}
                      baseline={calibration.lead_mean}
                      onChange={(v) => set({ lead_mean: v })} />
              <Slider name="lead_sigma" label="Delivery reliability" unit=" days swing"
                      value={knobs.lead_sigma ?? calibration.lead_sigma}
                      min={0} max={20} step={0.25}
                      baseline={calibration.lead_sigma}
                      onChange={(v) => set({ lead_sigma: v })} />
              <Slider name="stock_on_hand" label="Stock on the shelf" unit=" units"
                      value={knobs.start_stock ?? result.position.start_stock}
                      min={0} max={Math.max(result.position.start_stock * 4, 60)} step={1}
                      baseline={result.position.start_stock}
                      onChange={(v) => set({ start_stock: v })} />
              <Slider name="committed_units" label="Already on its way" unit=" units"
                      value={knobs.committed_units ?? result.position.committed_units}
                      min={0} max={Math.max(result.position.committed_units * 4, 60)} step={1}
                      baseline={result.position.committed_units}
                      onChange={(v) => set({ committed_units: v })} />
              <div className="grid grid-cols-2 gap-3 pt-1">
                <Slider label="Look ahead" unit=" days" value={knobs.horizon}
                        min={14} max={90} step={7}
                        onChange={(v) => set({ horizon: v })} compact />
                <Slider name="n_paths" label="Runs" unit="" value={knobs.n_paths}
                        min={1000} max={20000} step={1000}
                        onChange={(v) => set({ n_paths: v })} compact />
              </div>
              {touched && (
                <button onClick={() => { setKnobs({ horizon: 42, n_paths: 4000 }); setTouched(false); }}
                        className="text-[12px] underline underline-offset-2 self-start"
                        style={{ color: "var(--text-muted)" }}>
                  put everything back to the measured values
                </button>
              )}
            </div>
            {/* The server's own sentence about how these were calibrated. It is
                precise and worth keeping, but it is not the first thing a
                planner needs to read, so it sits behind the icon. */}
            <p className="text-[12px] leading-relaxed mt-3 inline-flex items-start gap-1.5"
               style={{ color: "var(--text-muted)" }}>
              These come from your own history, not from a textbook.
              <InfoHint text={calibration.note} />
            </p>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Compare name="p_stockout" label="Chance of running out"
                     baseline={pct(base.p_stockout, 1)} scenario={pct(scenario.p_stockout, 1)}
                     delta={<Delta from={base.p_stockout} to={scenario.p_stockout} />}
                     tone={scenario.p_stockout > 0.5 ? bandColor.Critical : undefined} />
            <Compare name="days_to_stockout_p50" label="Likely to run out on"
                     baseline={base.days_to_stockout.p50 !== null ? `day ${base.days_to_stockout.p50}` : "not in this window"}
                     scenario={scenario.days_to_stockout.p50 !== null ? `day ${scenario.days_to_stockout.p50}` : "not in this window"} />
            <Compare name="expected_unmet_units" label="Sales we'd miss"
                     baseline={`${num(base.expected_unmet_units, 1)} units`}
                     scenario={`${num(scenario.expected_unmet_units, 1)} units`} />
          </div>

          <Card title="Chance of having run out, day by day"
                subtitle={`Across ${num(result.paths)} runs · today's reality against your what-if`}>
            <ProbabilityCurve baseline={base.by_day} scenario={scenario.by_day} />
            <div className="flex items-center gap-4 mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5" style={{ background: "var(--series-1)" }} />As things stand
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5" style={{ background: "var(--series-2)",
                        borderTop: "2px dashed var(--series-2)" }} />Your what-if
              </span>
            </div>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card title="How the stock runs down"
                  subtitle="The middle line is the likeliest path; the shaded band is the realistic best and worst case">
              <FanChart data={scenario.by_day} height={210} />
              <Note>
                The band widens further out because small differences compound.
                Where it touches zero, some runs have already sold out.
              </Note>
            </Card>

            <Card title="When does it run out?"
                  subtitle={
                    <span className="inline-flex flex-wrap items-center gap-x-1 gap-y-0.5">
                      <TermLabel name="days_to_stockout_p10" label="Earliest likely" />
                      {" "}{fmtDay(scenario.days_to_stockout.p10)} ·
                      <TermLabel name="days_to_stockout_p50" label="Typical" />
                      {" "}{fmtDay(scenario.days_to_stockout.p50)} ·
                      <TermLabel name="days_to_stockout_p90" label="Latest likely" />
                      {" "}{fmtDay(scenario.days_to_stockout.p90)}
                    </span>
                  }>
              <StockoutHistogram data={scenario.histogram} height={210} />
              <Note>
                A dash means too few runs sold out to put a date on it — better
                than quoting one we would be making up.
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

function Compare({ name, label, baseline, scenario, delta, tone }: {
  name: string; label: string; baseline: string; scenario: string;
  delta?: React.ReactNode; tone?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
        <TermLabel name={name} label={label} />
      </p>
      <div className="flex items-baseline gap-2">
        <span className="text-[22px] font-semibold" style={{ color: tone }}>{scenario}</span>
        {delta && <span className="text-[12px]">{delta}</span>}
      </div>
      <p className="text-[12px] mt-1" style={{ color: "var(--text-muted)" }}>
        as things stand, {baseline}
      </p>
    </div>
  );
}

function Slider({ name, label, unit, value, min, max, step, baseline, onChange, compact }: {
  /** Optional glossary key — adds the hint explaining what the knob does. */
  name?: string;
  label: string; unit: string; value: number; min: number; max: number; step: number;
  baseline?: number; onChange: (v: number) => void; compact?: boolean;
}) {
  const moved = baseline !== undefined && Math.abs(value - baseline) > step / 2;
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-baseline justify-between gap-2 text-[12px]">
        <span style={{ color: "var(--text-secondary)" }}>
          {name ? <TermLabel name={name} label={label} /> : label}
        </span>
        <span className="tnum" style={{ color: moved ? "var(--series-2)" : "var(--text-primary)" }}>
          {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}{unit}
        </span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full accent-[var(--series-1)] cursor-pointer" />
      {!compact && baseline !== undefined && (
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
          yours today: {baseline.toLocaleString(undefined, { maximumFractionDigits: 2 })}{unit}
        </span>
      )}
    </label>
  );
}
