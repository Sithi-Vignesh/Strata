import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCommonDashboard } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { PageHeader } from "../components/layout/PageHeader";
import type { Dashboard } from "../types/product";

export function CommonDashboardPage() {
  const { currentUser, workspaces } = useProduct(); const navigate = useNavigate(); const version = useRef(0);
  const [data, setData] = useState<Dashboard | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null);
  const load = () => { const current = ++version.current; setLoading(true); setError(null); void getCommonDashboard().then((result) => { if (current === version.current) setData(result); }, (reason) => { if (current === version.current) setError(reason instanceof Error ? reason.message : "Could not load the dashboard."); }).finally(() => { if (current === version.current) setLoading(false); }); };
  useEffect(() => { load(); return () => { ++version.current; }; }, [workspaces]);
  return <section className="page-container overview-page"><PageHeader eyebrow="Account overview" title={`Welcome, ${currentUser.name.split(/\s+/)[0]}`} description="A secure summary across every workspace you can currently access." actions={<button className="button button-primary" onClick={() => navigate("/all-tasks")} type="button">View all tasks →</button>} />
    {loading && <p className="dashboard-empty">Loading account dashboard…</p>}{error && <div className="alert alert-error" role="alert">{error} <button className="text-button" onClick={load} type="button">Retry</button></div>}
    {data && !loading && <div className="overview-content"><div className="metric-grid"><Metric label="Workspaces" value={data.workspace_count} detail="Current memberships" /><Metric label="Projects" value={data.project_count} detail="Accessible portfolio" /><Metric label="All tasks" value={data.task_count} detail={`${data.completed_count} completed`} /><Metric label="Assigned to me" value={data.assigned_to_me} detail={`${data.overdue_count} overdue · ${data.upcoming_count} upcoming`} /></div>
      <div className="overview-primary-grid"><section className="dashboard-section"><div className="dashboard-section-heading"><div><span className="kicker">Overall progress</span><h2>Delivery status</h2></div><strong>{percent(data.completed_count, data.task_count)}%</strong></div><div className="dashboard-summary-body"><div className="progress-track"><i style={{ width: `${percent(data.completed_count, data.task_count)}%` }} /></div><p>{data.status_counts.TODO ?? 0} to do · {data.status_counts.IN_PROGRESS ?? 0} in progress · {data.status_counts.DONE ?? 0} done</p></div></section>
      <section className="dashboard-section"><div className="dashboard-section-heading"><div><span className="kicker">Attention</span><h2>Deadlines</h2></div></div><div className="dashboard-summary-body"><strong>{data.overdue_count}</strong><p>overdue open tasks</p><button className="text-button" onClick={() => navigate("/all-tasks")} type="button">Review account tasks →</button></div></section></div>
    </div>}
  </section>;
}
function Metric({ label, value, detail }: { label: string; value: number; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function percent(value: number, total: number) { return total === 0 ? 0 : Math.round(value / total * 100); }
