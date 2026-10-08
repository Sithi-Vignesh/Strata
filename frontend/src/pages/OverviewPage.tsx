import { useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { PriorityBadge } from "../components/tasks/PriorityBadge";
import { StatusBadge } from "../components/tasks/StatusBadge";
import { TASK_PRIORITIES, TASK_STATUSES, type Project, type Task } from "../types/product";

export function OverviewPage() {
  const { projects, workspaceTasks, currentUser, selectedWorkspaceId, status, retry, selectProject } = useProduct();
  const navigate = useNavigate();
  const tasks = Object.values(workspaceTasks).flat();
  const done = tasks.filter((task) => task.status === "DONE").length;
  const assigned = tasks.filter((task) => task.assignee_user_id === currentUser.id);
  const openProject = (projectId: number) => { selectProject(projectId); navigate("/tasks"); };
  const loading = status === "loading";
  const error = status === "error";
  return <section className="max-w-6xl">
    <PageHeader description="Live workspace progress, priorities, and your assigned work." title="Dashboard" />
    <DataState error={error} errorMessage="Could not load your Strata dashboard." loading={loading} loadingMessage="Loading dashboard…" onRetry={retry} />
    {!loading && !error && selectedWorkspaceId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No workspaces available.</p>}
    {!loading && !error && selectedWorkspaceId !== null && <div className="mt-6 space-y-8">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><Metric label="Projects" value={projects.length} /><Metric label="Total tasks" value={tasks.length} /><Metric label="Completed" value={done} /><Metric label="Completion" value={`${percent(done, tasks.length)}%`} /></div>
      <div className="grid gap-6 lg:grid-cols-2"><Group title="Tasks by status">{TASK_STATUSES.map((item) => <Count key={item} label={<StatusBadge status={item} />} value={tasks.filter((task) => task.status === item).length} />)}</Group><Group title="Tasks by priority">{TASK_PRIORITIES.map((item) => <Count key={item} label={<PriorityBadge priority={item} />} value={tasks.filter((task) => task.priority === item).length} />)}</Group></div>
      <section aria-labelledby="my-tasks"><h2 className="text-sm font-semibold" id="my-tasks">My Tasks</h2>{assigned.length === 0 ? <p className="mt-3 rounded-md border border-[var(--strata-border)] p-4 text-sm text-[var(--strata-muted)]">No tasks are assigned to you in this workspace.</p> : <div className="mt-3 divide-y rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">{assigned.map((task) => <button className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[var(--strata-hover)]" key={task.id} onClick={() => openProject(task.project_id)} type="button"><span><span className="block text-sm font-medium">{task.title}</span><span className="text-xs text-[var(--strata-subtle)]">{projectName(projects, task.project_id)}</span></span><span className="flex gap-2"><StatusBadge status={task.status} /><PriorityBadge priority={task.priority} /></span></button>)}</div>}</section>
      <section aria-labelledby="project-progress"><h2 className="text-sm font-semibold" id="project-progress">Project Progress</h2>{projects.length === 0 ? <p className="mt-3 rounded-md border border-[var(--strata-border)] p-4 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p> : <div className="mt-3 grid gap-3 sm:grid-cols-2">{projects.map((project) => <ProjectProgress key={project.id} onOpen={openProject} project={project} tasks={workspaceTasks[project.id] ?? []} />)}</div>}</section>
    </div>}
  </section>;
}

function Metric({ label, value }: { label: string; value: string | number }) { return <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-4"><p className="text-xs font-semibold uppercase tracking-[.08em] text-[var(--strata-subtle)]">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p></article>; }
function Group({ title, children }: { title: string; children: ReactNode }) { return <section><h2 className="text-sm font-semibold">{title}</h2><div className="mt-3 divide-y rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">{children}</div></section>; }
function Count({ label, value }: { label: ReactNode; value: number }) { return <div className="flex items-center justify-between px-4 py-3"><span>{label}</span><span className="text-sm font-semibold tabular-nums">{value}</span></div>; }
function ProjectProgress({ project, tasks, onOpen }: { project: Project; tasks: Task[]; onOpen: (id: number) => void }) { const done = tasks.filter((task) => task.status === "DONE").length; const completion = percent(done, tasks.length); return <button className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-4 text-left hover:bg-[var(--strata-hover)]" onClick={() => onOpen(project.id)} type="button"><div className="flex justify-between gap-3"><span className="font-medium">{project.name}</span><span className="text-sm text-[var(--strata-subtle)]">{done}/{tasks.length}</span></div><div className="mt-3 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-[var(--strata-accent)]" style={{ width: `${completion}%` }} /></div><p className="mt-2 text-xs text-[var(--strata-subtle)]">{tasks.length === 0 ? "No tasks yet" : `${completion}% complete`}</p></button>; }
function percent(done: number, total: number) { return total === 0 ? 0 : Math.round((done / total) * 100); }
function projectName(projects: Project[], projectId: number) { return projects.find((project) => project.id === projectId)?.name ?? "Project"; }
