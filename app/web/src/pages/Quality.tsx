import { useState } from "react";
import { Link } from "react-router-dom";
import { api, exportUrl } from "../lib/api";
import { num, pct } from "../lib/format";
import {
  Bar, Card, DownloadCsv, Empty, Kpi, Loadable, Note, Table,
} from "../components/ui";
import { useApi } from "../lib/useApi";

/**
 * Can this extract carry the model at all?
 *
 * The scope banner comes FIRST, above every green tick, because a page of passes
 * reads as "this extract is validated" — a claim this project explicitly
 * retracts. What actually runs is stock accounting; the grain, join-rate and
 * referential checks were retired, and nothing reports destroyed date cells any
 * more.
 */
export function Quality() {
  const [severity, setSeverity] = useState("");
  const [passed, setPassed] = useState("");

  const checks = useApi(
    () => api.validation({
      severity: severity || undefined,
      passed: passed === "" ? undefined : passed === "true",
    }),
    [severity, passed],
  );
  const movement = useApi(() => api.movement(), []);
  const structure = useApi(() => api.dcStructure(), []);

  return (
    <div className="flex flex-col gap-5">
      <Loadable state={checks} label="Running the accounting invariants…">
        {(data) => (
          <>
            <Card title="What was actually checked" subtitle={`module: ${data.scope.module}`}>
              <p className="text-[13px] leading-relaxed">{data.scope.note}</p>
            </Card>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Kpi label="Checks run" value={num(data.n_checks)} sub="in this extract" />
              <Kpi label="Failed" value={num(data.n_failed)}
                   tone={data.n_failed ? "var(--status-serious)" : undefined}
                   sub="of every severity" />
              <Kpi label="Blocking" value={num(data.n_blocking)}
                   tone={data.n_blocking ? "var(--status-critical)" : undefined}
                   sub="severity = error" />
              <Kpi label="Unexplained loss"
                   value={movement.data ? num(movement.data.unexplained_loss_units) : "—"}
                   sub={movement.data
                     ? `${pct(movement.data.unexplained_share_of_sales ?? 0, 2)} of sales`
                     : "measuring…"} />
            </div>

            <Card title="Accounting invariants"
                  subtitle={`Showing ${num(data.n_shown)} of ${num(data.n_checks)}`}
                  right={
                    <span className="flex items-center gap-2">
                      <Select value={severity} onChange={setSeverity}
                              options={[["", "All severities"], ["error", "Error"],
                                        ["warn", "Warning"], ["info", "Info"]]} />
                      <Select value={passed} onChange={setPassed}
                              options={[["", "Pass and fail"], ["false", "Failing only"],
                                        ["true", "Passing only"]]} />
                      <DownloadCsv href={exportUrl.validation()} label="All checks" />
                    </span>
                  }>
              {!data.checks.length ? <Empty>No checks match these filters.</Empty> : (
                <Table head={["", "Check", "Table", "Severity", "Bad / total", "Summary"]}>
                  {data.checks.map((check) => (
                    <tr key={`${check.check}-${check.table}`}
                        style={{ borderBottom: "1px solid var(--border)" }}>
                      {/* A word beside the dot: colour never carries the verdict. */}
                      <td className="py-2 pr-3 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1.5 text-[12px]"
                              style={{ color: check.passed
                                ? "var(--success-text)" : "var(--status-critical)" }}>
                          <span className="w-2 h-2 rounded-full"
                                style={{ background: check.passed
                                  ? "var(--status-good)" : "var(--status-critical)" }} />
                          {check.passed ? "pass" : "fail"}
                        </span>
                      </td>
                      <td className="py-2 pr-4 font-medium">{check.check}</td>
                      <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                        {check.table}
                      </td>
                      <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                        {check.severity}
                      </td>
                      <td className="py-2 pr-4">
                        {num(check.n_bad)} / {num(check.n_total)}
                      </td>
                      <td className="py-2 pr-4 text-[12px] leading-relaxed max-w-[460px]"
                          style={{ color: "var(--text-secondary)" }}>
                        {check.summary}
                        {check.detail && (
                          <span className="block mt-1" style={{ color: "var(--text-muted)" }}>
                            {check.detail}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
              <Note>
                The totals describe the extract; the filters describe this view.
                Narrowing the list does not change how many checks ran.
              </Note>
            </Card>
          </>
        )}
      </Loadable>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
        <Card title="Stock that moved with nothing behind it"
              subtitle="The only instrument that sees an untracked transfer">
          <Loadable state={movement} label="Scanning stock movement…">
            {(data) => (
              <>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <Fact label="Transitions" value={num(data.transitions ?? 0)} />
                  <Fact label="Unexplained events" value={num(data.unexplained_loss_events ?? 0)} />
                  <Fact label="Unexplained units" value={num(data.unexplained_loss_units ?? 0)} />
                  <Fact label="Worst single loss" value={num(data.worst_single_loss ?? 0)} />
                </div>
                <p className="text-[11px] uppercase tracking-wider mb-1"
                   style={{ color: "var(--text-muted)" }}>
                  Share of sales
                </p>
                <Bar value={data.unexplained_share_of_sales ?? 0} max={0.1}
                     color="var(--status-serious)" />
                <p className="text-[12px] mt-1 tnum" style={{ color: "var(--text-secondary)" }}>
                  {pct(data.unexplained_share_of_sales ?? 0, 2)} of units sold
                </p>

                {/* Not a muted footnote: this is the finding that model quality
                    IMPROVES as the data gets less truthful. */}
                <div className="rounded-md px-4 py-3 mt-4 text-[12px] leading-relaxed"
                     style={{ background: "color-mix(in srgb, var(--status-warning) 12%, transparent)",
                              border: "1px solid var(--status-warning)" }}>
                  {data.why_metrics_will_not_warn_you}
                </div>
                <Note>{data.note} Instrument: <code>{data.instrument}</code>.</Note>
              </>
            )}
          </Loadable>
        </Card>

        <Card title="Can the store → DC mapping be recovered?"
              subtitle="Asked of the data, not of the configuration">
          <Loadable state={structure} label="Comparing store columns…">
            {(data) => (
              <>
                <p className="text-[14px] leading-relaxed">{data.verdict}</p>
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <Fact label="Groups recovered" value={num(data.n_groups)} />
                  <Fact label="Varying share"
                        value={data.varying_share === undefined
                          ? "—" : pct(data.varying_share, 1)} />
                </div>
                <Note>{data.note}</Note>
                <Link to="/network" className="text-[12px] underline underline-offset-2 mt-2 inline-block"
                      style={{ color: "var(--series-1)" }}>
                  See the network this recovers →
                </Link>
              </>
            )}
          </Loadable>
        </Card>
      </div>
    </div>
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
            className="rounded-md px-2.5 py-1.5 text-[12px] outline-none cursor-pointer"
            style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                     color: "var(--text-primary)" }}>
      {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
}
