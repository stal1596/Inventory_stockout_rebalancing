import { useState } from "react";
import { api } from "../lib/api";
import { ACTION_COLORS, ACTION_LABELS, days, num, pct } from "../lib/format";
import { Card, Empty, ErrorState, Kpi, Loadable, Note, Spinner, Table } from "../components/ui";
import { DiscriminationBars, TailCoverageBar } from "../components/charts-evidence";
import { useApi } from "../lib/useApi";

/**
 * Did the predictions hold up?
 *
 * Both endpoints rescore at an EARLIER date than the scored population, because
 * the standing `as_of` sits on the last panel date and leaves no future to check
 * against. Asking for a date with no room returns a 400 whose message names the
 * latest usable one — so that message is rendered verbatim rather than replaced
 * with a generic failure.
 */
export function Backtests() {
  const [asOf, setAsOf] = useState("");
  const [horizon, setHorizon] = useState(28);

  const simulation = useApi(
    () => api.backtestSimulation({ as_of: asOf || undefined, horizon, n_paths: 500 }),
    [asOf, horizon],
  );
  // The horizon selector drives BOTH cards. It used to be hard-coded to 14 here,
  // so moving the control relabelled one card and silently left the other on a
  // different horizon — two numbers side by side describing different windows.
  const decisions = useApi(
    () => api.backtestDecisions({ as_of: asOf || undefined, horizon, limit: 300 }),
    [asOf, horizon],
  );

  const covered = simulation.data && simulation.data.coverage_p10_p90 !== undefined
    ? simulation.data.coverage_p10_p90 : null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
          Score as of
        </label>
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)}
               className="rounded-md px-2.5 py-1.5 text-[13px] outline-none"
               style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                        color: "var(--text-primary)" }} />
        <Select value={String(horizon)} onChange={(v) => setHorizon(Number(v))}
                options={[["14", "14-day horizon"], ["28", "28-day horizon"],
                          ["56", "56-day horizon"]]} />
        {asOf && (
          <button onClick={() => setAsOf("")}
                  className="text-[12px] underline underline-offset-2"
                  style={{ color: "var(--text-muted)" }}>
            use the latest backtestable date
          </button>
        )}
      </div>

      {/* The server's message names the latest usable date, which is the only
          thing that lets a user fix the input. */}
      {simulation.error && (
        <ErrorState message={simulation.error} onRetry={simulation.refetch} />
      )}

      {!simulation.error && (
        <Loadable state={simulation} label="Re-simulating a past window…">
          {(data) => (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <Kpi label="P10–P90 coverage"
                     value={covered === null ? "—" : pct(covered, 1)}
                     sub={`target ${pct(data.expected.coverage_p10_p90)}`}
                     tone={covered !== null && Math.abs(covered - data.expected.coverage_p10_p90) > 0.1
                       ? "var(--status-serious)" : undefined} />
                <Kpi label="Ran out earlier than P10"
                     value={pct(data.breach_below_p10 ?? 0, 1)}
                     tone={(data.breach_below_p10 ?? 0) > data.expected.breach_below_p10
                       ? "var(--status-critical)" : undefined}
                     sub="the direction a planner is caught out by"
                     hint="Target ~10%. Above it, the interval is too narrow where it matters." />
                <Kpi label="Lasted longer than P90"
                     value={pct(data.breach_above_p90 ?? 0, 1)}
                     sub="expected to exceed 10%" />
                <Kpi label="Median error"
                     value={days(data.median_error_days)}
                     sub="simulated P50 minus realised" />
              </div>

              <Card title="Did the interval cover reality?"
                    subtitle={`Scored ${data.as_of}, ${data.horizon}-day window · panel ends ${data.panel_end}`}>
                {data.n === 0 ? (
                  <Empty>No position produced an observable outcome in this window.</Empty>
                ) : (
                  <>
                    <TailCoverageBar
                      below={data.breach_below_p10 ?? 0}
                      inside={covered ?? 0}
                      above={data.breach_above_p90 ?? 0}
                      expected={data.expected} />
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mt-4">
                      <Fact label="Positions simulated" value={num(data.n_positions)} />
                      <Fact label="With an observed outcome" value={num(data.n)} />
                      <Fact label="Predicted stockout rate"
                            value={pct(data.p_stockout_mean ?? 0, 1)} />
                      <Fact label="Actual stockout rate"
                            value={pct(data.actual_stockout_rate ?? 0, 1)} />
                    </div>
                    <Note>{data.note}</Note>
                  </>
                )}
              </Card>
            </>
          )}
        </Loadable>
      )}

      <Card title="Did 'act' land on the positions that ran out?"
            subtitle="Precision and recall of the decision, not of the saving">
        {decisions.error ? <ErrorState message={decisions.error} onRetry={decisions.refetch} />
          : !decisions.data ? <Spinner label="Re-valuing every lever…" />
          : decisions.data.n === 0 ? (
            <Empty>No position produced an observable outcome in this window.</Empty>
          ) : (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)] gap-5">
                <DiscriminationBars
                  acted={decisions.data.stockout_rate_when_acted ?? 0}
                  notActed={decisions.data.stockout_rate_when_not ?? null}
                  baseRate={decisions.data.base_rate ?? 0} />
                <Table head={["Measure", "Value"]}>
                  <Row label="Precision" value={pct(decisions.data.precision, 1)} />
                  <Row label="Recall" value={pct(decisions.data.recall, 1)} />
                  <Row label="Acted on" value={pct(decisions.data.acted_share, 1)} />
                  <Row label="Base rate" value={pct(decisions.data.base_rate, 1)} />
                  <Row label="Positions scored" value={num(decisions.data.n)} />
                </Table>
              </div>

              {decisions.data.mix.length > 0 && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-4 text-[11px]"
                     style={{ color: "var(--text-muted)" }}>
                  {decisions.data.mix.map((entry) => (
                    <span key={entry.recommended_action} className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm"
                            style={{ background: ACTION_COLORS[entry.recommended_action] }} />
                      {ACTION_LABELS[entry.recommended_action] ?? entry.recommended_action}
                      {" · "}{num(entry.positions)}
                    </span>
                  ))}
                </div>
              )}

              <Note>{decisions.data.read_as}</Note>
              <Note>{decisions.data.note}</Note>
            </>
          )}
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr style={{ borderBottom: "1px solid var(--border)" }}>
      <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>{label}</td>
      <td className="py-2 pr-4 font-medium">{value}</td>
    </tr>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
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
