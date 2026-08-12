import { useState } from "react";
import { api } from "../lib/api";
import { days, num, pct } from "../lib/format";
import { Card, Empty, ErrorState, Kpi, Loadable, Note, Spinner, Table } from "../components/ui";
import {
  CalibrationPlot, CifPartitionChart, CoefficientBars, KmBiasCurves,
} from "../components/charts-evidence";
import { useApi } from "../lib/useApi";

/**
 * Why you should believe the model.
 *
 * Six independent calls, each owning its own card's loading and error state.
 * Bundling them would gate the page on the slowest: the KM-bias measurement is
 * 8.3 seconds cold, and it is the one result worth waiting for rather than the
 * one that should block the other five.
 *
 * Every section renders the endpoint's OWN framing string rather than prose
 * written here. Kaplan-Meier and Aalen-Johansen answer different questions —
 * one is not a fixed version of the other — and those strings are where that
 * distinction is stated.
 */
export function Evidence() {
  const [horizon, setHorizon] = useState(14);
  const [bins, setBins] = useState(10);
  const [actionableOnly, setActionableOnly] = useState(false);

  const evaluation = useApi(() => api.modelEvaluation(), []);
  const calibration = useApi(() => api.modelCalibration(horizon, bins), [horizon, bins]);
  const bias = useApi(() => api.kmBias(), []);
  const risks = useApi(() => api.competingRisks(), []);
  const coefficients = useApi(() => api.coefficients(), []);
  const registry = useApi(() => api.featureRegistry(), []);

  const primary = evaluation.data?.models.find((m) => m.model === evaluation.data?.primary);
  const rival = evaluation.data?.models.find((m) => m.model !== evaluation.data?.primary);

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Held-out C-index"
             value={primary ? num(primary.c_index_test, 4) : "—"}
             sub={rival ? `${rival.model.split(" ")[0]} ${num(rival.c_index_test, 4)}` : ""}
             hint="Discrimination: is the ranking right? 0.5 is a coin flip." />
        <Kpi label={`Brier @ ${horizon}d`}
             value={calibration.data ? num(calibration.data.brier, 4) : "—"}
             sub="lower is better; 0.25 is a coin flip" />
        <Kpi label="Max calibration gap"
             value={calibration.data?.max_gap === null || calibration.data === null
               ? "—" : pct(calibration.data.max_gap, 1)}
             sub="worst predicted-minus-observed bin" />
        <Kpi label="Naive KM bias"
             value={bias.data?.available ? days(bias.data.median_gap_days) : "n/a"}
             tone={bias.data?.available ? "var(--status-serious)" : undefined}
             sub={bias.data?.available
               ? `median, ${bias.data.direction}`
               : "needs a counterfactual arm"} />
      </div>

      {/* ---- discrimination -------------------------------------------- */}
      <Card title="The model against its alternative"
            subtitle="Held-out discrimination and accuracy">
        <Loadable state={evaluation} label="Fitting the comparison…">
          {(data) => (
            <>
              <Table head={["Model", "C-index (test)", "C-index (train)", "Brier 7d",
                            "14d", "28d", "Max gap", "Events (test)"]}>
                {data.models.map((model) => (
                  <tr key={model.model} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td className="py-2 pr-4 font-medium">
                      <span className="inline-flex items-center gap-2">
                        {model.model === data.primary && (
                          <span className="w-2 h-2 rounded-full"
                                style={{ background: "var(--series-1)" }} />
                        )}
                        {model.model}
                        {model.model === data.primary && (
                          <span className="text-[10px] uppercase tracking-wider"
                                style={{ color: "var(--text-muted)" }}>primary</span>
                        )}
                      </span>
                    </td>
                    <td className="py-2 pr-4">{num(model.c_index_test, 4)}</td>
                    <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                      {num(model.c_index_train, 4)}
                    </td>
                    <td className="py-2 pr-4">{num(model.brier_7d, 4)}</td>
                    <td className="py-2 pr-4">{num(model.brier_14d, 4)}</td>
                    <td className="py-2 pr-4">{num(model.brier_28d, 4)}</td>
                    <td className="py-2 pr-4">{num(model.calibration_max_gap, 4)}</td>
                    <td className="py-2 pr-4">{num(model.events_test)}</td>
                  </tr>
                ))}
              </Table>
              <Note>{data.note}</Note>
              {/* The one that stops 0.72 -> 0.79 being read as improvement. */}
              <Note>{data.comparability}</Note>
            </>
          )}
        </Loadable>
      </Card>

      {/* ---- calibration ------------------------------------------------ */}
      <Card title="Do the probabilities mean anything?"
            subtitle="Predicted against observed, by predicted-risk bin"
            right={
              <span className="flex items-center gap-2">
                <Select value={String(horizon)} onChange={(v) => setHorizon(Number(v))}
                        options={[["7", "7 days"], ["14", "14 days"], ["28", "28 days"]]} />
                <Select value={String(bins)} onChange={(v) => setBins(Number(v))}
                        options={[["5", "5 bins"], ["10", "10 bins"], ["20", "20 bins"]]} />
              </span>
            }>
        <Loadable state={calibration} label="Binning the holdout…">
          {(data) => (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)] gap-5">
                <CalibrationPlot bins={data.bins} />
                <Table head={["Bin", "n", "Predicted", "Observed", "Gap"]}>
                  {data.bins.map((bin) => (
                    <tr key={bin.bin} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td className="py-1.5 pr-4">{bin.bin + 1}</td>
                      <td className="py-1.5 pr-4">{num(bin.n)}</td>
                      <td className="py-1.5 pr-4">{pct(bin.predicted_mean, 1)}</td>
                      <td className="py-1.5 pr-4">{pct(bin.observed_km, 1)}</td>
                      <td className="py-1.5 pr-4"
                          style={{ color: Math.abs(bin.gap) > 0.1
                            ? "var(--status-serious)" : "var(--text-secondary)" }}>
                        {pct(bin.gap, 1)}
                      </td>
                    </tr>
                  ))}
                </Table>
              </div>
              <Note>{data.note}</Note>
            </>
          )}
        </Loadable>
      </Card>

      {/* ---- KM bias ---------------------------------------------------- */}
      <Card title="What naive Kaplan-Meier gets wrong"
            subtitle="Measured against a counterfactual arm where replenishment was disabled">
        {bias.error ? <ErrorState message={bias.error} onRetry={bias.refetch} />
          : !bias.data ? <Spinner label="Measuring the bias…" />
          : !bias.data.available ? <Empty>{bias.data.reason}</Empty>
          : (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-4">
                <Fact label="Naive median" value={days(bias.data.median_naive)} />
                <Fact label="True median" value={days(bias.data.median_true)} />
                <Fact label="Gap" value={days(bias.data.median_gap_days)}
                      tone="var(--status-serious)" />
                <Fact label="Censored by replenishment"
                      value={pct(bias.data.censored_share, 1)} />
              </div>
              <KmBiasCurves curve={bias.data.curve} gapAt={bias.data.gap_at} />
              <div className="flex flex-wrap items-center gap-4 mt-2 text-[11px]"
                   style={{ color: "var(--text-muted)" }}>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm"
                        style={{ background: "var(--series-2)" }} />
                  Naive KM on the observed world
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm"
                        style={{ background: "var(--series-1)" }} />
                  True, from the counterfactual
                </span>
                <span>shaded band: survival the naive curve claims and the world does not deliver</span>
              </div>
              <p className="text-[13px] mt-3">{bias.data.summary}</p>
              <Note>{bias.data.question}</Note>
            </>
          )}
      </Card>

      {/* ---- competing risks -------------------------------------------- */}
      <Card title="Competing risks: the partition self-check"
            subtitle="Stockout, replenishment and survival must account for everything">
        <Loadable state={risks} label="Fitting Aalen-Johansen…">
          {(data) => (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,260px)] gap-5">
                <CifPartitionChart curve={data.curve} />
                <div className="flex flex-col gap-2">
                  <Fact label="Partition closes to within"
                        value={data.partition_error.toExponential(1)} />
                  <Fact label={`AJ vs empirical, t ≤ ${data.aj_vs_empirical_days}`}
                        value={num(data.aj_vs_empirical_max_gap, 4)} />
                </div>
              </div>
              {/* Stated separately from KM's question, so the two cannot read as
                  two versions of one curve. */}
              <Note>{data.question}</Note>
              <Note>{data.note}</Note>
            </>
          )}
        </Loadable>
      </Card>

      {/* ---- coefficients ------------------------------------------------ */}
      <Card title="The fitted model, in full"
            subtitle="Positive buys the position time; negative costs it time"
            right={
              <label className="flex items-center gap-2 text-[12px] cursor-pointer"
                     style={{ color: "var(--text-secondary)" }}>
                <input type="checkbox" checked={actionableOnly}
                       onChange={(e) => setActionableOnly(e.target.checked)} />
                actionable only
              </label>
            }>
        <Loadable state={coefficients} label="Reading the coefficients…">
          {(data) => (
            <>
              <CoefficientBars rows={data.coefficients} actionableOnly={actionableOnly} />
              <div className="rounded-md px-4 py-3 mt-4"
                   style={{ background: "var(--surface-3)" }}>
                <p className="text-[11px] uppercase tracking-wider"
                   style={{ color: "var(--text-muted)" }}>
                  Cover coefficient
                </p>
                <p className="text-[22px] font-semibold tnum">
                  {num(data.cover_coefficient, 4)}
                </p>
                <p className="text-[12px] leading-relaxed mt-1"
                   style={{ color: "var(--text-secondary)" }}>
                  {data.cover_note}
                </p>
              </div>
              {data.coefficients.filter((c) => c.caution).map((c) => (
                <div key={c.feature} className="rounded-md px-4 py-3 mt-3 text-[12px] leading-relaxed"
                     style={{ background: "color-mix(in srgb, var(--status-warning) 12%, transparent)",
                              border: "1px solid var(--status-warning)" }}>
                  <span className="font-semibold">{c.feature}</span> — {c.caution}
                </div>
              ))}
              <Note>{data.note}</Note>
            </>
          )}
        </Loadable>
      </Card>

      {/* ---- feature registry -------------------------------------------- */}
      <Card title="Feature registry"
            subtitle="Read from the registry itself, so a newly registered feature appears here">
        <Loadable state={registry} label="Reading the registry…">
          {(data) => (
            <>
              <div className="flex flex-wrap gap-2 mb-4">
                {data.groups.map((group) => (
                  <span key={group.group} className="text-[11px] rounded px-2 py-1"
                        style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
                    {group.group} · {group.n}
                  </span>
                ))}
                <span className="text-[11px] rounded px-2 py-1"
                      style={{ background: "var(--surface-3)", color: "var(--text-muted)" }}>
                  {data.n_fitted} fitted of {data.n_registered} registered
                </span>
              </div>
              <Table head={["Feature", "Group", "Kind", "In model", "Description"]}>
                {data.features.map((feature) => (
                  <tr key={feature.name} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td className="py-2 pr-4 font-medium">{feature.name}</td>
                    <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                      {feature.group}
                    </td>
                    <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                      {feature.kind}
                    </td>
                    <td className="py-2 pr-4"
                        style={{ color: feature.in_model
                          ? "var(--text-primary)" : "var(--text-muted)" }}>
                      {feature.in_model ? "yes" : "attached only"}
                    </td>
                    <td className="py-2 pr-4 text-[12px] leading-relaxed max-w-[420px]"
                        style={{ color: "var(--text-secondary)" }}>
                      {feature.description}
                    </td>
                  </tr>
                ))}
              </Table>
              <Note>{data.note}</Note>
              <Note>
                Trailing window {data.windows.trailing_window_days} days, burn-in{" "}
                {data.windows.burn_in_days} days. {data.windows.note}
              </Note>
            </>
          )}
        </Loadable>
      </Card>
    </div>
  );
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p className="text-[15px] font-semibold tnum mt-0.5" style={{ color: tone }}>{value}</p>
    </div>
  );
}

function Select({ value, onChange, options }: {
  value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
            className="rounded-md px-2.5 py-1.5 text-[12px] outline-none cursor-pointer"
            style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                     color: "var(--text-primary)" }}>
      {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
}
