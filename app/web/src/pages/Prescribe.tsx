import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, exportUrl, type Recommendation } from "../lib/api";
import { ACTION_COLORS, ACTION_LABELS, money, num, pct } from "../lib/format";
import {
  Card, DownloadCsv, Empty, ErrorState, Kpi, Loadable, Note, Spinner, Table, TermLabel,
} from "../components/ui";
import { ScenarioPanel } from "../components/ScenarioPanel";
import { useApi } from "../lib/useApi";
import { useStore } from "../store";

const PAGE_SIZE = 120;

export function Prescribe() {
  const { selection, focus } = useStore();
  // The action filter lives in the URL, so the "inventory imbalance" alert can
  // deep-link straight to the transfer candidates it promised.
  const [params, setParams] = useSearchParams();
  const action = params.get("action") ?? "";
  const [offset, setOffset] = useState(0);

  const setAction = (next: string) => {
    setOffset(0);
    setParams((current) => {
      const merged = new URLSearchParams(current);
      if (next) merged.set("action", next);
      else merged.delete("action");
      return merged;
    }, { replace: true });
  };

  const feed = useApi(
    () => api.recommendations({ limit: PAGE_SIZE, offset, action: action || undefined }),
    [action, offset],
  );
  const detail = useApi(
    () => (selection ? api.recommendation(selection.storeId, selection.skuUid) : Promise.resolve(null)),
    [selection?.storeId, selection?.skuUid],
  );

  return (
    <div className="flex flex-col gap-5">
      <Loadable state={feed} label="Pricing up every option…">
        {(data) => {
          const acted = data.mix.filter((m) => m.recommended_action !== "no_action");
          const total = data.mix.reduce((sum, m) => sum + m.positions, 0) || 1;
          return (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <Kpi name="net_value" label="Worth acting on" value={money(data.total_net_value)}
                     sub="after paying for the moves"
                     hint="What acting on everything below is worth: the profit kept, less what the transfers and expedited deliveries cost. Profit is counted at margin — stock you never sold also never cost you anything to buy." />
                <Kpi name="no_action_share" label="Leave alone" value={pct(data.no_action_share)}
                     sub="acting would cost more than it saves"
                     hint="Most products need nothing done. A tool that always finds something to do is not really choosing — it just spends your freight budget." />
                {acted.slice(0, 2).map((m) => (
                  <Kpi key={m.recommended_action}
                       label={ACTION_LABELS[m.recommended_action] ?? m.recommended_action}
                       value={num(m.positions)}
                       sub={`${money(m.margin_protected)} of profit kept`} />
                ))}
              </div>

              <ScenarioPanel />

              <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)] gap-5 items-start">
                <Card title="What to do"
                      subtitle={`${num(data.total)} products · looking ${data.horizon} days ahead`}
                      right={
                        <span className="flex items-center gap-2">
                          <select value={action} onChange={(e) => setAction(e.target.value)}
                                  aria-label="Filter by action"
                                  className="rounded-md px-2.5 py-1.5 text-[12px] outline-none cursor-pointer"
                                  style={{ background: "var(--surface-1)",
                                           border: "1px solid var(--border)",
                                           color: "var(--text-primary)" }}>
                            <option value="">All actions</option>
                            {Object.entries(ACTION_LABELS).map(([value, label]) => (
                              <option key={value} value={value}>{label}</option>
                            ))}
                          </select>
                          <DownloadCsv href={exportUrl.prescriptions({ action: action || undefined })} />
                        </span>
                      }>
                  <div className="flex gap-1 mb-4 rounded-full overflow-hidden h-2.5">
                    {data.mix.map((m) => (
                      <div key={m.recommended_action}
                           title={`${ACTION_LABELS[m.recommended_action]}: ${m.positions}`}
                           style={{ width: `${(m.positions / total) * 100}%`,
                                    background: ACTION_COLORS[m.recommended_action] }} />
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mb-4 text-[11px]"
                       style={{ color: "var(--text-muted)" }}>
                    {data.mix.map((m) => (
                      <span key={m.recommended_action} className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-sm"
                              style={{ background: ACTION_COLORS[m.recommended_action] }} />
                        {ACTION_LABELS[m.recommended_action]} · {num(m.positions)}
                      </span>
                    ))}
                  </div>

                  {!data.rows.length ? (
                    <Empty>Nothing here needs acting on right now.</Empty>
                  ) : (
                    <>
                      <Table head={[
                        "Product", "Store",
                        <TermLabel key="action" name="recommended_action" />,
                        <TermLabel key="speed" name="speed" />,
                        <TermLabel key="saved" name="units_saved" />,
                        <TermLabel key="margin" name="margin_protected" label="Profit kept" />,
                        <TermLabel key="net" name="net_value" />,
                      ]}>
                        {data.rows.map((row: Recommendation) => {
                          const active = selection?.storeId === row.store_id &&
                                         selection?.skuUid === row.sku_uid;
                          const select = () =>
                            focus({ storeId: row.store_id, skuUid: row.sku_uid });
                          return (
                            <tr key={`${row.store_id}-${row.sku_uid}`}
                                onClick={select}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault(); select();
                                  }
                                }}
                                tabIndex={0}
                                role="button"
                                aria-pressed={active}
                                aria-label={`${row.sku_uid} at ${row.store_id}`}
                                className="cursor-pointer focus:outline-none focus-visible:ring-2"
                                style={{ background: active ? "var(--surface-3)" : undefined,
                                         borderBottom: "1px solid var(--border)" }}>
                              <td className="py-2 pr-4 font-medium">{row.sku_uid}</td>
                              <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                                {row.store_id}
                              </td>
                              <td className="py-2 pr-4">
                                <span className="inline-flex items-center gap-1.5">
                                  <span className="w-2 h-2 rounded-full"
                                        style={{ background: ACTION_COLORS[row.action] }} />
                                  {/* The server's label, not a client-side map that
                                      can drift away from it. */}
                                  {row.action_label}
                                  {row.donor && (
                                    <span style={{ color: "var(--text-muted)" }}>
                                      from {row.donor}
                                    </span>
                                  )}
                                </span>
                              </td>
                              <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                                {row.speed}
                              </td>
                              {/* Units saved against the units actually at risk —
                                  a bare "3.2 units" says nothing about whether the
                                  lever solves the problem or dents it. */}
                              <td className="py-2 pr-4">
                                {num(row.units_saved, 1)}
                                <span style={{ color: "var(--text-muted)" }}>
                                  {" "}of {num(row.baseline_lost_units, 1)}
                                </span>
                              </td>
                              <td className="py-2 pr-4">{money(row.margin_protected)}</td>
                              <td className="py-2 pr-4">{money(row.net_value)}</td>
                            </tr>
                          );
                        })}
                      </Table>
                      <Pager total={data.total} offset={offset} shown={data.rows.length}
                             onOffset={setOffset} />
                    </>
                  )}
                  <Note>{data.caveat}</Note>
                </Card>

                <div className="xl:sticky xl:top-[96px]">
                  {!selection ? (
                    <Card title="The full story">
                      <Empty>Pick a row on the left to see the reasoning behind it.</Empty>
                    </Card>
                  ) : detail.error ? (
                    <Card title="The full story">
                      <ErrorState message={detail.error} onRetry={detail.refetch} />
                    </Card>
                  ) : !detail.data ? (
                    <Card title="The full story"><Spinner label="Reading the reasoning…" /></Card>
                  ) : (
                    <Card title="The full story"
                          subtitle={`${detail.data.sku_uid} at ${detail.data.store_id}`}>
                      <div className="grid grid-cols-3 gap-2 mb-4">
                        <Fact name="units_saved" label="Saves" value={num(detail.data.units_saved, 1)} />
                        <Fact name="margin_protected" label="Profit kept"
                              value={money(detail.data.margin_protected)} />
                        <Fact name="net_value" label="Net value"
                              value={money(detail.data.net_value)} />
                      </div>
                      <Story label="Problem" text={detail.data.problem} />
                      <Story label="Evidence" text={detail.data.evidence} />
                      <Story label="Recommended action" text={detail.data.action_text}
                             accent={ACTION_COLORS[detail.data.recommended]} />
                      <Story label="Expected impact" text={detail.data.impact} />

                      <div className="mt-5 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
                        <p className="text-[11px] uppercase tracking-wider mb-2"
                           style={{ color: "var(--text-muted)" }}>
                          The other options we checked
                        </p>
                        <div className="flex flex-col gap-1.5">
                          {detail.data.options.map((option) => (
                            <div key={option.action}
                                 className="flex items-center justify-between text-[12px] rounded-md px-2.5 py-2"
                                 style={{ background: option.chosen ? "var(--surface-3)" : "transparent",
                                          border: option.chosen
                                            ? `1px solid ${ACTION_COLORS[option.action]}`
                                            : "1px solid transparent" }}>
                              <span className="flex items-center gap-2">
                                <span className="w-2 h-2 rounded-full"
                                      style={{ background: option.feasible
                                        ? ACTION_COLORS[option.action] : "var(--text-muted)" }} />
                                <span style={{ color: option.feasible
                                  ? "var(--text-primary)" : "var(--text-muted)" }}>
                                  {option.label}
                                </span>
                                <span style={{ color: "var(--text-muted)" }}>{option.speed}</span>
                              </span>
                              <span className="tnum" style={{ color: "var(--text-secondary)" }}>
                                {option.feasible ? money(option.net_value) : "not available"}
                              </span>
                            </div>
                          ))}
                        </div>
                        <Note>
                          The options we turned down are shown on purpose. A
                          recommendation you cannot argue with is not a
                          recommendation — it is an instruction.
                        </Note>
                      </div>

                      <button onClick={() => focus(selection, "simulate")}
                              className="mt-4 w-full rounded-md py-2 text-[13px] font-medium"
                              style={{ border: "1px solid var(--border)",
                                       color: "var(--text-primary)" }}>
                        ← Back to the simulation
                      </button>
                    </Card>
                  )}
                </div>
              </div>
            </>
          );
        }}
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
    <div className="rounded-md px-2.5 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        <TermLabel name={name} label={label} />
      </p>
      <p className="text-[14px] font-medium tnum">{value}</p>
    </div>
  );
}

function Story({ label, text, accent }: { label: string; text: string; accent?: string }) {
  return (
    <div className="mb-3.5">
      <p className="text-[10px] uppercase tracking-wider mb-1 font-semibold"
         style={{ color: accent ?? "var(--text-muted)" }}>
        {label}
      </p>
      <p className="text-[13px] leading-relaxed">{text}</p>
    </div>
  );
}
