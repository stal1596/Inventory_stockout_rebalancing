import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { useStore } from "../store";

/**
 * The nav is ordered as the analytical journey, not alphabetically or by
 * frequency: descriptive -> predictive -> simulation -> prescriptive. A user who
 * reads it top to bottom has read the argument.
 */
const JOURNEY = [
  { to: "/", label: "Control Tower", stage: "Overview", end: true },
  { to: "/inventory", label: "Inventory & Demand", stage: "Descriptive" },
  { to: "/risk", label: "Stockout Risk", stage: "Predictive" },
  { to: "/simulate", label: "Simulation", stage: "Uncertainty" },
  { to: "/prescribe", label: "Recommendations", stage: "Prescriptive" },
  // Last, and distinct from the step before it: a recommendation is a one-off
  // action, a reorder point is the standing rule that stops it recurring.
  { to: "/policy", label: "Reorder Policy", stage: "Standing policy" },
];

// Evidence, not workflow. `/data` stays first so the breadcrumb's `startsWith`
// match never resolves a longer path to it.
const REFERENCE = [
  { to: "/network", label: "Supply Network" },
  { to: "/data", label: "Data & Model" },
  { to: "/evidence", label: "Model Evidence" },
  { to: "/quality", label: "Data Quality" },
  { to: "/backtests", label: "Backtests" },
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
            Analytical journey
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
            {cIndex !== undefined && (
              <span className="hidden md:inline"
                    title="Held-out concordance of the survival model on unseen spells">
                Model C-index <span className="tnum" style={{ color: "var(--text-secondary)" }}>
                  {cIndex.toFixed(3)}
                </span>
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

function Breadcrumb({ path }: { path: string }) {
  const all = [...JOURNEY, ...REFERENCE];
  const current = all.find((i) => (i.to === "/" ? path === "/" : path.startsWith(i.to)));
  return (
    <h1 className="text-[17px] font-semibold tracking-tight">
      {current?.label ?? "Control Tower"}
    </h1>
  );
}

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
