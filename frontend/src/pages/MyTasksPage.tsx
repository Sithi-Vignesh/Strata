import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listMyTasks } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { PageHeader } from "../components/layout/PageHeader";
import { DueDate } from "../components/tasks/DueDate";
import { PriorityBadge } from "../components/tasks/PriorityBadge";
import { StatusBadge } from "../components/tasks/StatusBadge";
import { EmptyState } from "../components/ui/EmptyState";
import type { AssignedTask, TaskPriority, TaskSort, TaskStatus } from "../types/product";
import { TaskFilters } from "./AllTasksPage";

const PAGE_SIZE = 20;
export function MyTasksPage() {
  const { refreshWorkspace, selectedWorkspaceId, workspaces } = useProduct(); const navigate = useNavigate(); const version = useRef(0);
  const [items, setItems] = useState<AssignedTask[]>([]), [total, setTotal] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(""), [debouncedQuery, setDebouncedQuery] = useState(""), [status, setStatus] = useState<"" | TaskStatus>(""), [priority, setPriority] = useState<"" | TaskPriority>(""), [dueAfter, setDueAfter] = useState(""), [dueBefore, setDueBefore] = useState(""), [sort, setSort] = useState<TaskSort>("updated_desc"), [offset, setOffset] = useState(0);
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300); return () => window.clearTimeout(timer); }, [query]);
  useEffect(() => { setOffset(0); }, [debouncedQuery, status, priority, dueAfter, dueBefore, sort, selectedWorkspaceId]);
  useEffect(() => { const current = ++version.current; if (selectedWorkspaceId === null) { setItems([]); setTotal(0); setLoading(false); setError(null); return; } setLoading(true); setError(null); void listMyTasks({ workspace_id: selectedWorkspaceId, query: debouncedQuery || undefined, status: status || undefined, priority: priority || undefined, due_after: dueAfter || undefined, due_before: dueBefore || undefined, sort, limit: PAGE_SIZE, offset }).then((page) => { if (!page || !Array.isArray(page.items)) throw new Error("Could not load your tasks."); if (current === version.current) { setItems(page.items); setTotal(page.total); } }, (reason) => { if (current === version.current) { setItems([]); setTotal(0); setError(reason instanceof Error ? reason.message : "Could not load your tasks."); } }).finally(() => { if (current === version.current) setLoading(false); }); return () => { ++version.current; }; }, [debouncedQuery, dueAfter, dueBefore, offset, priority, selectedWorkspaceId, sort, status]);
  const open = async (task: AssignedTask) => { try { await refreshWorkspace({ workspaceId: task.workspace_id, projectId: task.project_id }); navigate(`/tasks?task=${task.id}`); } catch { setError("That task is no longer accessible."); } };
  const clear = () => { setQuery(""); setStatus(""); setPriority(""); setDueAfter(""); setDueBefore(""); setSort("updated_desc"); };
  const filtered = Boolean(debouncedQuery || status || priority || dueAfter || dueBefore || sort !== "updated_desc");
  const workspace = workspaces.find((item) => item.id === selectedWorkspaceId);
  return <section className="page-container"><PageHeader eyebrow="Workspace focus" title="My Tasks" description={workspace ? `Assigned to you in ${workspace.name}.` : "Select a workspace to see your assigned tasks."} />
    <TaskFilters query={query} status={status} priority={priority} sort={sort} dueAfter={dueAfter} dueBefore={dueBefore} filtered={filtered} onQuery={setQuery} onStatus={setStatus} onPriority={setPriority} onSort={setSort} onDueAfter={setDueAfter} onDueBefore={setDueBefore} onClear={clear} />
    {error && <div className="alert alert-error" role="alert">{error}</div>}{loading && <p className="dashboard-empty">Loading your tasks…</p>}{!loading && !error && items.length === 0 && <EmptyState title={filtered ? "No tasks match these filters" : "You’re all caught up"} description={filtered ? "Clear or adjust filters to see more assigned work." : workspace ? `No tasks in ${workspace.name} are assigned to you.` : "Select a workspace to begin."} />}
    {!loading && items.length > 0 && <div className="task-list-panel">{items.map((task) => <button className="focus-task focus-task-rich" key={`${task.workspace_id}-${task.id}`} onClick={() => void open(task)} type="button"><span className="task-check" aria-hidden="true">{task.status === "DONE" ? "✓" : ""}</span><span className="focus-task-main"><strong>{task.title}</strong><small>{task.workspace_name} / {task.project_name}</small></span><StatusBadge status={task.status} /><PriorityBadge priority={task.priority} /><DueDate dueDate={task.due_date ?? null} status={task.status} /><span className="row-arrow" aria-hidden="true">›</span></button>)}</div>}
    {!loading && total > 0 && <div className="pagination"><span>{offset + 1}–{Math.min(offset + items.length, total)} of {total}</span><div><button className="button button-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">Previous</button><button className="button button-secondary" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">Next</button></div></div>}
  </section>;
}
