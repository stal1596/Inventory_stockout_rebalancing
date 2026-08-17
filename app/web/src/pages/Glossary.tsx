import { useMemo, useState } from "react";
import { Card, Empty } from "../components/ui";
import { GROUP_BLURB, GROUP_ORDER, TERMS, type Term } from "../lib/glossary";

/**
 * Every number in the product, explained once.
 *
 * Rendered from the same `TERMS` map the tooltips read, so a definition here and
 * the hint on the column it describes cannot drift apart -- which is exactly
 * what happens to a glossary maintained as its own prose document.
 */
export function Glossary() {
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const match = (t: Term, key: string) =>
      !needle ||
      t.label.toLowerCase().includes(needle) ||
      t.help.toLowerCase().includes(needle) ||
      key.toLowerCase().includes(needle) ||
      (t.technical ?? "").toLowerCase().includes(needle);

    // Deduplicated by label: several API fields share one idea (`days_of_cover`
    // and `log_days_of_cover`), and listing the same definition twice makes the
    // page look padded rather than thorough.
    return GROUP_ORDER.map((group) => {
      const seen = new Set<string>();
      const entries = Object.entries(TERMS)
        .filter(([key, t]) => t.group === group && match(t, key))
        .filter(([, t]) => !seen.has(t.label) && seen.add(t.label))
        .sort((a, b) => a[1].label.localeCompare(b[1].label));
      return { group, entries };
    }).filter((section) => section.entries.length > 0);
  }, [query]);

  return (
    <div className="flex flex-col gap-5">
      <Card
        title="What the numbers mean"
        subtitle="Every figure in the product, in plain English. The grey line under each one names the underlying method, for anyone reconciling a screen against a report."
        right={
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            aria-label="Search the glossary"
            className="rounded-md px-3 py-1.5 text-[13px] w-[180px] outline-none"
            style={{
              background: "var(--surface-1)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        }
      >
        {!grouped.length && <Empty>Nothing matches “{query}”.</Empty>}

        <div className="flex flex-col gap-8">
          {grouped.map(({ group, entries }) => (
            <section key={group}>
              <h3 className="text-[13px] font-semibold tracking-tight">{group}</h3>
              <p className="text-[12px] leading-relaxed mt-0.5 mb-4 max-w-[60ch]"
                 style={{ color: "var(--text-muted)" }}>
                {GROUP_BLURB[group]}
              </p>
              <dl className="flex flex-col">
                {entries.map(([key, t]) => (
                  <div key={key} className="py-3 grid gap-1 sm:grid-cols-[minmax(0,190px)_minmax(0,1fr)] sm:gap-5"
                       style={{ borderTop: "1px solid var(--border)" }}>
                    <dt className="text-[13px] font-medium">{t.label}</dt>
                    <dd className="text-[13px] leading-relaxed max-w-[70ch]"
                        style={{ color: "var(--text-secondary)" }}>
                      {t.help}
                      {t.technical && (
                        <span className="block text-[11px] mt-1"
                              style={{ color: "var(--text-muted)" }}>
                          {t.technical}
                        </span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </Card>
    </div>
  );
}
