import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import type { Band } from "../lib/api";
import type { ApiState } from "../lib/useApi";
import { bandColor, num } from "../lib/format";
import { prettify, term as lookupTerm } from "../lib/glossary";

const HINT_WIDTH = 288;

/**
 * The explanatory tooltip.
 *
 * Hand-rolled, because the only alternative in the tree is the browser's native
 * `title` attribute and it fails this job four ways: nothing on screen says a
 * hint exists, it waits about a second, it never appears on a touch device, and
 * on a non-interactive `div` most screen readers ignore it. So: a real button
 * with a visible affordance, opening on hover, focus AND click.
 *
 * It renders through a portal on purpose. `Table` wraps its content in
 * `overflow-x-auto`, which would clip an absolutely-positioned bubble on every
 * column header -- and column headers are exactly where the jargon lives.
 */
export function InfoHint({ text, technical, className = "" }: {
  text: string;
  /** The real field name and method, for whoever wants to check our working. */
  technical?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<{ top: number; left: number; above: boolean } | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);
  const closing = useRef<number | undefined>(undefined);
  const id = useId();

  const place = useCallback(() => {
    const el = anchor.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Clamped to the viewport so a hint on the last column of a wide table does
    // not open off the right-hand edge.
    const left = Math.min(
      Math.max(8, rect.left + rect.width / 2 - HINT_WIDTH / 2),
      Math.max(8, window.innerWidth - HINT_WIDTH - 8),
    );
    const above = window.innerHeight - rect.bottom < 190;
    setBox({ top: above ? rect.top - 8 : rect.bottom + 8, left, above });
  }, []);

  const show = () => {
    window.clearTimeout(closing.current);
    place();
    setOpen(true);
  };
  // A short grace period, so moving the pointer from the icon into the bubble
  // does not dismiss the thing you are reaching for.
  const hide = () => {
    closing.current = window.setTimeout(() => setOpen(false), 120);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  useEffect(() => () => window.clearTimeout(closing.current), []);

  return (
    <>
      <button
        ref={anchor}
        type="button"
        aria-label="What does this mean?"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          // Rows and cards are themselves clickable on several pages; a hint
          // must never select the row underneath it.
          e.stopPropagation();
          e.preventDefault();
          open ? setOpen(false) : show();
        }}
        className={`inline-grid place-items-center w-[14px] h-[14px] rounded-full text-[9px] font-semibold align-middle shrink-0 transition-colors cursor-help ${className}`}
        style={{
          border: "1px solid var(--axis)",
          color: open ? "var(--text-primary)" : "var(--text-muted)",
          background: open ? "var(--surface-3)" : "transparent",
          lineHeight: 1,
        }}
      >
        i
      </button>
      {open && box &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            onMouseEnter={() => window.clearTimeout(closing.current)}
            onMouseLeave={hide}
            className="card p-3 shadow-lg text-[12px] leading-relaxed"
            style={{
              position: "fixed",
              top: box.top,
              left: box.left,
              width: HINT_WIDTH,
              zIndex: 60,
              transform: box.above ? "translateY(-100%)" : undefined,
              color: "var(--text-secondary)",
            }}
          >
            {text}
            {technical && (
              <p className="mt-2 pt-2 text-[11px]"
                 style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}>
                {technical}
              </p>
            )}
            {/* `block`, not `inline-block` -- with no `technical` line between
                them the link ran straight on from the last sentence. */}
            <Link to="/glossary" onClick={() => setOpen(false)}
                  className="mt-2 block text-[11px] underline underline-offset-2"
                  style={{ color: "var(--series-1)" }}>
              All terms explained →
            </Link>
          </div>,
          document.body,
        )}
    </>
  );
}

/**
 * A label and its hint, looked up by the API field name the value is read with.
 *
 * Going through the field name rather than passing prose at the call site is
 * what keeps a column header, the tile on the overview and the glossary page
 * saying the same thing about the same number.
 */
