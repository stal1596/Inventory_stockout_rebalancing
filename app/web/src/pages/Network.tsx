import { Link } from "react-router-dom";
import { money, num, pct } from "../lib/format";
import { api } from "../lib/api";
import { Card, ErrorState, Note, Spinner, Table } from "../components/ui";
import { useApi } from "../lib/useApi";

/**
 * Supplier → DC → store, drawn from config/network.yaml rather than hard-coded,
 * so changing the network is a YAML edit and this view follows.
 *
 * A node's colour carries risk (status palette, always with a number beside it);
 * an edge's presence carries the serving relationship. No decorative geometry.
 */
export function Network() {
  const state = useApi(() => api.topology(), []);

  if (state.error) return <ErrorState message={state.error} onRetry={state.refetch} />;
  if (!state.data) return <Spinner label="Resolving the network…" />;

  const topology = state.data;
  const { vendors, dcs, stores } = topology;
  // reduce, not Math.max(...spread): a full extract has thousands of stores and
  // spreading them as arguments is an engine limit waiting to be hit.
  const maxExposure = stores.reduce((most, s) => Math.max(most, s.exposure), 1);

  return (
    <div className="flex flex-col gap-5">
      <Card title="Network topology"
            subtitle={`${vendors.length} vendors · ${dcs.length} distribution centres · ${stores.length} stores`}>
        <div className="grid grid-cols-[1fr_auto_1fr_auto_1.4fr] gap-3 items-start">
          <Column title="Vendors">
            {vendors.map((vendor: any) => (
              <Node key={vendor.id} title={vendor.name}
                    lines={[
                      `${vendor.lead_time_days}d lead ± ${vendor.lead_time_sigma}`,
                      vendor.on_time_rate !== null && vendor.on_time_rate !== undefined
                        ? `${pct(vendor.on_time_rate)} on time`
                        : "on-time not measurable",
                    ]}
                    tone={vendor.on_time_rate !== null && vendor.on_time_rate < 0.8
                      ? "var(--status-serious)" : "var(--series-2)"} />
            ))}
          </Column>

          <Arrow label="ships to" />

          <Column title="Distribution centres">
            {dcs.map((dc: any) => (
              <Node key={dc.id} title={dc.name ?? dc.id}
                    lines={[
                      `${dc.stores.length} stores · ${dc.zones.join(", ")}`,
                      `fill ${pct(dc.fill_rate)} · ${dc.lead_days[0]}–${dc.lead_days[1]}d`,
                    ]}
                    tone="var(--series-1)" />
            ))}
          </Column>

          <Arrow label="replenishes" />

          <Column title="Stores">
            <div className="grid grid-cols-2 gap-2">
              {stores.map((store) => (
                // A node carrying a store id and an at-risk count that cannot be
                // opened is a dead end. Each one now filters the risk table.
                <Node key={store.id} title={store.id}
                      to={`/risk?at=${encodeURIComponent(store.id)}`}
                      lines={[
                        `${store.city} · ${store.dc ?? "—"}`,
                        `${store.at_risk} of ${store.positions} at risk`,
                      ]}
                      tone={store.at_risk / Math.max(store.positions, 1) > 0.4
                        ? "var(--status-critical)" : "var(--series-3)"}
                      meter={store.exposure / maxExposure}
                      meterLabel={money(store.exposure)} />
              ))}
            </div>
          </Column>
        </div>
        <Note>
          Recovered from the data, not assumed: {topology.recovered}
        </Note>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Distribution centres" subtitle="Configured in config/network.yaml">
          <Table head={["DC", "Zones", "Stores", "Fill rate", "Lead days"]}>
            {dcs.map((dc: any) => (
              <tr key={dc.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td className="py-2 pr-4 font-medium">{dc.id}</td>
                <td className="py-2 pr-4" style={{ color: "var(--text-secondary)" }}>
                  {dc.zones.join(", ")}
                </td>
                <td className="py-2 pr-4">{dc.stores.length}</td>
                <td className="py-2 pr-4">{pct(dc.fill_rate)}</td>
                <td className="py-2 pr-4">{dc.lead_days[0]}–{dc.lead_days[1]}</td>
              </tr>
            ))}
          </Table>
          <Note>
            A zone served by two DCs is refused when the config loads: an
            ambiguous store→DC mapping is exactly the condition the supplied
            extract cannot resolve.
          </Note>
        </Card>

        <Card title="Transfer policy" subtitle="What rebalancing is allowed to do">
          <div className="flex flex-col gap-2 text-[13px]">
            <Row label="Enabled" value={topology.transfers?.enabled ? "Yes" : "No"} />
            <Row label="Scope" value={String(topology.transfers?.scope ?? "—")} />
            <Row label="Lead days"
                 value={(topology.transfers?.lead_days ?? []).join("–") || "—"} />
            <Row label="Cost per unit" value={money(topology.transfers?.cost_per_unit)} />
            <Row label="Donor must retain"
                 value={`${topology.transfers?.min_donor_cover_days ?? "—"} days of cover`} />
          </div>
          <Note>
            The donor floor is the constraint that stops rebalancing simply moving
            a stockout to the store that helped — which would net to zero while
            looking like a saving.
          </Note>
        </Card>
      </div>
    </div>
  );
}

function Column({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider mb-2 font-semibold"
         style={{ color: "var(--text-muted)" }}>
        {title}
      </p>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function Node({ title, lines, tone, meter, meterLabel, to }: {
  title: string; lines: string[]; tone: string;
  meter?: number; meterLabel?: string; to?: string;
}) {
  const Wrapper = to
    ? ({ children }: { children: React.ReactNode }) => (
        <Link to={to} className="block rounded-md px-2.5 py-2 transition-colors hover:brightness-125"
              style={{ background: "var(--surface-3)", borderLeft: `3px solid ${tone}` }}>
          {children}
        </Link>
      )
    : ({ children }: { children: React.ReactNode }) => (
        <div className="rounded-md px-2.5 py-2"
             style={{ background: "var(--surface-3)", borderLeft: `3px solid ${tone}` }}>
          {children}
        </div>
      );

  return (
    <Wrapper>
      <p className="text-[12px] font-medium truncate" title={title}>{title}</p>
      {lines.map((line, index) => (
        <p key={index} className="text-[10.5px] leading-snug" style={{ color: "var(--text-muted)" }}>
          {line}
        </p>
      ))}
      {meter !== undefined && (
        <div className="mt-1.5">
          <div className="h-1 rounded-full" style={{ background: "var(--surface-1)" }}>
            <div className="h-1 rounded-full"
                 style={{ width: `${Math.max(meter * 100, 2)}%`, background: tone }} />
          </div>
          <p className="text-[10px] mt-0.5 tnum" style={{ color: "var(--text-muted)" }}>
            {meterLabel}
          </p>
        </div>
      )}
    </Wrapper>
  );
}

function Arrow({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full pt-6 px-1">
      <span className="text-[10px] mb-1" style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ color: "var(--axis)" }}>→</span>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span className="tnum">{value}</span>
    </div>
  );
}
