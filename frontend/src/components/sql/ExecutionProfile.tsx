import type { IndexCondition, SqlProfile, SqlValue } from "../../types/api";

export function ExecutionProfile({ profile }: { profile: SqlProfile | null }) {
  if (profile === null) {
    return (
      <section aria-labelledby="execution-profile-heading" className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-4 py-4">
        <h2 className="text-lg font-semibold text-[var(--strata-text)]" id="execution-profile-heading">Execution Profile</h2>
        <p className="mt-2 text-sm text-[var(--strata-muted)]">Unavailable for this query shape.</p>
      </section>
    );
  }

  const isIndexScan = profile.access_path === "IndexScan";
  const identity = `${profile.access_path} on ${profile.table}`;

  return (
    <section aria-labelledby="execution-profile-heading" className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--strata-text)]" id="execution-profile-heading">Execution Profile</h2>
          <p className="mt-1 text-sm text-[var(--strata-muted)]">{identity}</p>
        </div>
        <span className="rounded border border-indigo-200 bg-indigo-50 px-2 py-1 font-mono text-xs font-semibold text-indigo-800">{profile.access_path}</span>
      </div>

      <dl className="mt-5 grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
        <Metadata label="Access path" value={profile.access_path} />
        <Metadata label="Table" value={profile.table} />
        {isIndexScan ? (
          <>
            <Metadata label="Index" value={profile.index} />
            <Metadata label="Condition" value={formatCondition(profile.condition)} />
          </>
        ) : <Metadata label="Index" value="Not used" />}
      </dl>

      {isIndexScan ? (
        <>
          <p className="mt-5 text-sm leading-6 text-[var(--strata-muted)]">The planner selected <code className="font-mono text-[var(--strata-text)]">{profile.index}</code> because this query has an eligible comparison on the indexed <code className="font-mono text-[var(--strata-text)]">{profile.condition.column}</code> column. The index returned record identifiers before rows were fetched.</p>
          <BTreeFlow index={profile.index} ridsSelected={profile.metrics.rids_selected} rowsFetched={profile.metrics.rows_fetched} />
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric description="B+ Tree pages visited for the index lookup." label="Tree pages visited" value={profile.metrics.tree_pages_visited} />
            <Metric description="Index leaf entries inspected for the condition." label="Leaf entries examined" value={profile.metrics.leaf_entries_examined} />
            <Metric description="Record identifiers returned by the index." label="Record identifiers selected" value={profile.metrics.rids_selected} />
            <Metric description="Rows retrieved using selected record identifiers." label="Rows fetched" value={profile.metrics.rows_fetched} />
          </div>
        </>
      ) : (
        <>
          <p className="mt-5 text-sm leading-6 text-[var(--strata-muted)]">Read tuples directly from the table scan; the query predicate was evaluated by the execution pipeline.</p>
          <div className="mt-5 max-w-xs">
            <Metric description="Tuples read from the table scan." label="Tuples examined" value={profile.metrics.tuples_examined} />
          </div>
        </>
      )}
    </section>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--strata-subtle)]">{label}</dt>
      <dd className="mt-1 font-mono text-sm text-[var(--strata-text)]">{value}</dd>
    </div>
  );
}

function Metric({ description, label, value }: { description: string; label: string; value: number }) {
  return (
    <div className="rounded-md border border-[var(--strata-border)] bg-slate-50 px-3 py-3">
      <dt className="text-xs font-semibold text-[var(--strata-text)]">{label}</dt>
      <dd className="mt-2 text-xl font-semibold tabular-nums text-[var(--strata-text)]">{formatInteger(value)}</dd>
      <p className="mt-1 text-xs leading-5 text-[var(--strata-muted)]">{description}</p>
    </div>
  );
}

function BTreeFlow({ index, ridsSelected, rowsFetched }: { index: string; ridsSelected: number; rowsFetched: number }) {
  const recordIdentifierLabel = ridsSelected === 1 ? "record identifier" : "record identifiers";
  const rowLabel = rowsFetched === 1 ? "row" : "rows";
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2 rounded-md border border-[var(--strata-border)] bg-slate-50 px-3 py-3 text-sm text-[var(--strata-muted)]">
      <span><span className="font-semibold text-[var(--strata-text)]">B+ Tree index</span> <code className="font-mono text-[var(--strata-text)]">{index}</code></span>
      <span aria-hidden="true" className="text-[var(--strata-subtle)]">→</span>
      <span><span className="font-semibold tabular-nums text-[var(--strata-text)]">{formatInteger(ridsSelected)}</span> {recordIdentifierLabel} selected</span>
      <span aria-hidden="true" className="text-[var(--strata-subtle)]">→</span>
      <span><span className="font-semibold tabular-nums text-[var(--strata-text)]">{formatInteger(rowsFetched)}</span> {rowLabel} fetched</span>
    </div>
  );
}

function formatCondition(condition: IndexCondition): string {
  return `${condition.column} ${condition.operator} ${formatLiteral(condition.literal)}`;
}

function formatLiteral(value: SqlValue): string {
  if (value === null) return "NULL";
  if (typeof value === "string") return `'${value.replaceAll("'", "''")}'`;
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  return String(value);
}

function formatInteger(value: number): string {
  return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
