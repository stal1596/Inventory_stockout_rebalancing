import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Label, LabelList, Line,
  ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
  ZAxis,
} from "recharts";
import { ChartBox, TipShell } from "./charts";
import type { CalibrationBin, Coefficients, KmBias } from "../lib/api";
import { days, featureLabel, num, pct } from "../lib/format";

/**
 * Charts for the model-evidence and backtest pages.
 *
 * Colour assignments here were validated with the dataviz skill's checker rather
 * than chosen, and two results changed the design:
 *
 * - `--series-1` against `--series-2` passes every check in both modes (worst
 *   CVD deltaE 24.7, normal-vision 33.6), so the bias curves use that pair.
 * - The TIGHT sequential ramp (seq-550/400/250) fails the normal-vision floor at
 *   deltaE 14.4 — two adjacent segments a full-colour reader cannot separate.
 *   The WIDE ramp (seq-550/250/100) passes at 15.2, so the coverage bar uses
 *   that, and pays the contrast obligation its pale end incurs with direct
 *   labels plus the table beside it.
 */

const AXIS = { fontSize: 11, fill: "var(--text-muted)" };
const GRID = "var(--grid)";

/* ------------------------------------------------------------------ */
/* Calibration reliability                                             */
/* ------------------------------------------------------------------ */

/**
 * Predicted against observed, with the y=x line the model should sit on.
 *
 * One series, so no legend box — the title names it. The diagonal is a
 * reference, not a series, so it wears the axis token rather than a hue. Point
 * area carries bin size, because a bin holding 12 spells and one holding 900
 * should not argue with equal weight.
 */
export function CalibrationPlot({ bins, height = 280 }: {
  bins: CalibrationBin[]; height?: number;
}) {
  return (
    <ChartBox>
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 12, right: 20, bottom: 20, left: -6 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="predicted_mean" domain={[0, 1]}
                 tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }}
                 tickFormatter={(v) => pct(v)}>
            <Label value="predicted" position="insideBottom" offset={-12}
                   style={{ fontSize: 11, fill: "var(--text-muted)" }} />
          </XAxis>
          <YAxis type="number" dataKey="observed_km" domain={[0, 1]} width={54}
                 tick={AXIS} tickLine={false} axisLine={false}
                 tickFormatter={(v) => pct(v)}>
            <Label value="observed" angle={-90} position="insideLeft"
                   style={{ fontSize: 11, fill: "var(--text-muted)", textAnchor: "middle" }} />
          </YAxis>
          <ZAxis dataKey="n" range={[60, 300]} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                         stroke="var(--axis)" strokeDasharray="4 4" />
          <Tooltip cursor={{ stroke: "var(--axis)" }}
                   content={({ active, payload }) => {
                     const row = payload?.[0]?.payload as CalibrationBin | undefined;
                     return active && row ? (
                       <TipShell title={`Bin ${row.bin + 1}`}
                                 rows={[
                                   ["Predicted", pct(row.predicted_mean, 1), "var(--series-1)"],
                                   ["Observed (KM)", pct(row.observed_km, 1)],
                                   ["Gap", pct(row.gap, 1)],
                                   ["Spells", num(row.n)],
                                 ]} />
                     ) : null;
                   }} />
          <Scatter data={bins} fill="var(--series-1)" fillOpacity={0.75}
                   stroke="var(--surface-1)" strokeWidth={2} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

/* ------------------------------------------------------------------ */
/* Kaplan-Meier bias                                                   */
/* ------------------------------------------------------------------ */

type BiasCurve = Extract<KmBias, { available: true }>["curve"];

/**
 * Naive KM against the counterfactual truth, with the gap between them shaded.
 *
 * The shaded band IS the finding — the area between the two curves is the
 * survival the naive estimate claims and the world does not deliver. Drawn with
 * the same `[low, high]` tuple trick `FanChart` uses.
 */
