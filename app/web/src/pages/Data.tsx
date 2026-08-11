import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { num } from "../lib/format";
import { Card, Note, Spinner, Table } from "../components/ui";

/**
 * The page that keeps the demo honest.
 *
 * Everything in this product runs on a synthetic extract that is deliberately
 * better instrumented than the supplied one. Showing a complete-looking dashboard
 * while quietly depending on data the client does not have is the failure mode
 * this page exists to prevent, so the gap is stated rather than smoothed over.
 */
export function Data() {
  const [provenance, setProvenance] = useState<any>(null);

  useEffect(() => { api.provenance().then(setProvenance).catch(() => {}); }, []);
  if (!provenance) return <Spinner label="Reading the data contract…" />;

  const missing = provenance.tables.filter((t: any) => !t.in_supplied_extract);
  const present = provenance.tables.filter((t: any) => t.in_supplied_extract);

  return (
    <div className="flex flex-col gap-5">
      <Card title="Model" subtitle="What is behind every number in this application">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Fact label="Family" value={provenance.model.family} />
          <Fact label="Held-out C-index" value={String(provenance.model.c_index)} />
          <Fact label="Spells trained"
                value={`${num(provenance.model.spells_train)} / ${num(provenance.model.spells_test)} test`} />
          <Fact label="Features" value={String(provenance.model.features.length)} />
        </div>
        <Note>
          The split is chronological, not random: a random split would put spells
          from the same store, SKU and week on both sides and inflate every
          metric. Train ends {provenance.model.split_date}.
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

      <Card title="Model inputs" subtitle="Every feature the survival model reads">
        <div className="flex flex-wrap gap-1.5">
          {provenance.model.features.map((feature: string) => (
            <span key={feature} className="text-[11px] rounded px-2 py-1"
                  style={{ background: "var(--surface-3)", color: "var(--text-secondary)" }}>
              {feature}
            </span>
          ))}
        </div>
        <Note>
          Every one is computable at the moment a decision is made. A test
          multiplies all sales from the decision point onward by 100 and asserts
          that not one feature moves, which is a mechanical proof of no
          look-ahead rather than a code review.
        </Note>
      </Card>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md px-3 py-2.5" style={{ background: "var(--surface-3)" }}>
      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p className="text-[14px] font-medium mt-0.5">{value}</p>
    </div>
  );
}
