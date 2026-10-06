import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { executeSqlProfile, StrataApiError } from "../api/strata";
import { PageHeader } from "../components/layout/PageHeader";
import type { SqlProfileResponse, SqlValue } from "../types/api";

const TABLE_SCAN_SQL = "SELECT id, title, status, priority\nFROM tasks\nWHERE priority = 'URGENT';";
const INDEX_SCAN_SQL = "SELECT id, title, status, priority\nFROM tasks\nWHERE status = 'BLOCKED';";

const presets = [
  { label: "Table scan demo", sql: TABLE_SCAN_SQL },
  { label: "Index scan demo", sql: INDEX_SCAN_SQL },
] as const;

interface ExecutionError {
  title: string;
  message: string;
  code?: string;
}

export function SqlConsolePage() {
  const [sql, setSql] = useState(TABLE_SCAN_SQL);
  const [result, setResult] = useState<SqlProfileResponse | null>(null);
  const [executionError, setExecutionError] = useState<ExecutionError | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const mountedRef = useRef(true);
  const runningRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const runSql = async () => {
    if (runningRef.current) {
      return;
    }

    const trimmedSql = sql.trim();
    if (!trimmedSql) {
      setExecutionError({ title: "SQL required", message: "Enter a SQL statement before running it." });
      return;
    }

    runningRef.current = true;
    setIsRunning(true);
    setExecutionError(null);
    try {
      const response = await executeSqlProfile(trimmedSql);
      if (mountedRef.current) {
        setResult(response);
      }
    } catch (error) {
      if (mountedRef.current) {
        setExecutionError(classifyExecutionError(error));
      }
    } finally {
      runningRef.current = false;
      if (mountedRef.current) {
        setIsRunning(false);
      }
    }
  };

  const handleEditorKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void runSql();
    }
  };

  const selectPreset = (presetSql: string) => {
    setSql(presetSql);
    if (executionError?.title === "SQL required") {
      setExecutionError(null);
    }
  };

  return (
    <section className="max-w-6xl">
      <PageHeader description="Run SQL directly against the Strata database workload." title="SQL Console" />

      <section aria-labelledby="sql-editor-heading" className="mt-6 rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--strata-text)]" id="sql-editor-heading">Query editor</h2>
            <p className="mt-1 text-sm text-[var(--strata-muted)]">Execute one SQL statement against the Strata demo database.</p>
          </div>
          <div aria-label="SQL demo presets" className="flex flex-wrap gap-2">
            {presets.map((preset) => (
              <button
                className="rounded-md border border-[var(--strata-border)] px-3 py-1.5 text-sm font-medium text-[var(--strata-muted)] hover:bg-[var(--strata-hover)] hover:text-[var(--strata-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--strata-accent)] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isRunning}
                key={preset.label}
                onClick={() => selectPreset(preset.sql)}
                type="button"
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <label className="mt-5 block text-sm font-semibold text-[var(--strata-text)]" htmlFor="sql-editor">SQL statement</label>
        <textarea
          className="mt-2 min-h-72 w-full resize-y rounded-md border border-[var(--strata-border)] bg-slate-50 px-3 py-3 font-mono text-sm leading-6 text-[var(--strata-text)] shadow-none outline-none placeholder:text-[var(--strata-subtle)] focus:border-[var(--strata-accent)] focus:ring-2 focus:ring-[var(--strata-accent-soft)]"
          id="sql-editor"
          onChange={(event) => setSql(event.target.value)}
          onKeyDown={handleEditorKeyDown}
          spellCheck={false}
          value={sql}
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-[var(--strata-subtle)]">Run with Ctrl+Enter or ⌘Enter.</p>
          <button
            className="rounded-md bg-[var(--strata-accent)] px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--strata-accent)] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isRunning}
            onClick={() => void runSql()}
            type="button"
          >
            {isRunning ? "Running…" : "Run query"}
          </button>
        </div>
      </section>

      <section aria-labelledby="execution-output-heading" className="mt-6">
        <h2 className="sr-only" id="execution-output-heading">Execution output</h2>
        {isRunning && <p aria-live="polite" className="mb-4 text-sm text-[var(--strata-muted)]">Executing SQL…</p>}
        {executionError && <ExecutionErrorNotice error={executionError} isRunning={isRunning} onRetry={() => void runSql()} />}
        {result?.kind === "query" && <QueryResults response={result} />}
        {result?.kind === "command" && <CommandResult affectedRows={result.affected_rows} />}
      </section>
    </section>
  );
}

function QueryResults({ response }: { response: Extract<SqlProfileResponse, { kind: "query" }> }) {
  const rowLabel = `${response.row_count} ${response.row_count === 1 ? "row" : "rows"} returned`;
  return (
    <section aria-labelledby="query-results-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-[var(--strata-text)]" id="query-results-heading">Query results</h2>
        <p className="text-sm tabular-nums text-[var(--strata-muted)]">{rowLabel}</p>
      </div>
      {response.rows.length === 0 ? (
        <p className="mt-3 rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-4 py-5 text-sm text-[var(--strata-muted)]">This query returned no rows.</p>
      ) : null}
      <div className="mt-3 overflow-x-auto rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">
        <table className="w-full min-w-max border-collapse text-left text-sm">
          <caption className="sr-only">SQL result table</caption>
          <thead className="border-b border-[var(--strata-border)] bg-slate-50 text-xs text-[var(--strata-subtle)]">
            <tr>
              {response.columns.map((column) => (
                <th className="whitespace-nowrap px-4 py-3 font-semibold" key={column.name} scope="col">
                  <span className="block text-[var(--strata-text)]">{column.name}</span>
                  <span className="mt-0.5 block font-mono font-normal">{column.type}{column.nullable ? " · nullable" : ""}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--strata-border)]">
            {response.rows.map((row, rowIndex) => (
              <tr className="bg-[var(--strata-surface)]" key={rowIndex}>
                {row.map((value, columnIndex) => <ResultCell key={columnIndex} value={value} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ResultCell({ value }: { value: SqlValue }) {
  if (value === null) {
    return <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-[var(--strata-subtle)]">NULL</td>;
  }
  if (typeof value === "number") {
    return <td className="whitespace-nowrap px-4 py-3 tabular-nums text-[var(--strata-text)]">{String(value)}</td>;
  }
  if (typeof value === "boolean") {
    return <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-[var(--strata-text)]">{String(value)}</td>;
  }
  return <td className="px-4 py-3 text-[var(--strata-text)]">{value}</td>;
}

function CommandResult({ affectedRows }: { affectedRows: number }) {
  return (
    <section aria-labelledby="command-result-heading" className="rounded-md border border-indigo-200 bg-indigo-50 px-4 py-4">
      <h2 className="text-sm font-semibold text-indigo-950" id="command-result-heading">Command completed</h2>
      <p className="mt-1 text-sm text-indigo-900">{affectedRows} {affectedRows === 1 ? "row" : "rows"} affected.</p>
    </section>
  );
}

function ExecutionErrorNotice({ error, isRunning, onRetry }: { error: ExecutionError; isRunning: boolean; onRetry: () => void }) {
  return (
    <section className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-4 text-rose-950" role="alert">
      <h2 className="text-sm font-semibold">{error.title}</h2>
      <p className="mt-1 text-sm">{error.message}</p>
      {error.code && <p className="mt-2 font-mono text-xs text-rose-800">{error.code}</p>}
      <button
        className="mt-3 text-sm font-semibold text-rose-800 underline decoration-rose-300 underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--strata-accent)] disabled:cursor-not-allowed disabled:opacity-60"
        disabled={isRunning}
        onClick={onRetry}
        type="button"
      >
        Retry
      </button>
    </section>
  );
}

function classifyExecutionError(error: unknown): ExecutionError {
  if (error instanceof StrataApiError) {
    if (error.code === "SQL_ERROR") {
      return { title: "SQL error", message: error.message, code: error.code };
    }
    if (error.status === 422) {
      return { title: "Invalid request", message: "The SQL request was rejected before execution." };
    }
    if (error.code === "INTERNAL_ERROR" || error.status >= 500) {
      return { title: "Database error", message: error.message };
    }
  }
  return { title: "Backend unavailable", message: "Could not reach the Strata backend. Check that it is running." };
}
