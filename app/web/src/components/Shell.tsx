import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { useStore } from "../store";
import { InfoHint } from "./ui";

/**
 * The nav is ordered as the working day, not alphabetically or by frequency:
 * where you stand -> what is coming -> how sure we are -> what to do. A user who
 * reads it top to bottom has read the argument.
 *
 * Each entry also carries the one-line `intro` shown under the page title. It
 * lives here rather than in eleven page files so that adding a page and
 * explaining it are the same edit.
 */
interface NavItem {
  to: string;
  label: string;
  stage?: string;
  intro: string;
  end?: boolean;
}

const JOURNEY: NavItem[] = [
  {
    to: "/", label: "Control Tower", stage: "Where you stand", end: true,
    intro: "How the network looks this morning. Start here, then follow anything that looks wrong.",
  },
  {
    to: "/inventory", label: "Inventory & Demand", stage: "What you hold",
    intro: "What you are holding, what is selling, and how reliably your suppliers deliver.",
  },
  {
    to: "/risk", label: "Stockout Risk", stage: "What's coming",
    intro: "The products most likely to run out, worst first. Pick one to see why, and what to do about it.",
  },
  {
    to: "/simulate", label: "Simulation", stage: "How sure we are",
    intro: "We play the next few weeks out thousands of times to see when a product runs out — and how much that answer could move.",
  },
  {
    to: "/prescribe", label: "Recommendations", stage: "What to do",
    intro: "Move stock, chase a delivery, or leave it alone. Every option is priced against doing nothing.",
  },
  // Last, and distinct from the step before it: a recommendation is a one-off
  // action, a reorder point is the standing rule that stops it recurring.
  {
    to: "/policy", label: "Reorder Policy", stage: "The standing rule",
    intro: "When to reorder each product, so the same shortage does not come back next month.",
  },
];

// Reference, not workflow. `/data` stays before longer paths so the breadcrumb's
// `startsWith` match never resolves one of them to it.
const REFERENCE: NavItem[] = [
  {
    to: "/network", label: "Supply Network",
    intro: "Which warehouse serves which store, and how each supplier is performing.",
  },
  {
    to: "/data", label: "Data & Model",
    intro: "Where each figure comes from, and which parts are measured rather than assumed.",
  },
  {
    to: "/glossary", label: "What the numbers mean",
    intro: "Every number in the product, in plain English.",
  },
];

/**
 * Model diagnostics. Kept in full and kept reachable, but out of the daily path.
 *
 * These pages exist to prove the model works, and they are dense with the
 * vocabulary that does it -- calibration, concordance, competing risks. That is
 * the right language for the person auditing the thing and the wrong language to
 * put in front of a planner deciding what to move today.
 */
const ADVANCED: NavItem[] = [
  {
    to: "/evidence", label: "Model Evidence",
    intro: "How the model scores on data it never saw while learning, and where it is weakest.",
  },
  {
    to: "/quality", label: "Data Quality",
    intro: "Whether the stock records add up, and what it means when they do not.",
  },
  {
    to: "/backtests", label: "Backtests",
    intro: "Rewind to a past date, run the predictions again, and check them against what actually happened.",
  },
];