export function TermLabel({ name, label, hideHint }: {
  name: string;
  /** Overrides the glossary label where a column needs to be shorter. */
  label?: string;
  hideHint?: boolean;
}) {
  const found = lookupTerm(name);
  const text = label ?? found?.label ?? prettify(name);
  if (!found || hideHint) return <>{text}</>;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      {text}
      <InfoHint text={found.help} technical={found.technical} />
    </span>
  );
}

export function Card({
  title, subtitle, right, children, className = "", id,
}: {
  title?: string;
  /** A node, not just a string, so a subtitle can carry a `TermLabel`. */
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode; className?: string;
  /** Anchor target for a `#hash` deep-link from the alert feed. */
  id?: string;
}) {
  return (
    <section id={id} className={`card p-5 min-w-0 scroll-mt-6 ${className}`}>
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
  label, value, sub, tone, hint, name,
}: {
  label?: string; value: ReactNode; sub?: ReactNode;
  tone?: string;
  /** Explanatory copy. Was a native `title`; now a real, discoverable hint. */
  hint?: string;
  /** API field name — takes the label and the hint from the glossary. */
  name?: string;
}) {
  const found = name ? lookupTerm(name) : undefined;
  const text = label ?? found?.label ?? (name ? prettify(name) : "");
  const help = hint ?? found?.help;
  return (
    <div className="card p-4 flex flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wider inline-flex items-center gap-1.5"
            style={{ color: "var(--text-muted)" }}>
        {text}
        {help && <InfoHint text={help} technical={found?.technical} />}
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

/** `head` takes nodes as well as strings so a column can carry a `TermLabel`. */
export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-5 px-5">
      <table className="w-full text-[13px] tnum" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {head.map((h, index) => (
              <th key={index} scope="col"
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

/**
 * A failure that looks like a failure.
 *
 * The three states are rendered in one place so no page can accidentally treat
 * "errored" as "still loading" -- which is what every page did before, leaving a
 * spinner turning forever on a 500. The retry matters as much as the message: the
 * API pays a ~45s warm-up, so the most common error a user meets is one that
 * fixes itself a moment later.
 */
export function Loadable<T>({
  state, label, children,
}: {
  state: ApiState<T>;
  label?: string;
  /** Called only once the data is present, so pages stop null-checking. */
  children: (data: T) => ReactNode;
}) {
  if (state.error !== null) {
    return <ErrorState message={state.error} onRetry={state.refetch} />;
  }
  if (state.data === null) return <Spinner label={label} />;
  return <>{children(state.data)}</>;
}

/**
 * A plain anchor, not a fetch-into-a-blob.
 *
 * The endpoint already sets `Content-Disposition: attachment` with a dated
 * filename, so the browser names the file, streams it to disk and shows its own
 * progress. Fetching it would re-implement all three, hold the whole file in
 * memory, and lose the server's filename unless the header were parsed by hand.
 * The one reason to prefer fetch -- attaching an auth header -- does not apply:
 * this API has none.
 */
export function DownloadCsv({ href, label = "Export CSV", title }: {
  href: string; label?: string; title?: string;
}) {
  return (
    <a href={href} download title={title}
       className="rounded-md px-2.5 py-1.5 text-[12px] inline-flex items-center gap-1.5 whitespace-nowrap"
       style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
      ↓ {label}
    </a>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <p className="text-[13px]" style={{ color: "var(--status-critical)" }}>
        Could not reach the API.
      </p>
      <p className="text-[12px] max-w-[420px]" style={{ color: "var(--text-muted)" }}>
        {message}
      </p>
      {onRetry && (
        <button onClick={onRetry}
                className="rounded-md px-3 py-1.5 text-[13px] font-medium transition-opacity hover:opacity-90"
                style={{ background: "var(--series-1)", color: "#fff" }}>
          Try again
        </button>
      )}
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
