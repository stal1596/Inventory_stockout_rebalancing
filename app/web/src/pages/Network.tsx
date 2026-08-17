import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { money, num, pct } from "../lib/format";
import { api } from "../lib/api";
import { Card, ErrorState, Note, Spinner, Table, TermLabel } from "../components/ui";
import { useApi } from "../lib/useApi";

/** The config's own vocabulary, which was reaching the screen as `same_zone`. */
const SCOPE_WORDS: Record<string, string> = {
  same_zone: "Within the same zone",
  same_dc: "Between stores sharing a warehouse",
  same_city: "Within the same city",
  any: "Anywhere in the network",
};

/**
 * Supplier → DC → store, drawn from config/network.yaml rather than hard-coded,
 * so changing the network is a YAML edit and this view follows.
 *
 * A node's colour carries risk (status palette, always with a number beside it);
 * an edge's presence carries the serving relationship. No decorative geometry.
 */
export function Network() {
  const state = useApi(() => api.topology(), []);

  // The supplier-reliability alert deep-links here as `?vendor=<name>`. Nothing
  // read it, so "X is delivering late" opened an undifferentiated topology and
  // left the user to find X by eye — the link carried an argument that did
  // nothing. The alert sends the vendor NAME; ids are matched too so either form
  // of the link resolves.
  const [params] = useSearchParams();
  const wanted = params.get("vendor");
  const marked = useRef<HTMLDivElement>(null);
  const loaded = Boolean(state.data);
  useEffect(() => {
    if (wanted && loaded) marked.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [wanted, loaded]);

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
            {vendors.map((vendor: any) => {
              const flagged = Boolean(wanted) &&
                (vendor.name === wanted || vendor.id === wanted);
              return (
                <Node key={vendor.id} title={vendor.name}
                      highlight={flagged}
                      nodeRef={flagged ? marked : undefined}
                      lines={[
                        `${vendor.lead_time_days}d lead ± ${vendor.lead_time_sigma}`,
                        vendor.on_time_rate !== null && vendor.on_time_rate !== undefined
                          ? `${pct(vendor.on_time_rate)} on time`
                          : "on-time not measurable",
                      ]}
                      tone={vendor.on_time_rate !== null && vendor.on_time_rate < 0.8
                        ? "var(--status-serious)" : "var(--series-2)"} />
              );
            })}
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
        {/* The server's sentence is the precise one and stays; it just needed
            something in front of it saying why anyone should care. */}
        <Note>
          None of this shape was assumed — it was worked out from the stock
          records themselves, which is the check that the map above matches how
          goods actually move.{" "}
          <span style={{ color: "var(--text-secondary)" }}>{topology.recovered}</span>
        </Note>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Warehouses"
              subtitle="Which stores each one serves, and how well it serves them">
          <Table head={[
            "Warehouse", "Zones", "Stores",
            <TermLabel key="fill" name="fill_rate" label="Orders filled" />,
            "Days to deliver",
          ]}>
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
            Every store is served by exactly one warehouse. A zone split between
            two is rejected outright, because then nobody can say where a store's
            stock is really coming from.
          </Note>
        </Card>

        <Card title="Rules for moving stock between stores"
              subtitle="The limits every transfer recommendation has to respect">
          <div className="flex flex-col gap-2 text-[13px]">
            <Row label="Transfers allowed" value={topology.transfers?.enabled ? "Yes" : "No"} />
            <Row label="How far stock can move"
                 value={SCOPE_WORDS[String(topology.transfers?.scope)]
                        ?? String(topology.transfers?.scope ?? "—")} />
            <Row label="Days in transit"
                 value={(topology.transfers?.lead_days ?? []).join("–") || "—"} />
            <Row label="Cost per unit moved" value={money(topology.transfers?.cost_per_unit)} />
            <Row label="Sending store must keep"
                 value={`${topology.transfers?.min_donor_cover_days ?? "—"} days of stock`} />
          </div>
          <Note>
            That last rule matters most. Without it a transfer just moves the
            shortage to the store that helped out — no better off overall, but it
            would still look like a saving on this screen.
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

function Node({ title, lines, tone, meter, meterLabel, to, highlight, nodeRef }: {
  title: string; lines: string[]; tone: string;
  meter?: number; meterLabel?: string; to?: string;
  /** The node the alert feed pointed at. Ringed so the drill-through lands somewhere. */
  highlight?: boolean;
  nodeRef?: React.Ref<HTMLDivElement>;
}) {
  const surface = {
    background: highlight ? "var(--surface-2)" : "var(--surface-3)",
    borderLeft: `3px solid ${tone}`,
    outline: highlight ? `1px solid ${tone}` : undefined,
  };
  const Wrapper = to
    ? ({ children }: { children: React.ReactNode }) => (
        <Link to={to} className="block rounded-md px-2.5 py-2 transition-colors hover:brightness-125"
              style={surface}>
          {children}
        </Link>
      )
    : ({ children }: { children: React.ReactNode }) => (
        <div ref={nodeRef} className="rounded-md px-2.5 py-2 scroll-mt-6" style={surface}>
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
