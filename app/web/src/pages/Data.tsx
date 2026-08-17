import { api } from "../lib/api";
import { featureLabel, num } from "../lib/format";
import { Card, ErrorState, InfoHint, Note, Spinner, Table } from "../components/ui";
import { term } from "../lib/glossary";
import { useApi } from "../lib/useApi";

/**
 * The page that keeps the demo honest.
 *
 * Everything in this product runs on a synthetic extract that is deliberately
 * better instrumented than the supplied one. Showing a complete-looking dashboard
 * while quietly depending on data the client does not have is the failure mode
 * this page exists to prevent, so the gap is stated rather than smoothed over.
 */
export function Data() {
  const state = useApi(() => api.provenance(), []);

  if (state.error) return <ErrorState message={state.error} onRetry={state.refetch} />;
  if (!state.data) return <Spinner label="Checking where the data comes from…" />;

  const provenance = state.data;
  const missing = provenance.tables.filter((t) => !t.in_supplied_extract);
  const present = provenance.tables.filter((t) => t.in_supplied_extract);

  return (
    <div className="flex flex-col gap-5">
      <Card title="What is behind the numbers"
            subtitle="How the forecasting was built, and how well it holds up">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Fact label="Method" value="Survival analysis"
                hint="The same maths used to estimate how long something lasts before it fails — here, how long stock lasts before the shelf empties."
                technical={provenance.model.family} />
          <Fact label="Ranking accuracy" value={`${(provenance.model.c_index * 100).toFixed(0)}%`}
                hint="Given two products, how often it correctly picks the one that runs out first — measured on data it never saw while learning. A coin flip would score 50%."
                technical={`Held-out C-index ${provenance.model.c_index}`} />
          <Fact label="Learned from"
                value={`${num(provenance.model.spells_train)} runs of stock`}
                hint={`Each one is a stretch where a product sat in a store between deliveries. A further ${num(provenance.model.spells_test)} were held back to test against.`} />
          <Fact label="Things it looks at" value={String(provenance.model.features.length)}
                hint="Listed in full at the bottom of this page." />
        </div>
        <Note>
          It learned from the past and was tested on the future, never the other
          way round. Shuffling the two would put the same store, product and week
          on both sides and flatter every figure on this page. Learning stops at{" "}
          {provenance.model.split_date}.
        </Note>
      </Card>

      <Card title="Fields this extract has that the supplied one does not"
            subtitle="Synthesized by the generator so the product can be complete">
        <Table head={["Table", "Rows", "Why it is here"]}>
          {missing.map((table: any) => (
            <tr key={table.table} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-2.5 pr-4 font-medium align-top">{table.table}</td>
              <td className="py-2.5 pr-4 align-top">{num(table.rows)}</td>
              <td className="py-2.5 pr-4 align-top text-[12px] leading-relaxed"
                  style={{ color: "var(--text-secondary)" }}>
                {table.synthesized_note ?? table.description}
              </td>
            </tr>
          ))}
        </Table>
        <Note>{provenance.note}</Note>
      </Card>

      <Card title="Lead time: measured against inferred"
            subtitle="The cross-check that makes the inference trustworthy">
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-md p-4" style={{ background: "var(--surface-3)" }}>
            <p className="text-[11px] uppercase tracking-wider mb-1"
               style={{ color: "var(--text-muted)" }}>
              Observed, from goods receipts
            </p>
            <p className="text-[22px] font-semibold tnum">
              {provenance.lead_time.observed
                ? `${provenance.lead_time.observed.mean}d ± ${provenance.lead_time.observed.std}`
                : "not available"}
            </p>
            <p className="text-[12px] mt-1" style={{ color: "var(--text-secondary)" }}>
              {provenance.lead_time.observed
                ? `${num(provenance.lead_time.observed.n)} receipts`
                : "no receipt dates in this extract"}
            </p>
          </div>
          <div className="rounded-md p-4" style={{ background: "var(--surface-3)" }}>
            <p className="text-[11px] uppercase tracking-wider mb-1"
               style={{ color: "var(--text-muted)" }}>
              Inferred, from stock movement
            </p>
            <p className="text-[22px] font-semibold tnum">
              {provenance.lead_time.inferred.mean
                ? `${provenance.lead_time.inferred.mean}d ± ${provenance.lead_time.inferred.std}`
                : "—"}
            </p>
            <p className="text-[12px] mt-1" style={{ color: "var(--text-secondary)" }}>
              {num(provenance.lead_time.inferred.n)} inferred receipts
            </p>
          </div>
        </div>
        <Note>
          The model uses the inferred figure, because a real extract has no
          receipt date. That the two agree this closely is the evidence the
          inference is sound — and it is the reason the pipeline was never
          repointed at the receipt field.
        </Note>
      </Card>

      <Card title="Tables in both extracts" subtitle="Present in the supplied data as well">
        <Table head={["Table", "File", "Rows", "Description"]}>
          {present.map((table: any) => (
            <tr key={table.table} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-2 pr-4 font-medium align-top">{table.table}</td>
              <td className="py-2 pr-4 align-top" style={{ color: "var(--text-muted)" }}>
                {table.file}
              </td>
              <td className="py-2 pr-4 align-top">{num(table.rows)}</td>
              <td className="py-2 pr-4 align-top text-[12px] leading-relaxed max-w-[520px]"
                  style={{ color: "var(--text-secondary)" }}>
                {table.description}
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title="What it looks at"
            subtitle="Everything taken into account when judging a product's risk">
        <div className="flex flex-wrap gap-1.5">
          {/* These printed as raw identifiers -- `log_days_of_cover` and friends
              -- even though the translation map already existed and was used on
              the Risk page. */}
          {provenance.model.features.map((feature: string) => {
            const found = term(feature);
            return (
              <span key={feature}
                    className="text-[11px] rounded px-2 py-1 inline-flex items-center gap-1"
                    style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
                {featureLabel(feature)}
                {found && <InfoHint text={found.help} technical={found.technical} />}
              </span>
            );
          })}
        </div>
        <Note>
          Every one of these can be known at the moment you would make the
          decision — none of them peek at what happened next. That is checked
          mechanically: a test multiplies all later sales by 100 and asserts not
          one of these figures moves.
        </Note>
      </Card>
    </div>
  );
}

function Fact({ label, value, hint, technical }: {
  label: string; value: string; hint?: string; technical?: string;
}) {
  return (
    <div className="rounded-md px-3 py-2.5" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider inline-flex items-center gap-1"
         style={{ color: "var(--text-muted)" }}>
        {label}
        {hint && <InfoHint text={hint} technical={technical} />}
      </p>
      <p className="text-[14px] font-medium mt-0.5">{value}</p>
    </div>
  );
}