export function KmBiasCurves({ curve, gapAt, height = 280 }: {
  curve: BiasCurve; gapAt?: number; height?: number;
}) {
  // The API column is literally named `true`. Remap once, here, so no
  // `dataKey="true"` ever reaches Recharts or a reader.
  const data = curve.map((point) => ({
    t: point.t,
    naive: point.naive,
    truth: point["true"],
    band: [point["true"], point.naive] as [number, number],
  }));

  return (
    <ChartBox>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: -10 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="t" tick={AXIS} tickLine={false}
                 axisLine={{ stroke: "var(--axis)" }} minTickGap={32}>
            <Label value="days since the spell opened" position="insideBottom" offset={-10}
                   style={{ fontSize: 11, fill: "var(--text-muted)" }} />
          </XAxis>
          <YAxis domain={[0, 1]} width={54} tick={AXIS} tickLine={false} axisLine={false}
                 tickFormatter={(v) => pct(v)} />
          <Tooltip cursor={{ stroke: "var(--axis)" }}
                   content={({ active, payload, label }) => {
                     const row = payload?.[0]?.payload;
                     return active && row ? (
                       <TipShell title={`Day ${label}`}
                                 rows={[
                                   ["Naive KM", pct(row.naive, 1), "var(--series-2)"],
                                   ["True (counterfactual)", pct(row.truth, 1), "var(--series-1)"],
                                   ["Overstated by", pct(row.naive - row.truth, 1)],
                                 ]} />
                     ) : null;
                   }} />
          <Area dataKey="band" stroke="none" fill="var(--series-2)" fillOpacity={0.16}
                isAnimationActive={false} />
          <Line type="monotone" dataKey="truth" stroke="var(--series-1)" strokeWidth={2}
                dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="naive" stroke="var(--series-2)" strokeWidth={2}
                dot={false} isAnimationActive={false} />
          <ReferenceLine y={0.5} stroke="var(--axis)" strokeDasharray="4 4" />
          {gapAt !== undefined && (
            <ReferenceLine x={gapAt} stroke="var(--axis)" strokeDasharray="4 4" />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

/* ------------------------------------------------------------------ */
/* AFT coefficients                                                    */
/* ------------------------------------------------------------------ */

/**
 * Diverging on a real zero: a feature either buys the position time or costs it
 * time. Same encoding as `DriverWaterfall` — blue buys, red costs — because a
 * user meeting both charts in one product must not have to relearn the polarity.
 * The words "buys time" / "costs time" ship in the legend, so colour never
 * carries the meaning alone.
 */
export function CoefficientBars({ rows, limit = 16, actionableOnly = false }: {
  rows: Coefficients["coefficients"]; limit?: number; actionableOnly?: boolean;
}) {
  const data = rows
    .filter((row) => row.coefficient !== null)
    .filter((row) => (actionableOnly ? row.actionable : true))
    .sort((a, b) => Math.abs(b.coefficient!) - Math.abs(a.coefficient!))
    .slice(0, limit)
    .map((row) => ({ ...row, label: featureLabel(row.feature) }));

  if (!data.length) return null;

  return (
    <>
      <ChartBox>
        <ResponsiveContainer width="100%" height={data.length * 26 + 40}>
          <BarChart data={data} layout="vertical"
                    margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" tick={AXIS} tickLine={false}
                   axisLine={{ stroke: "var(--axis)" }} />
            <YAxis type="category" dataKey="label" width={160} tick={AXIS}
                   tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: "var(--surface-3)" }}
                     content={({ active, payload }) => {
                       const row = payload?.[0]?.payload;
                       return active && row ? (
                         <TipShell title={row.label}
                                   rows={[
                                     ["Coefficient", num(row.coefficient, 4)],
                                     ["Effect", row.coefficient > 0 ? "buys time" : "costs time"],
                                     ["Group", row.group],
                                     ["Actionable", row.actionable ? "yes" : "no lever"],
                                   ]} />
                       ) : null;
                     }} />
            <ReferenceLine x={0} stroke="var(--axis)" />
            <Bar dataKey="coefficient" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {data.map((row) => (
                <Cell key={row.feature}
                      fill={row.coefficient! > 0 ? "var(--series-1)" : "var(--status-critical)"}
                      // Non-actionable features are dimmed, not recoloured:
                      // colour is already spent carrying polarity here.
                      fillOpacity={row.actionable ? 1 : 0.45} />
              ))}
              <LabelList dataKey="coefficient" position="right"
                         formatter={(v: number) => num(v, 3)}
                         style={{ fontSize: 11, fill: "var(--text-secondary)" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartBox>
      <div className="flex flex-wrap items-center gap-4 mt-2 text-[11px]"
           style={{ color: "var(--text-muted)" }}>
        <Swatch color="var(--series-1)" label="buys time (survives longer)" />
        <Swatch color="var(--status-critical)" label="costs time" />
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm"
                style={{ background: "var(--series-1)", opacity: 0.45 }} />
          dimmed — no lever behind it
        </span>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Backtest interval coverage                                          */
/* ------------------------------------------------------------------ */

/**
 * Where reality fell against the simulated interval: earlier than P10, inside
 * P10-P90, or later than P90.
 *
 * Three ordered positions on one axis (early / inside / late), so this is
 * magnitude order and takes a sequential ramp rather than categorical hues. The
 * WIDE ramp is used deliberately — the tighter one failed the normal-vision
 * separation floor at deltaE 14.4, which would have left two adjacent segments
 * indistinguishable to a full-colour reader. Its pale end sits under 3:1 on the
 * light surface, so every segment carries a direct label and the page shows the
 * numbers in a table beside it.
 *
 * Exceeding the 10% target is signalled in the KPI text, never by recolouring a
 * segment: status colours are reserved.
 */
export function TailCoverageBar({ below, inside, above, expected, height = 108 }: {
  below: number; inside: number; above: number;
  expected: { breach_below_p10: number; breach_above_p90: number };
  height?: number;
}) {
  const data = [{ name: "coverage", below, inside, above }];
  const segment = (key: "below" | "inside" | "above", color: string, label: string) => (
    <Bar dataKey={key} stackId="a" fill={color} isAnimationActive={false}
         // 2px of surface between segments, so adjacent fills never touch.
         stroke="var(--surface-1)" strokeWidth={2}>
      <LabelList dataKey={key} position="center"
                 formatter={(v: number) => (v > 0.06 ? `${label} ${pct(v)}` : "")}
                 style={{ fontSize: 11, fill: "var(--surface-1)", fontWeight: 600 }} />
    </Bar>
  );

  return (
    <ChartBox>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 12, bottom: 24, left: 8 }}>
          <XAxis type="number" domain={[0, 1]} tick={AXIS} tickLine={false}
                 axisLine={{ stroke: "var(--axis)" }} tickFormatter={(v) => pct(v)} />
          <YAxis type="category" dataKey="name" hide />
          <Tooltip cursor={{ fill: "transparent" }}
                   content={({ active }) =>
                     active ? (
                       <TipShell title="Where reality fell"
                                 rows={[
                                   ["Earlier than P10", pct(below, 1), "var(--seq-550)"],
                                   ["Inside P10–P90", pct(inside, 1), "var(--seq-250)"],
                                   ["Later than P90", pct(above, 1), "var(--seq-100)"],
                                 ]} />
                     ) : null } />
          {segment("below", "var(--seq-550)", "early")}
          {segment("inside", "var(--seq-250)", "covered")}
          {segment("above", "var(--seq-100)", "late")}
          {/* Where a perfectly calibrated 10/80/10 would land. */}
          <ReferenceLine x={expected.breach_below_p10} stroke="var(--axis)"
                         strokeDasharray="4 4" />
          <ReferenceLine x={1 - expected.breach_above_p90} stroke="var(--axis)"
                         strokeDasharray="4 4" />
        </BarChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

/**
 * Realised stockout rate among positions acted on against those left alone.
 *
 * Both bars are the SAME measure split by a binary group, so both take one hue
 * and position carries the grouping — a second colour would imply a second
 * measure. The base rate is a reference line, not a third bar.
 */
export function DiscriminationBars({ acted, notActed, baseRate, height = 200 }: {
  acted: number; notActed: number | null; baseRate: number; height?: number;
}) {
  const data = [
    { group: "Acted on", rate: acted },
    ...(notActed === null ? [] : [{ group: "Left alone", rate: notActed }]),
  ];

  return (
    <>
      <ChartBox>
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} margin={{ top: 16, right: 12, bottom: 4, left: -12 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="group" tick={AXIS} tickLine={false}
                   axisLine={{ stroke: "var(--axis)" }} />
            <YAxis domain={[0, 1]} width={50} tick={AXIS} tickLine={false} axisLine={false}
                   tickFormatter={(v) => pct(v)} />
            <Tooltip cursor={{ fill: "var(--surface-3)" }}
                     content={({ active, payload, label }) =>
                       active && payload?.length ? (
                         <TipShell title={String(label)}
                                   rows={[
                                     ["Really ran out", pct(payload[0]?.payload.rate, 1),
                                      "var(--series-1)"],
                                     ["Base rate", pct(baseRate, 1)],
                                   ]} />
                       ) : null } />
            <ReferenceLine y={baseRate} stroke="var(--axis)" strokeDasharray="4 4" />
            <Bar dataKey="rate" fill="var(--series-1)" radius={[4, 4, 0, 0]}
                 isAnimationActive={false} maxBarSize={90}>
              <LabelList dataKey="rate" position="top"
                         formatter={(v: number) => pct(v, 1)}
                         style={{ fontSize: 12, fill: "var(--text-secondary)" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartBox>
      <p className="text-[11px] mt-2" style={{ color: "var(--text-muted)" }}>
        Dashed line: the base rate of {pct(baseRate, 1)} across every scored
        position. {notActed === null && "Every position was acted on, so there is no comparison group."}
      </p>
    </>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

/** Cumulative incidence: the two causes and survival must partition to 1. */
export function CifPartitionChart({ curve, height = 260 }: {
  curve: { t: number; cif_stockout: number; cif_replenished: number; survival_any: number }[];
  height?: number;
}) {
  return (
    <>
      <ChartBox>
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={curve} margin={{ top: 8, right: 16, bottom: 18, left: -10 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} tickLine={false}
                   axisLine={{ stroke: "var(--axis)" }} minTickGap={32}>
              <Label value="days" position="insideBottom" offset={-10}
                     style={{ fontSize: 11, fill: "var(--text-muted)" }} />
            </XAxis>
            <YAxis domain={[0, 1]} width={54} tick={AXIS} tickLine={false} axisLine={false}
                   tickFormatter={(v) => pct(v)} />
            <Tooltip cursor={{ stroke: "var(--axis)" }}
                     content={({ active, payload, label }) => {
                       const row = payload?.[0]?.payload;
                       return active && row ? (
                         <TipShell title={`Day ${label}`}
                                   rows={[
                                     ["Stocked out", pct(row.cif_stockout, 1), "var(--series-2)"],
                                     ["Replenished", pct(row.cif_replenished, 1), "var(--series-1)"],
                                     ["Still running", pct(row.survival_any, 1), "var(--seq-250)"],
                                     ["Total", pct(row.cif_stockout + row.cif_replenished + row.survival_any, 2)],
                                   ]} />
                       ) : null;
                     }} />
            <Area dataKey="cif_stockout" stackId="1" stroke="var(--series-2)"
                  strokeWidth={2} fill="var(--series-2)" fillOpacity={0.5}
                  isAnimationActive={false} />
            <Area dataKey="cif_replenished" stackId="1" stroke="var(--series-1)"
                  strokeWidth={2} fill="var(--series-1)" fillOpacity={0.5}
                  isAnimationActive={false} />
            {/* Third band takes a sequential step rather than a third categorical
                hue: it is the remainder, not a peer category. */}
            <Area dataKey="survival_any" stackId="1" stroke="var(--seq-250)"
                  strokeWidth={2} fill="var(--seq-250)" fillOpacity={0.5}
                  isAnimationActive={false} />
            <ReferenceLine y={1} stroke="var(--axis)" strokeDasharray="4 4" />
          </ComposedChart>
        </ResponsiveContainer>
      </ChartBox>
      <div className="flex flex-wrap items-center gap-4 mt-2 text-[11px]"
           style={{ color: "var(--text-muted)" }}>
        <Swatch color="var(--series-2)" label="stocked out" />
        <Swatch color="var(--series-1)" label="replenished first" />
        <Swatch color="var(--seq-250)" label="still running" />
      </div>
    </>
  );
}