export function Shell({ children, asOf, cIndex }: {
  children: ReactNode; asOf?: string; cIndex?: number;
}) {
  const { selection, clearSelection } = useStore();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);

  // Any navigation closes the drawer, or a phone user taps a link and stays
  // looking at the menu.
  useEffect(() => setNavOpen(false), [location.pathname]);

  return (
    <div className="min-h-full flex" style={{ background: "var(--surface-2)" }}>
      {navOpen && (
        <button aria-label="Close navigation" onClick={() => setNavOpen(false)}
                className="fixed inset-0 z-20 lg:hidden"
                style={{ background: "rgba(0,0,0,0.5)" }} />
      )}
      <aside className={`w-[232px] shrink-0 flex flex-col gap-6 px-4 py-6 sticky top-0 h-screen
                         max-lg:fixed max-lg:z-30 max-lg:transition-transform
                         ${navOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full"}`}
             style={{ borderRight: "1px solid var(--border)",
                      background: "var(--surface-2)" }}>
        <div className="px-2">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm rotate-45"
                  style={{ background: "var(--series-1)" }} aria-hidden />
            <span className="font-semibold text-[15px] tracking-tight">Control Tower</span>
          </div>
          <p className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
            Inventory intelligence
          </p>
        </div>

        <nav className="flex flex-col gap-0.5">
          <p className="px-2 pb-1 text-[10px] uppercase tracking-wider font-semibold"
             style={{ color: "var(--text-muted)" }}>
            Your working day
          </p>
          {JOURNEY.map((item, index) => (
            <NavLink key={item.to} to={item.to} end={item.end}
                     className="group flex items-center gap-2.5 rounded-md px-2 py-2 text-[13px] transition-colors"
                     style={({ isActive }) => ({
                       background: isActive ? "var(--surface-3)" : "transparent",
                       color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                       fontWeight: isActive ? 600 : 450,
                     })}>
              <span className="w-5 h-5 rounded-full grid place-items-center text-[10px] tnum shrink-0"
                    style={{ border: "1px solid var(--border)", color: "var(--text-muted)" }}>
                {index + 1}
              </span>
              <span className="flex flex-col leading-tight">
                {item.label}
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                  {item.stage}
                </span>
              </span>
            </NavLink>
          ))}
        </nav>

        <nav className="flex flex-col gap-0.5">
          <p className="px-2 pb-1 text-[10px] uppercase tracking-wider font-semibold"
             style={{ color: "var(--text-muted)" }}>
            Reference
          </p>
          {REFERENCE.map((item) => (
            <NavLink key={item.to} to={item.to}
                     className="rounded-md px-2 py-2 text-[13px] transition-colors"
                     style={({ isActive }) => ({
                       background: isActive ? "var(--surface-3)" : "transparent",
                       color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                       fontWeight: isActive ? 600 : 450,
                     })}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Collapsed by default, but forced open when the current route is
            inside it -- otherwise navigating to Model Evidence lands you on a
            page whose nav group appears shut. */}
        <details open={ADVANCED.some((item) => location.pathname.startsWith(item.to))}
                 className="flex flex-col">
          <summary className="group px-2 py-1 text-[10px] uppercase tracking-wider font-semibold cursor-pointer list-none flex items-center gap-1.5"
                   style={{ color: "var(--text-muted)" }}>
            <span aria-hidden
                  className="text-[8px] transition-transform group-open:rotate-90">▸</span>
            Advanced · for analysts
          </summary>
          <nav className="flex flex-col gap-0.5 mt-1">
            {ADVANCED.map((item) => (
              <NavLink key={item.to} to={item.to}
                       className="rounded-md px-2 py-2 text-[13px] transition-colors"
                       style={({ isActive }) => ({
                         background: isActive ? "var(--surface-3)" : "transparent",
                         color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                         fontWeight: isActive ? 600 : 450,
                       })}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </details>

        {/* The carried selection, visible on every page. This is what makes the
            journey feel continuous rather than like four separate tools. */}
        {selection && (
          <div className="mt-auto card p-3">
            <p className="text-[10px] uppercase tracking-wider font-semibold mb-1"
               style={{ color: "var(--text-muted)" }}>
              Following
            </p>
            <p className="text-[12px] font-medium break-all">{selection.skuUid}</p>
            <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
              at {selection.storeId}
            </p>
            <button onClick={clearSelection}
                    className="mt-2 text-[11px] underline underline-offset-2"
                    style={{ color: "var(--text-muted)" }}>
              clear
            </button>
          </div>
        )}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="flex items-center justify-between px-5 lg:px-8 py-4 sticky top-0 z-10"
                style={{ background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}>
          <span className="flex items-center gap-3 min-w-0">
            <button onClick={() => setNavOpen(true)} aria-label="Open navigation"
                    aria-expanded={navOpen}
                    className="lg:hidden rounded-md px-2 py-1 text-[13px] shrink-0"
                    style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              ☰
            </button>
            <Breadcrumb path={location.pathname} />
          </span>
          <div className="flex items-center gap-5 text-[12px]"
               style={{ color: "var(--text-muted)" }}>
            {/* This sits on every page in the product, so it was the most-read
                piece of jargon in it. The number is not lost -- it moved into
                the hint, where the people who want it will look. */}
            {cIndex !== undefined && (
              <span className="hidden md:inline-flex items-center gap-1.5">
                Model accuracy
                <span style={{ color: "var(--text-secondary)" }}>{accuracyRead(cIndex)}</span>
                <InfoHint
                  text={`Given two products, the model picks the one that runs out first about ${(cIndex * 100).toFixed(0)}% of the time — tested on data it never saw while learning. A coin flip would score 50%.`}
                  technical={`Held-out C-index ${cIndex.toFixed(3)} — concordance of the log-normal AFT survival model on unseen spells`}
                />
              </span>
            )}
            {asOf && (
              <span className="hidden sm:inline">
                As of <span className="tnum" style={{ color: "var(--text-secondary)" }}>{asOf}</span>
              </span>
            )}
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1 px-5 lg:px-8 py-6 min-w-0 overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}

/**
 * Page title and the one line saying what the page is for.
 *
 * ADVANCED must be in this list or its three pages lose their title and fall
 * back to reading "Control Tower".
 */
function Breadcrumb({ path }: { path: string }) {
  const all = [...JOURNEY, ...REFERENCE, ...ADVANCED];
  const current = all.find((i) => (i.to === "/" ? path === "/" : path.startsWith(i.to)));
  return (
    <span className="min-w-0">
      <h1 className="text-[17px] font-semibold tracking-tight leading-tight">
        {current?.label ?? "Control Tower"}
      </h1>
      {current && (
        <p className="text-[12px] leading-snug mt-0.5 hidden sm:block"
           style={{ color: "var(--text-muted)" }}>
          {current.intro}
        </p>
      )}
    </span>
  );
}

/** A plain read of the model's ranking accuracy, so the header stops leading
 *  with a statistic most readers cannot place. */
const accuracyRead = (cIndex: number) =>
  cIndex >= 0.75 ? "Strong" : cIndex >= 0.65 ? "Good" : "Fair";

/**
 * Three states, not two, and the choice survives a reload.
 *
 * `index.css` already carries a correct `prefers-color-scheme` block, but it was
 * inert: `index.html` hard-coded `data-theme="dark"` on the element, so the
 * attribute was always present and the media query could never win. "System" is
 * therefore a real state — it REMOVES the attribute and lets the OS decide — and
 * the stored choice is applied before first paint by a small script in the head,
 * so a light-mode user never sees a dark flash.
 */
const THEMES = ["system", "light", "dark"] as const;
type Theme = (typeof THEMES)[number];

export const THEME_KEY = "control-tower-theme";

function readTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY);
  return THEMES.includes(stored as Theme) ? (stored as Theme) : "system";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  const cycle = () => {
    const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(next);
    setTheme(next);
  };

  return (
    <button onClick={cycle} title={`Theme: ${theme}. Click to change.`}
            aria-label={`Theme: ${theme}. Click to change.`}
            className="rounded-md px-2 py-1 text-[12px] transition-colors capitalize"
            style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
      {theme}
    </button>
  );
}
