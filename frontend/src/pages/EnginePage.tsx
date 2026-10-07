import { Link } from "react-router-dom";
import { PageHeader } from "../components/layout/PageHeader";

const pipelineStages = [
  { title: "SQL Frontend", description: "Lexer and parser turn one supported SQL statement into an unresolved syntax tree.", detail: "Handwritten lexer + recursive-descent parser" },
  { title: "Bind", description: "Resolves tables, columns, predicates, and types against the catalog.", detail: "Catalog-aware binding" },
  { title: "Plan", description: "Builds deterministic plan operators and selects an eligible index access path when rules allow.", detail: "Rule-based planning" },
  { title: "Execute", description: "Streams tuples through open / next / close operators for scans, filters, joins, aggregation, sorting, and limits.", detail: "Volcano-style iterator execution" },
  { title: "Persist", description: "Reads and writes typed records through catalog-managed heap files, slotted pages, and the buffer pool.", detail: "4 KiB fixed-size pages" },
];

const capabilities = [
  { title: "SQL Processing", description: "Handwritten lexer, recursive-descent parser, and catalog-aware binder.", evidence: "SELECT · WHERE · ORDER BY · LIMIT/OFFSET" },
  { title: "Query Execution", description: "Volcano-style operators for scans, filtering, projection, sorting, and limits.", evidence: "TableScan · IndexScan · Filter · Projection" },
  { title: "Relational Operations", description: "Aggregation with GROUP BY plus two-table INNER JOIN through nested-loop execution.", evidence: "COUNT · SUM · AVG · MIN · MAX" },
  { title: "Persistent Storage", description: "4 KiB pages, slotted-page heap records, buffer pooling, and persistent secondary B+ Tree indexes.", evidence: "PageFile · SlottedPage · BufferPool" },
];

export function EnginePage() {
  return (
    <div className="max-w-6xl">
      <section>
        <PageHeader description="A relational database engine built from scratch in Python." title="Strata Database Engine" />
        <div className="mt-6 max-w-3xl">
          <p className="text-sm font-medium text-[var(--strata-muted)]">Built for Strata&apos;s project-management workload.</p>
          <p className="mt-3 text-lg font-medium leading-7 text-[var(--strata-text)]">The application is the workload; the custom DBMS is the innovation.</p>
        </div>
      </section>

      <section aria-labelledby="pipeline-heading" className="mt-10">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--strata-muted)]">Query pipeline</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[var(--strata-text)]" id="pipeline-heading">From SQL to storage</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--strata-muted)]">Each supported query follows a small, explicit path through the engine.</p>
        </div>
        <ol className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {pipelineStages.map((stage, index) => (
            <li className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-4" key={stage.title}>
              <p className="font-mono text-xs font-semibold text-[var(--strata-accent)]">{String(index + 1).padStart(2, "0")}</p>
              <h3 className="mt-3 text-sm font-semibold text-[var(--strata-text)]">{stage.title}</h3>
              <p className="mt-2 text-sm leading-6 text-[var(--strata-muted)]">{stage.description}</p>
              <p className="mt-3 font-mono text-xs leading-5 text-[var(--strata-subtle)]">{stage.detail}</p>
            </li>
          ))}
        </ol>
        <aside aria-labelledby="indexing-heading" className="mt-4 rounded-md border border-indigo-200 bg-indigo-50 px-5 py-4">
          <h3 className="text-sm font-semibold text-indigo-950" id="indexing-heading">Persistent B+ Tree indexing</h3>
          <p className="mt-1 text-sm leading-6 text-indigo-900">Catalog-managed secondary indexes persist B+ Tree entries. Eligible predicates select IndexScan; the tree returns record identifiers before rows are fetched.</p>
          <p className="mt-3 font-mono text-xs font-medium text-indigo-800">Point + range access · Persistent index files · Index-aware planning</p>
        </aside>
      </section>

      <section aria-labelledby="capabilities-heading" className="mt-10">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--strata-muted)]">Engine capabilities</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[var(--strata-text)]" id="capabilities-heading">A focused relational core</h2>
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {capabilities.map((capability) => (
            <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-5" key={capability.title}>
              <h3 className="text-sm font-semibold text-[var(--strata-text)]">{capability.title}</h3>
              <p className="mt-2 text-sm leading-6 text-[var(--strata-muted)]">{capability.description}</p>
              <p className="mt-4 font-mono text-xs leading-5 text-[var(--strata-subtle)]">{capability.evidence}</p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="bridge-heading" className="mt-10 rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-5 sm:p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--strata-muted)]">Product connection</p>
        <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[var(--strata-text)]" id="bridge-heading">One engine, two views</h2>
        <div className="mt-4 max-w-3xl space-y-3 text-sm leading-6 text-[var(--strata-muted)]">
          <p>Overview, Tasks, and Board use the product REST API, ProductService, and the dedicated Strata product database.</p>
          <p>SQL Console remains a separate DBthon demo surface; its execution profiles are assembled from the TableScan or IndexScan operator used for that SQL execution.</p>
        </div>
        <Link className="mt-5 inline-flex rounded-md bg-[var(--strata-accent)] px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--strata-accent)]" to="/sql">Open SQL Console</Link>
      </section>
    </div>
  );
}
