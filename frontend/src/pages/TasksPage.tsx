import { useEffect, useState } from "react";
import { createTask, deleteTask, updateTask } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskDeleteConfirmation, TaskModal } from "../components/tasks/TaskModal";
import { TaskDetailModal } from "../components/tasks/TaskDetailModal";
import { TaskTable } from "../components/tasks/TaskTable";
import type { CreateTaskInput, Task, UpdateTaskInput } from "../types/product";

export function TasksPage() {
  const { tasks, currentUser, memberUsers, selectedWorkspaceId, selectedProjectId, status, retry, refreshTasks } = useProduct();
  const [editing, setEditing] = useState<Task | null | "new">(null);
  const [deleting, setDeleting] = useState<Task | null>(null);
  const [detail, setDetail] = useState<Task | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const loading = status === "loading";
  const error = status === "error";
  useEffect(() => {
    if (editing !== null && editing !== "new" && editing.project_id !== selectedProjectId) setEditing(null);
    if (deleting !== null && deleting.project_id !== selectedProjectId) setDeleting(null);
    if (detail !== null && detail.project_id !== selectedProjectId) setDetail(null);
  }, [selectedProjectId, editing, deleting, detail]);
  const afterMutation = async (action: () => Promise<unknown>, verb: string) => { await action(); try { await refreshTasks(); return true; } catch { setNotice(`Task was ${verb}, but the latest task list could not be refreshed.`); return false; } };
  const create = async (input: CreateTaskInput) => { if (selectedProjectId === null) throw new Error("Select a project before creating a task."); return afterMutation(() => createTask(selectedProjectId, input), "created"); };
  const update = (task: Task, input: UpdateTaskInput) => Object.keys(input).length === 0 ? Promise.resolve(true) : afterMutation(() => updateTask(task.id, input), "saved");
  const remove = async () => { if (deleting === null) return true; const result = await afterMutation(() => deleteTask(deleting.id), "deleted"); setDeleting(null); return result; };
  return <section className="max-w-6xl"><PageHeader description="Track and review work across the Strata workspace." title="Tasks" />
    {!loading && !error && selectedProjectId !== null && <div className="mt-6 flex justify-end"><button className="rounded-md bg-[var(--strata-accent)] px-4 py-2 text-sm font-semibold text-white" onClick={() => { setNotice(null); setEditing("new"); }} type="button">New task</button></div>}
    {notice && <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status">{notice}</div>}
    <DataState error={error} errorMessage="Could not load tasks for this project." loading={loading} loadingMessage="Loading tasks…" onRetry={retry} />
    {!loading && !error && selectedWorkspaceId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No workspaces available.</p>}
    {!loading && !error && selectedWorkspaceId !== null && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}
    {!loading && !error && selectedProjectId !== null && (tasks.length ? <TaskTable memberUsers={memberUsers} onDelete={setDeleting} onEdit={setEditing} onOpen={setDetail} tasks={tasks} /> : <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>)}
    {editing !== null && <TaskModal memberUsers={memberUsers} onClose={() => setEditing(null)} onCreate={create} onUpdate={update} task={editing === "new" ? null : editing} />}{deleting && <TaskDeleteConfirmation onCancel={() => setDeleting(null)} onConfirm={remove} task={deleting} />}{detail && <TaskDetailModal currentUser={currentUser} memberUsers={memberUsers} onClose={() => setDetail(null)} onEdit={(task) => { setDetail(null); setEditing(task); }} task={detail} />}
  </section>;
}
