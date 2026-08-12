import { useState } from "react";
import { api, type ScenarioFeed } from "../lib/api";
import { ACTION_COLORS, ACTION_LABELS, money, num, pct } from "../lib/format";
import { Card, ErrorState, Note, Spinner } from "./ui";
import { useApi } from "../lib/useApi";

/**
 * "What if freight were five times dearer?"
 *
 * This cannot be answered by scaling the standing recommendations, because the
 * choice between levers is an argmax: a cost change can flip WHICH lever wins,
 * not merely shrink the margin on the one that already did. So the engine is
 * re-run, and the comparison arm is the standing recommendation for the SAME
 * positions — never a fresh run at default parameters, which would let
 * simulation noise masquerade as the effect of the change.
 *
 * The run is deliberate rather than live: it re-values every lever over the
 * whole population and takes about five seconds cold, cached per parameter set
 * thereafter.
 */
const DEFAULTS = { horizon: 14, margin: 0.4, freight: 1 };

export function ScenarioPanel() {
  const [horizon, setHorizon] = useState(DEFAULTS.horizon);
  const [margin, setMargin] = useState(DEFAULTS.margin);
  const [freight, setFreight] = useState(DEFAULTS.freight);
  const [applied, setApplied] = useState<null | typeof DEFAULTS>(null);

  const scenario = useApi<ScenarioFeed | null>(
    () =>
      applied
        ? api.prescribeScenario({
            horizon: applied.horizon,
            margin_rate: applied.margin,
            // Multipliers on the engine's own defaults, so the control reads as
            // "5x freight" rather than asking a planner to know that a DC
            // expedite costs 90 a unit.
            ...(applied.freight === 1 ? {} : {
              rebalance_cost: 40 * applied.freight,
              expedite_dc_cost: 90 * applied.freight,
              expedite_supplier_cost: 220 * applied.freight,
            }),
            limit: 200,
          })
        : Promise.resolve(null),
    [applied?.horizon, applied?.margin, applied?.freight],
  );

  const dirty = applied === null
    || applied.horizon !== horizon || applied.margin !== margin || applied.freight !== freight;

  return (
    <Card title="What if the assumptions were different?"
          subtitle="Re-values every lever, then compares against the standing list for the same positions">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Knob label="Horizon" value={`${horizon} days`}>
          <input type="range" min={7} max={60} step={7} value={horizon}
                 onChange={(e) => setHorizon(Number(e.target.value))} className="w-full" />
        </Knob>
        <Knob label="Margin rate" value={pct(margin)}>
          <input type="range" min={0.05} max={0.9} step={0.05} value={margin}
                 onChange={(e) => setMargin(Number(e.target.value))} className="w-full" />
        </Knob>
        <Knob label="Freight cost" value={`${freight}×`}>
          <input type="range" min={0.5} max={8} step={0.5} value={freight}
                 onChange={(e) => setFreight(Number(e.target.value))} className="w-full" />
        </Knob>
      </div>

      <div className="flex items-center gap-3 mt-4">
        <button onClick={() => setApplied({ horizon, margin, freight })}
                disabled={!dirty || scenario.loading}
                className="rounded-md px-3 py-1.5 text-[13px] font-medium disabled:opacity-40"
                style={{ background: "var(--series-1)", color: "#fff" }}>
          {scenario.loading ? "Re-valuing…" : "Run scenario"}
        </button>
        {applied && (
          <button onClick={() => {
                    setHorizon(DEFAULTS.horizon); setMargin(DEFAULTS.margin);
                    setFreight(DEFAULTS.freight); setApplied(null);
                  }}
                  className="text-[12px] underline underline-offset-2"
                  style={{ color: "var(--text-muted)" }}>
            reset to the measured assumptions
          </button>
        )}
        <span className="ml-auto text-[11px]" style={{ color: "var(--text-muted)" }}>
          Runs over the whole population — a few seconds the first time.
        </span>
      </div>

      {scenario.error && (
        <ErrorState message={scenario.error} onRetry={scenario.refetch} />
      )}
      {scenario.loading && !scenario.data && <Spinner label="Re-valuing every lever…" />}

      {scenario.data && !scenario.error && (
        <div className="mt-5 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Compare label="Leave alone"
                     baseline={pct(scenario.data.delta_vs_default.no_action_share_default ?? 0)}
                     scenario={pct(scenario.data.no_action_share)} />
            <Compare label="Net value of acting"
                     baseline={money(scenario.data.delta_vs_default.net_value_default ?? 0)}
                     scenario={money(scenario.data.total_net_value)} />
            <Compare label="Positions valued"
                     baseline={num(scenario.data.positions)}
                     scenario={num(scenario.data.positions)} />
            <Compare label="Horizon"
                     baseline={`${scenario.data.defaults.horizon}d`}
                     scenario={`${scenario.data.horizon}d`} />
          </div>

          <div className="flex gap-1 mt-4 rounded-full overflow-hidden h-2.5">
            {scenario.data.mix.map((m) => (
              <div key={m.recommended_action}
                   title={`${ACTION_LABELS[m.recommended_action]}: ${m.positions}`}
                   style={{ width: `${(m.positions / Math.max(scenario.data!.total, 1)) * 100}%`,
                            background: ACTION_COLORS[m.recommended_action] }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px]"
               style={{ color: "var(--text-muted)" }}>
            {scenario.data.mix.map((m) => (
              <span key={m.recommended_action} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm"
                      style={{ background: ACTION_COLORS[m.recommended_action] }} />
                {ACTION_LABELS[m.recommended_action]} · {num(m.positions)}
              </span>
            ))}
          </div>

          <Note>{scenario.data.delta_vs_default.note}</Note>
        </div>
      )}
    </Card>
  );
}

function Knob({ label, value, children }: {
  label: string; value: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[11px] uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}>
          {label}
        </span>
        <span className="text-[13px] tnum font-medium">{value}</span>
      </div>
      {children}
    </div>
  );
}

function Compare({ label, baseline, scenario }: {
  label: string; baseline: string; scenario: string;
}) {
  const moved = baseline !== scenario;
  return (
    <div className="rounded-md px-3 py-2" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p className="text-[16px] font-semibold tnum"
         style={{ color: moved ? "var(--series-2)" : "var(--text-primary)" }}>
        {scenario}
      </p>
      <p className="text-[11px] tnum" style={{ color: "var(--text-muted)" }}>
        standing: {baseline}
      </p>
    </div>
  );
}
