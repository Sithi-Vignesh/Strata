import { useEffect, useState } from "react";
import { TASK_PRIORITIES, TASK_STATUSES, type CreateTaskInput, type Task, type TaskPriority, type TaskStatus, type UpdateTaskInput, type User } from "../../types/product";

type FormValues = { title: string; description: string; status: TaskStatus; priority: TaskPriority; assignee: string };

export function TaskModal({ task, memberUsers, onClose, onCreate, onUpdate }: {
  task: Task | null;
  memberUsers: Record<number, User>;
  onClose: () => void;
  onCreate: (input: CreateTaskInput) => Promise<boolean>;
  onUpdate: (task: Task, input: UpdateTaskInput) => Promise<boolean>;
}) {
  const editing = task !== null;
  const [values, setValues] = useState<FormValues>(() => initialValues(task));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && !submitting) onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, submitting]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const title = values.title.trim();
    if (!title) { setError("Task title cannot be blank."); return; }
    setSubmitting(true);
    setError(null);
    try {
      if (task) await onUpdate(task, changedFields(task, { ...values, title }));
      else await onCreate({ title, description: values.description || null, status: values.status, priority: values.priority, assignee_user_id: assigneeId(values.assignee) });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save this task.");
    } finally { setSubmitting(false); }
  };

  return <div aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-labelledby="task-modal-title">
    <form className="max-h-[90svh] w-full max-w-xl overflow-y-auto rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-5 shadow-xl sm:p-6" onSubmit={(event) => void submit(event)}>
      <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-[var(--strata-text)]" id="task-modal-title">{editing ? "Edit task" : "New task"}</h2><p className="mt-1 text-sm text-[var(--strata-muted)]">{editing ? "Update the task details." : "Add work to this project."}</p></div><button aria-label="Close task form" className="rounded px-2 py-1 text-lg text-[var(--strata-muted)] hover:bg-[var(--strata-hover)]" disabled={submitting} onClick={onClose} type="button">×</button></div>
      <label className="mt-5 block text-sm font-semibold text-[var(--strata-text)]" htmlFor="task-title">Title</label><input className="mt-2 w-full rounded-md border border-[var(--strata-border)] px-3 py-2 text-sm" id="task-title" onChange={(event) => setValues((current) => ({ ...current, title: event.target.value }))} value={values.title} />
      <label className="mt-4 block text-sm font-semibold text-[var(--strata-text)]" htmlFor="task-description">Description</label><textarea className="mt-2 min-h-24 w-full rounded-md border border-[var(--strata-border)] px-3 py-2 text-sm" id="task-description" onChange={(event) => setValues((current) => ({ ...current, description: event.target.value }))} value={values.description} />
      <div className="mt-4 grid gap-4 sm:grid-cols-3"><SelectField label="Status" name="task-status" onChange={(value) => setValues((current) => ({ ...current, status: value as TaskStatus }))} options={TASK_STATUSES} value={values.status} /><SelectField label="Priority" name="task-priority" onChange={(value) => setValues((current) => ({ ...current, priority: value as TaskPriority }))} options={TASK_PRIORITIES} value={values.priority} /><label className="block text-sm font-semibold text-[var(--strata-text)]">Assignee<select className="mt-2 w-full rounded-md border border-[var(--strata-border)] px-3 py-2 text-sm" id="task-assignee" onChange={(event) => setValues((current) => ({ ...current, assignee: event.target.value }))} value={values.assignee}><option value="">Unassigned</option>{Object.values(memberUsers).map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label></div>
      {error && <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900" role="alert">{error}</p>}
      <div className="mt-6 flex justify-end gap-3"><button className="rounded-md px-3 py-2 text-sm font-semibold text-[var(--strata-muted)] hover:bg-[var(--strata-hover)]" disabled={submitting} onClick={onClose} type="button">Cancel</button><button className="rounded-md bg-[var(--strata-accent)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" disabled={submitting} type="submit">{submitting ? (editing ? "Saving…" : "Creating…") : (editing ? "Save changes" : "Create task")}</button></div>
    </form>
  </div>;
}

export function TaskDeleteConfirmation({ task, onCancel, onConfirm }: { task: Task; onCancel: () => void; onConfirm: () => Promise<boolean> }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => { setDeleting(true); setError(null); try { await onConfirm(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not delete this task."); } finally { setDeleting(false); } };
  return <div aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-labelledby="delete-task-title"><section className="w-full max-w-md rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-5 shadow-xl"><h2 className="text-lg font-semibold text-[var(--strata-text)]" id="delete-task-title">Delete task?</h2><p className="mt-2 text-sm text-[var(--strata-muted)]">Delete “{task.title}”? This cannot be undone.</p>{error && <p className="mt-4 text-sm text-rose-900" role="alert">{error}</p>}<div className="mt-6 flex justify-end gap-3"><button disabled={deleting} onClick={onCancel} type="button">Cancel</button><button className="rounded-md bg-rose-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" disabled={deleting} onClick={() => void confirm()} type="button">{deleting ? "Deleting…" : "Delete task"}</button></div></section></div>;
}

function initialValues(task: Task | null): FormValues { return task ? { title: task.title, description: task.description ?? "", status: task.status, priority: task.priority, assignee: task.assignee_user_id === null ? "" : String(task.assignee_user_id) } : { title: "", description: "", status: "TODO", priority: "MEDIUM", assignee: "" }; }
function assigneeId(value: string): number | null { return value === "" ? null : Number(value); }
function changedFields(task: Task, values: FormValues): UpdateTaskInput { const next: UpdateTaskInput = {}; const description = values.description || null; const assignee = assigneeId(values.assignee); if (values.title !== task.title) next.title = values.title; if (description !== task.description) next.description = description; if (values.status !== task.status) next.status = values.status; if (values.priority !== task.priority) next.priority = values.priority; if (assignee !== task.assignee_user_id) next.assignee_user_id = assignee; return next; }
function SelectField({ label, name, options, value, onChange }: { label: string; name: string; options: readonly string[]; value: string; onChange: (value: string) => void }) { return <label className="block text-sm font-semibold text-[var(--strata-text)]">{label}<select className="mt-2 w-full rounded-md border border-[var(--strata-border)] px-3 py-2 text-sm" id={name} onChange={(event) => onChange(event.target.value)} value={value}>{options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}</select></label>; }
