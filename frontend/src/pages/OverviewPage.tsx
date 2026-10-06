import { useEffect, useState } from "react";
import { getTaskStatusSummary } from "../api/tasks";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { StatusBadge } from "../components/tasks/StatusBadge";
import { TASK_STATUSES, type TaskStatusSummary } from "../types/task";

export function OverviewPage() {
  const [summary, setSummary] = useState<TaskStatusSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    void getTaskStatusSummary().then(
      (value) => {
        if (active) {
          setSummary(value);
          setLoading(false);
        }
      },
      () => {
        if (active) {
          setSummary(null);
          setError(true);
          setLoading(false);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);

  const retry = () => setAttempt((value) => value + 1);
  const total = summary ? Object.values(summary).reduce((sum, count) => sum + count, 0) : 0;

  return (
    <section className="max-w-6xl">
      <PageHeader description="Workspace activity and project progress at a glance." title="Overview" />
      <DataState error={error} loading={loading} loadingMessage="Loading workspace summary…" onRetry={retry} />
      {!loading && !error && summary && total > 0 && (
        <div className="mt-6 space-y-8">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryMetric label="Total tasks" value={total} />
            <SummaryMetric label="In progress" value={summary.IN_PROGRESS} />
            <SummaryMetric label="Blocked" value={summary.BLOCKED} />
            <SummaryMetric label="Done" value={summary.DONE} />
          </div>
          <section aria-labelledby="work-by-status-heading">
            <h2 className="text-sm font-semibold text-[var(--strata-text)]" id="work-by-status-heading">Work by status</h2>
            <div className="mt-3 divide-y divide-[var(--strata-border)] rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">
              {TASK_STATUSES.map((status) => (
                <div className="flex items-center justify-between gap-4 px-4 py-3" key={status}>
                  <StatusBadge status={status} />
                  <span className="text-sm font-semibold tabular-nums text-[var(--strata-text)]">{summary[status]}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
      {!loading && !error && (!summary || total === 0) && <p className="py-10 text-sm text-[var(--strata-muted)]">No task data is available yet.</p>}
    </section>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-4 py-4">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--strata-subtle)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-[var(--strata-text)]">{value}</p>
    </article>
  );
}
