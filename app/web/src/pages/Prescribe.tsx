import { useEffect, useState } from "react";
import { api, type Recommendation, type RecommendationDetail } from "../lib/api";
import { ACTION_COLORS, ACTION_LABELS, money, num, pct } from "../lib/format";
import { Card, Empty, Kpi, Note, Spinner, Table } from "../components/ui";
import { useStore } from "../store";

export function Prescribe() {
  const { selection, focus } = useStore();
  const [feed, setFeed] = useState<any>(null);
  const [detail, setDetail] = useState<RecommendationDetail | null>(null);
  const [action, setAction] = useState<string>("");

  useEffect(() => {
    api.recommendations({ limit: 120, action: action || undefined })
      .then(setFeed).catch(() => setFeed(null));
  }, [action]);

  useEffect(() => {
    if (!selection) { setDetail(null); return; }
    api.recommendation(selection.storeId, selection.skuUid)
      .then(setDetail).catch(() => setDetail(null));
  }, [selection]);

  if (!feed) return <Spinner label="Valuing every lever…" />;

  const mix = feed.mix as { recommended_action: string; positions: number; net_value: number }[];
  const total = mix.reduce((sum, m) => sum + m.positions, 0);

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Net value of acting" value={money(feed.total_net_value)}
             sub="margin protected less freight" />
        <Kpi label="Leave alone" value={pct(feed.no_action_share)}
             sub="every lever costs more than it saves"
             hint="An engine that always acts is not discriminating." />
        {mix.filter((m) => m.recommended_action !== "no_action").slice(0, 2).map((m) => (
          <Kpi key={m.recommended_action}
               label={ACTION_LABELS[m.recommended_action] ?? m.recommended_action}
               value={num(m.positions)}
               tone={ACTION_COLORS[m.recommended_action]}
               sub={`${money(m.net_value)} net value`} />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)] gap-5 items-start">
        <Card title="Recommended actions"
              subtitle="Each lever is valued by re-simulating the position with it applied"
              right={
                <select value={action} onChange={(e) => setAction(e.target.value)}
                        className="rounded-md px-2.5 py-1.5 text-[12px] outline-none cursor-pointer"
                        style={{ background: "var(--surface-1)", border: "1px solid var(--border)",
                                 color: "var(--text-primary)" }}>
                  <option value="">All actions</option>
                  {Object.entries(ACTION_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              }>
          <div className="flex gap-1 mb-4 rounded-full overflow-hidden h-2.5">
            {mix.map((m) => (
              <div key={m.recommended_action}
                   title={`${ACTION_LABELS[m.recommended_action]}: ${m.positions}`}
                   style={{ width: `${(m.positions / total) * 100}%`,
                            background: ACTION_COLORS[m.recommended_action] }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mb-4 text-[11px]"
               style={{ color: "var(--text-muted)" }}>
            {mix.map((m) => (
              <span key={m.recommended_action} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm"
                      style={{ background: ACTION_COLORS[m.recommended_action] }} />
                {ACTION_LABELS[m.recommended_action]} · {num(m.positions)}
              </span>
            ))}
          </div>

          {!feed.rows.length ? <Empty>Nothing to act on.</Empty> : (
            <Table head={["SKU", "Store", "Action", "Speed", "Units", "Net value"]}>
              {feed.rows.map((row: Recommendation) => {
                const active = selection?.storeId === row.store_id &&
                               selection?.skuUid === row.sku_uid;
                return (
                  <tr key={`${row.store_id}-${row.sku_uid}`}
                      onClick={() => focus({ storeId: row.store_id, skuUid: row.sku_uid })}
                      className="cursor-pointer"
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
                        {ACTION_LABELS[row.action] ?? row.action}
                        {row.donor && (
                          <span style={{ color: "var(--text-muted)" }}>from {row.donor}</span>
                        )}
                      </span>
                    </td>
                    <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                      {row.speed}
                    </td>
                    <td className="py-2 pr-4">{num(row.units_saved, 1)}</td>
                    <td className="py-2 pr-4">{money(row.net_value)}</td>
                  </tr>
                );
              })}
            </Table>
          )}
          <Note>{feed.caveat}</Note>
        </Card>

        <div className="xl:sticky xl:top-[76px]">
          {!selection ? (
            <Card title="Recommendation">
              <Empty>Select a row to see the full reasoning.</Empty>
            </Card>
          ) : !detail ? (
            <Card title="Recommendation"><Spinner /></Card>
          ) : (
            <Card title="Recommendation" subtitle={`${detail.sku_uid} at ${detail.store_id}`}>
              <Story label="Problem" text={detail.problem} />
              <Story label="Evidence" text={detail.evidence} />
              <Story label="Recommended action" text={detail.action}
                     accent={ACTION_COLORS[detail.recommended]} />
              <Story label="Expected impact" text={detail.impact} />

              <div className="mt-5 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
                <p className="text-[11px] uppercase tracking-wider mb-2"
                   style={{ color: "var(--text-muted)" }}>
                  Every lever considered
                </p>
                <div className="flex flex-col gap-1.5">
                  {detail.options.map((option) => (
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
                  Showing the rejected options is deliberate: a recommendation
                  without its alternatives is an oracle, not a decision.
                </Note>
              </div>
            </Card>
          )}
        </div>
      </div>
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
