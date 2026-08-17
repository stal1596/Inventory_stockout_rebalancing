import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line,
  LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ReactNode } from "react";
import type { Driver } from "../lib/api";
import { days, featureLabel, num, pct } from "../lib/format";


/**
 * Recharts' ResponsiveContainer measures its parent and, inside a grid or flex
 * item, can inflate it and never shrink back -- which pushed the whole page wider
 * than the viewport the moment a chart appeared. `width:0; min-width:100%` gives
 * it a definite basis to measure against, so it fills the column and cannot
 * grow it.
 */
export function ChartBox({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden" style={{ width: 0, minWidth: "100%" }}>
      {children}
    </div>
  );
}

const AXIS = { fontSize: 11, fill: "var(--text-muted)" };
const GRID = "var(--grid)";

/** Shared tooltip shell. An HTML chart is interactive by default, so every
 *  chart here ships a hover layer rather than treating it as an extra. */
export function TipShell({ title, rows }: { title: string; rows: [string, string, string?][] }) {
  return (
    <div className="rounded-lg px-3 py-2 text-[12px] shadow-lg"
         style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <p className="font-medium mb-1.5">{title}</p>
      {rows.map(([label, value, color]) => (
        <p key={label} className="flex items-center gap-2 justify-between tnum">
          <span className="flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            {color && <span className="w-2 h-2 rounded-full" style={{ background: color }} />}
            {label}
          </span>
          <span style={{ color: "var(--text-primary)" }}>{value}</span>
        </p>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Driver waterfall                                                    */
/* ------------------------------------------------------------------ */

/**
 * Diverging by nature: each feature either buys the SKU time or costs it time,
 * and zero is a real midpoint. So this uses the diverging pair (blue / red)
 * rather than categorical hues — polarity is the data's job here.
 *
 * Bars are labelled directly with the day effect, which is also the relief the
 * palette requires where a fill sits below 3:1 on the light surface.
 */
export function DriverWaterfall({ drivers }: { drivers: Driver[] }) {
  const shown = drivers.slice(0, 9);
  if (!shown.length) return null;
  const max = Math.max(...shown.map((d) => Math.abs(d.days_effect)), 0.1);

  return (
    <div className="flex flex-col gap-2.5">
      {/* Fixed three-column row: label, bar, value. The value used to float at
          the end of its own bar, which collided with the label as soon as a bar
          reached full width. A reserved column cannot collide. */}
      {shown.map((driver) => {
        const negative = driver.days_effect < 0;
        const width = (Math.abs(driver.days_effect) / max) * 48;
        return (
          <div key={driver.feature} className="flex items-center gap-2.5">
            <div className="w-[112px] shrink-0 text-[11.5px] text-right leading-tight truncate"
                 title={featureLabel(driver.feature)}
                 style={{ color: driver.actionable
                   ? "var(--text-secondary)" : "var(--text-muted)" }}>
              {featureLabel(driver.feature)}
            </div>
            <div className="flex-1 min-w-0 relative h-5 flex items-center">
              <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--axis)" }} />
              <div
                className="absolute h-3 transition-all"
                style={{
                  width: `${width}%`,
                  [negative ? "right" : "left"]: "50%",
                  background: negative ? "var(--status-critical)" : "var(--series-1)",
                  borderRadius: negative ? "4px 0 0 4px" : "0 4px 4px 0",
                }}
              />
            </div>
            <div className="w-[46px] shrink-0 text-[11px] tnum text-right"
                 style={{ color: "var(--text-secondary)" }}>
              {driver.days_effect > 0 ? "+" : ""}{driver.days_effect.toFixed(1)}d
            </div>
          </div>
        );
      })}
      <div className="flex items-center gap-4 mt-1 text-[11px]" style={{ color: "var(--text-muted)" }}>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--status-critical)" }} />
          makes stock run out sooner
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
          makes it last longer
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Monte Carlo fan                                                     */
/* ------------------------------------------------------------------ */

/** Inventory trajectory with a P10–P90 band. One measure, one axis. */
export function FanChart({ data, height = 240 }: {
  data: { day: number; p10_stock: number; p50_stock: number; p90_stock: number }[];
  height?: number;
}) {
  const shaped = data.map((d) => ({ ...d, band: [d.p10_stock, d.p90_stock] as [number, number] }));
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={shaped} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="day" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }}
               label={{ value: "days ahead", position: "insideBottom", offset: -2, style: AXIS }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={54} />
        <Tooltip
          cursor={{ stroke: "var(--axis)" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TipShell
                title={`Day ${label}`}
                rows={[
                  ["If things go well", num(payload[0]?.payload.p90_stock, 0)],
                  ["Most likely", num(payload[0]?.payload.p50_stock, 0), "var(--series-1)"],
                  ["If things go badly", num(payload[0]?.payload.p10_stock, 0)],
                ]}
              />
            ) : null
          }
        />
        <Area type="monotone" dataKey="band" stroke="none"
              fill="var(--series-1)" fillOpacity={0.16} isAnimationActive={false} />
        <Line type="monotone" dataKey="p50_stock" stroke="var(--series-1)" strokeWidth={2}
              dot={false} isAnimationActive={false} />
        <ReferenceLine y={0} stroke="var(--status-critical)" strokeDasharray="3 3" />
      </ComposedChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** Cumulative P(stockout by day t): baseline against scenario. */
export function ProbabilityCurve({ baseline, scenario, height = 220 }: {
  baseline: { day: number; probability: number }[];
  scenario: { day: number; probability: number }[];
  height?: number;
}) {
  const merged = baseline.map((point, index) => ({
    day: point.day,
    baseline: point.probability,
    scenario: scenario[index]?.probability ?? null,
  }));
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={merged} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="day" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={54}
               domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip
          cursor={{ stroke: "var(--axis)" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TipShell title={`Within ${label} days`}
                        rows={[
                          ["As things stand", pct(payload[0]?.payload.baseline, 1), "var(--series-1)"],
                          ["Your what-if", pct(payload[0]?.payload.scenario, 1), "var(--series-2)"],
                        ]} />
            ) : null
          }
        />
        <Line type="monotone" dataKey="baseline" stroke="var(--series-1)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="Baseline" />
        <Line type="monotone" dataKey="scenario" stroke="var(--series-2)" strokeWidth={2}
              strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Scenario" />
      </LineChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** When does it run out? A histogram of simulated stockout days. */
export function StockoutHistogram({ data, height = 180 }: {
  data: { day: number; share: number }[]; height?: number;
}) {
  if (!data.length) {
    return (
      <div className="grid place-items-center text-[12px] py-10"
           style={{ color: "var(--text-muted)" }}>
        Not one run sold out inside this window.
      </div>
    );
  }
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="day" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={54}
               tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip cursor={{ fill: "var(--surface-3)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={`Day ${label}`}
                               rows={[["Ran out on this day", pct(payload[0]?.payload.share, 1)]]} />
                   ) : null } />
        <Bar dataKey="share" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** Projected depletion from today's shelf at the observed demand rate. */
export function DepletionChart({ data, height = 200 }: {
  data: { day: number; projected_stock: number }[]; height?: number;
}) {
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="day" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={54} />
        <Tooltip cursor={{ stroke: "var(--axis)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={`Day ${label}`}
                               rows={[["Projected stock",
                                       num(payload[0]?.payload.projected_stock, 0),
                                       "var(--series-1)"]]} />
                   ) : null } />
        <Area type="monotone" dataKey="projected_stock" stroke="var(--series-1)"
              strokeWidth={2} fill="var(--series-1)" fillOpacity={0.14}
              isAnimationActive={false} />
        <ReferenceLine y={0} stroke="var(--status-critical)" strokeDasharray="3 3" />
      </AreaChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** Network inventory against demand. Two measures of similar scale, one axis —
 *  never a second y-scale. */
export function TrendChart({ data, height = 240 }: {
  data: { date: string; on_hand: number; units_sold: number }[]; height?: number;
}) {
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }}
               minTickGap={48} tickFormatter={(v) => String(v).slice(5)} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
        <Tooltip cursor={{ stroke: "var(--axis)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={String(label)}
                               rows={[
                                 ["Units on hand", num(payload[0]?.payload.on_hand), "var(--series-1)"],
                                 ["Units sold", num(payload[0]?.payload.units_sold), "var(--series-2)"],
                               ]} />
                   ) : null } />
        <Line type="monotone" dataKey="on_hand" stroke="var(--series-1)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="On hand" />
        <Line type="monotone" dataKey="units_sold" stroke="var(--series-2)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="Sold" />
      </LineChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/**
 * The supply side of the same panel: what landed in stores, and what the DCs
 * were holding behind them.
 *
 * A separate chart rather than two more lines on `TrendChart`, for a reason the
 * palette forces: only three categorical slots are validated, so a fourth series
 * would introduce an unchecked pair. Two charts of two series each reuse the one
 * validated pair and stay readable.
 */
export function SupplyChart({ data, height = 230 }: {
  data: { date: string; received: number; dc_stock: number }[]; height?: number;
}) {
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }}
               minTickGap={48} tickFormatter={(v) => String(v).slice(5)} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
        <Tooltip cursor={{ stroke: "var(--axis)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={String(label)}
                               rows={[
                                 ["Units received", num(payload[0]?.payload.received), "var(--series-1)"],
                                 ["DC stock", num(payload[0]?.payload.dc_stock), "var(--series-2)"],
                               ]} />
                   ) : null } />
        <Line type="monotone" dataKey="received" stroke="var(--series-1)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="Received" />
        <Line type="monotone" dataKey="dc_stock" stroke="var(--series-2)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="DC stock" />
      </LineChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** Forecast against actual. Same measure, same scale, one axis. */
export function ForecastChart({ data, height = 240 }: {
  data: { week: string; forecast: number; actual: number }[]; height?: number;
}) {
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="week" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }}
               minTickGap={40} tickFormatter={(v) => String(v).slice(5)} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
        <Tooltip cursor={{ stroke: "var(--axis)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={`Week of ${label}`}
                               rows={[
                                 ["Forecast", num(payload[0]?.payload.forecast), "var(--series-1)"],
                                 ["Actual", num(payload[0]?.payload.actual), "var(--series-2)"],
                               ]} />
                   ) : null } />
        <Line type="monotone" dataKey="forecast" stroke="var(--series-1)" strokeWidth={2}
              strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Forecast" />
        <Line type="monotone" dataKey="actual" stroke="var(--series-2)" strokeWidth={2}
              dot={false} isAnimationActive={false} name="Actual" />
      </LineChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

/** Ordered magnitude across buckets — a sequential ramp, not categorical hues. */
export function DistributionChart({ data, xKey, yKey, height = 200, colors }: {
  data: any[]; xKey: string; yKey: string; height?: number; colors?: string[];
}) {
  return (
    <ChartBox>
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={54} />
        <Tooltip cursor={{ fill: "var(--surface-3)" }}
                 content={({ active, payload, label }) =>
                   active && payload?.length ? (
                     <TipShell title={String(label)}
                               rows={[["Positions", num(payload[0]?.value as number)]]} />
                   ) : null } />
        <Bar dataKey={yKey} radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((_, index) => (
            <Cell key={index} fill={colors?.[index] ?? "var(--series-1)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
    </ChartBox>
  );
}

export { days, num, pct };
