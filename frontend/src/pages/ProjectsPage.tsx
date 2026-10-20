import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createProject, deleteProject, deleteWorkspace, updateProject, updateWorkspace } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { PageHeader } from "../components/layout/PageHeader";
import type { Project } from "../types/product";

export function ProjectsPage() {
  const { projects, workspaces, workspaceTasks, members, currentUser, selectedWorkspaceId, selectProject, refreshWorkspace, status, error } = useProduct();
  const navigate = useNavigate();
  const workspaceRef = useRef(selectedWorkspaceId);
  workspaceRef.current = selectedWorkspaceId;
  const refreshCurrent = async (selection?: { workspaceId?: number; projectId?: number }) => {
    if (workspaceRef.current === selectedWorkspaceId) await refreshWorkspace(selection);
  };
  const workspace = workspaces.find((item) => item.id === selectedWorkspaceId);
  const owner = members.some((item) => item.user_id === currentUser.id && item.role === "OWNER");
  const [editing, setEditing] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { setEditing(null); setName(""); setDescription(""); setMessage(null); }, [selectedWorkspaceId]);
  useEffect(() => { setWorkspaceName(workspace?.name ?? ""); }, [workspace?.name]);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setMessage(null);
    try { await action(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not save changes."); }
    finally { setBusy(false); }
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || selectedWorkspaceId === null) { setMessage("Enter a project name."); return; }
    void perform(async () => {
      const input = { name: name.trim(), description: description.trim() || null };
      // Send only edited fields so another member's unrelated changes survive.
      const changes = editing ? {
        ...(input.name !== editing.name ? { name: input.name } : {}),
        ...(input.description !== editing.description ? { description: input.description } : {}),
      } : input;
      const saved = editing ? await updateProject(editing.id, changes) : await createProject(selectedWorkspaceId, input);
      setEditing(null); setName(""); setDescription("");
      await refreshCurrent({ workspaceId: selectedWorkspaceId, projectId: saved.id });
    });
  };
  const disabled = busy || status !== "ready";
  return <section className="page-container projects-page">
    <PageHeader eyebrow="Workspace planning" title="Projects" description="Organize related work, monitor real completion, and move into execution." />
    {error && <p className="mt-4 text-sm text-rose-800" role="alert">{error.message}</p>}
    {message && <p className="mt-4 text-sm text-rose-800" role="alert">{message}</p>}
    {status === "loading" && <p className="mt-4 text-sm">Loading workspace…</p>}
    {workspace && <>
      {owner && workspace.kind === "COLLABORATIVE" && <details className="workspace-settings" aria-label="Workspace settings"><summary>Workspace settings</summary><div>
        <label className="field-label" htmlFor="workspace-name">Workspace name</label><input className="input" id="workspace-name" maxLength={128} value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} disabled={disabled} /><div className="settings-actions"><button className="button button-secondary" disabled={disabled || !workspaceName.trim()} onClick={() => void perform(async () => { await updateWorkspace(workspace.id, workspaceName.trim()); await refreshCurrent(); })} type="button">Save workspace</button><button className="text-button danger-text" disabled={disabled} onClick={() => { if (window.confirm("Delete this workspace? Delete its projects first.")) void perform(async () => { await deleteWorkspace(workspace.id); await refreshCurrent(); }); }} type="button">Delete workspace</button></div>
      </div></details>}
      <form className="project-composer" onSubmit={save}><div className="composer-heading"><span className="project-card-icon">+</span><div><h2>{editing ? "Edit project" : "Create a project"}</h2><p>{editing ? "Update the project details without interrupting its work." : "Give related work a clear home in this workspace."}</p></div></div><div className="project-form-grid"><label>Project name<input className="input" id="project-name" maxLength={128} value={name} onChange={(event) => setName(event.target.value)} disabled={disabled} /></label><label>Description<textarea className="input" id="project-description" maxLength={1024} value={description} onChange={(event) => setDescription(event.target.value)} disabled={disabled} /></label></div><div className="composer-actions"><button className="button button-primary" disabled={disabled} type="submit">{editing ? "Save project" : "Create project"}</button>{editing && <button className="button button-secondary" disabled={busy} onClick={() => { setEditing(null); setName(""); setDescription(""); }} type="button">Cancel</button>}</div></form>
      <div className="projects-grid">{status === "ready" && projects.length === 0 && <p className="dashboard-empty">No projects yet. Create your first project above.</p>}{projects.map((project) => { const projectTasks = workspaceTasks[project.id] ?? []; const done = projectTasks.filter((task) => task.status === "DONE").length; const progress = projectTasks.length ? Math.round(done / projectTasks.length * 100) : 0; return <article className="project-tile" key={project.id}><div className="project-tile-top"><span className="project-card-icon">{project.name.slice(0,2).toUpperCase()}</span><span className="project-menu-label">{projectTasks.length} tasks</span></div><h2>{project.name}</h2><p>{project.description || "No description yet."}</p><div className="project-tile-progress"><span><b>{progress}%</b> complete</span><span>{done}/{projectTasks.length}</span></div><div className="progress-track"><i style={{ width: `${progress}%` }} /></div><div className="project-tile-actions"><button className="button button-secondary" disabled={disabled} onClick={() => { selectProject(project.id); navigate("/tasks"); }} type="button">Open tasks</button><button className="text-button" disabled={disabled} onClick={() => { setEditing(project); setName(project.name); setDescription(project.description ?? ""); setMessage(null); }} type="button">Edit project</button>{(project.created_by_user_id === currentUser.id || (owner && !members.some((item) => item.user_id === project.created_by_user_id && item.account_state === "ACTIVE"))) && <button className="text-button danger-text" disabled={disabled} onClick={() => { if (window.confirm("Delete this project? Delete its tasks first.")) void perform(async () => { await deleteProject(project.id); await refreshCurrent(); }); }} type="button">Delete project</button>}</div></article>; })}</div>
    </>}
  </section>;
}
