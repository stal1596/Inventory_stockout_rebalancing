import type { ReactNode } from "react";
import type { Band } from "../lib/api";
import { bandColor, num } from "../lib/format";

export function Card({
  title, subtitle, right, children, className = "",
}: {
  title?: string; subtitle?: string; right?: ReactNode;
  children: ReactNode; className?: string;
}) {
  return (
    <section className={`card p-5 min-w-0 ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 mb-4">
          <div>
            {title && (
              <h2 className="text-[13px] font-semibold tracking-wide uppercase"
                  style={{ color: "var(--text-secondary)" }}>
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="text-[13px] mt-1" style={{ color: "var(--text-muted)" }}>
                {subtitle}
              </p>
            )}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

/** Stat tile. A hero number is a form in its own right — no chart needed when
 *  the job is a single magnitude. Proportional figures, per the type rule. */
export function Kpi({
  label, value, sub, tone, hint,
}: {
  label: string; value: ReactNode; sub?: ReactNode;
  tone?: string; hint?: string;
}) {
  return (
    <div className="card p-4 flex flex-col gap-1" title={hint}>
      <span className="text-[11px] font-medium uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span className="text-[26px] leading-tight font-semibold"
            style={{ color: tone ?? "var(--text-primary)" }}>
        {value}
      </span>
      {sub && (
        <span className="text-[12px]" style={{ color: "var(--text-secondary)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}

/** Risk band. Colour never carries the band alone — the label is always there,
 *  which is the mitigation the status palette requires. */
export function BandBadge({ band, small }: { band: Band; small?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${
        small ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-[12px]"
      }`}
      style={{ background: `color-mix(in srgb, ${bandColor[band]} 16%, transparent)`,
               color: bandColor[band] }}
    >
      <span className="w-1.5 h-1.5 rounded-full"
            style={{ background: bandColor[band] }} aria-hidden />
      {band}
    </span>
  );
}

export function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="h-2 rounded-full w-full" style={{ background: "var(--surface-3)" }}>
      {/* 4px rounded data-end anchored to the baseline */}
      <div className="h-2 rounded-full" style={{ width: `${width}%`, background: color }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-center py-12 text-[13px]"
         style={{ color: "var(--text-muted)" }}>
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-12 justify-center text-[13px]"
         style={{ color: "var(--text-muted)" }}>
      <span className="w-4 h-4 rounded-full border-2 animate-spin"
            style={{ borderColor: "var(--axis)", borderTopColor: "var(--series-1)" }} />
      {label}
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-5 px-5">
      <table className="w-full text-[13px] tnum" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}
                  className="text-left font-medium pb-2 pr-4 whitespace-nowrap text-[11px] uppercase tracking-wider"
                  style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="text-[12px] leading-relaxed mt-3" style={{ color: "var(--text-muted)" }}>
      {children}
    </p>
  );
}

export function Delta({ from, to, invert }: { from: number; to: number; invert?: boolean }) {
  const change = to - from;
  const better = invert ? change > 0 : change < 0;
  if (Math.abs(change) < 1e-9) {
    return <span style={{ color: "var(--text-muted)" }}>no change</span>;
  }
  return (
    <span style={{ color: better ? "var(--success-text)" : "var(--status-critical)" }}>
      {better ? "▼" : "▲"} {num(Math.abs(change * 100), 1)} pts
    </span>
  );
}
