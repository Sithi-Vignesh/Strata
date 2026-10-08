import { Link, NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { getHealth } from "../../api/strata";
import { addWorkspaceMember, createWorkspace, removeWorkspaceMember, transferWorkspaceOwnership } from "../../api/product";
import { useOptionalProduct } from "../../app/ProductContext";
import { useAuth } from "../../app/AuthContext";
import { NavIcon, type NavIconName } from "../icons/NavIcon";

type ConnectionState = "checking" | "connected" | "unavailable";

const navigation = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Overview", icon: "overview" },
      { to: "/tasks", label: "Tasks", icon: "tasks" },
      { to: "/board", label: "Board", icon: "board" },
    ],
  },
  {
    label: "Database",
    items: [
      { to: "/sql", label: "SQL Console", icon: "sql" },
      { to: "/engine", label: "Engine", icon: "engine" },
    ],
  },
] as const satisfies ReadonlyArray<{
  label: string;
  items: ReadonlyArray<{ to: string; label: string; icon: NavIconName }>;
}>;

const healthCopy: Record<ConnectionState, string> = {
  checking: "Checking backend…",
  connected: "Backend: Connected",
  unavailable: "Backend: Unavailable",
};

const healthDot: Record<ConnectionState, string> = {
  checking: "bg-slate-400",
  connected: "bg-emerald-500",
  unavailable: "bg-rose-500",
};

export function AppShell() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const auth = useAuth();

  useEffect(() => {
    let active = true;
    void getHealth().then(
      () => active && setConnection("connected"),
      () => active && setConnection("unavailable"),
    );
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="min-h-svh bg-[var(--strata-canvas)] text-[var(--strata-text)] md:flex">
      <header className="border-b border-[var(--strata-border)] bg-[var(--strata-surface)] md:hidden">
        <div className="flex items-center justify-between px-5 py-4">
          <Wordmark />
          <div className="flex items-center gap-4"><HealthStatus connection={connection} /><AccountControls auth={auth} /></div>
        </div>
        <nav aria-label="Primary navigation" className="overflow-x-auto border-t border-[var(--strata-border)] px-3">
          <div className="flex min-w-max items-center gap-5 py-2">
            {navigation.map((group) => (
              <div className="flex items-center gap-1" key={group.label}>
                <span className="px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]">{group.label}</span>
                {group.items.map((item) => <NavigationLink item={item} key={item.to} />)}
              </div>
            ))}
          </div>
        </nav>
      </header>

      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 flex-col border-r border-[var(--strata-border)] bg-[var(--strata-surface)] md:flex">
        <div className="px-6 py-6"><Wordmark /></div>
        <WorkspaceSelector />
        <nav aria-label="Primary navigation" className="min-h-0 flex-1 overflow-y-auto px-3 pb-6">
          {navigation.map((group) => (
            <section className="mt-6 first:mt-0" key={group.label}>
              <h2 className="px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]">{group.label}</h2>
              <div className="mt-2 space-y-1">
                {group.items.map((item) => <NavigationLink item={item} key={item.to} />)}
              </div>
            </section>
          ))}
        </nav>
        <footer className="border-t border-[var(--strata-border)] px-6 py-5">
          <AccountControls auth={auth} />
          <HealthStatus connection={connection} />
          <p className="mt-3 text-xs text-[var(--strata-subtle)]">Powered by Strata DB</p>
        </footer>
      </aside>

      <main className="min-w-0 flex-1 px-5 py-8 sm:px-8 sm:py-10 lg:px-10">
        {auth.user && auth.error && <div className="mb-5 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-950" role="alert">Could not sign you out. Please try again.</div>}
        <Outlet />
      </main>
    </div>
  );
}

function AccountControls({ auth }: { auth: ReturnType<typeof useAuth> }) {
  if (auth.user === null) return null;
  return <div className="flex items-center justify-between gap-2"><span className="truncate text-xs font-medium text-[var(--strata-text)]">{auth.user.name}</span><button className="text-xs font-semibold text-[var(--strata-accent)] disabled:opacity-60" disabled={auth.logoutPending} onClick={() => { void auth.logout(); }} type="button">{auth.logoutPending ? "Signing out…" : "Sign out"}</button></div>;
}

function Wordmark() {
  return <Link className="text-sm font-bold tracking-[0.16em] text-[var(--strata-text)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--strata-accent)]" to="/">STRATA</Link>;
}

function WorkspaceSelector() {
  const product = useOptionalProduct();
  if (product === null) return null;
  const { workspaces, projects, members, currentUser, selectedWorkspaceId, selectedProjectId, selectWorkspace, selectProject, refreshWorkspace, status } = product;
  const [name, setName] = useState("");
  const [memberId, setMemberId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const selected = workspaces.find((workspace) => workspace.id === selectedWorkspaceId);
  const owner = members.some((member) => member.user_id === currentUser.id && member.role === "OWNER");
  const mutate = async (action: () => Promise<unknown>, success: string) => { try { await action(); await refreshWorkspace(); setMessage(success); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not update workspace membership."); } };
  const add = () => { const userId = Number(memberId); if (!Number.isInteger(userId) || userId < 1 || selectedWorkspaceId === null) { setMessage("Enter a valid user ID."); return; } void mutate(() => addWorkspaceMember(selectedWorkspaceId, userId), "Member added."); };
  const create = () => { const value = name.trim(); if (!value) { setMessage("Enter a workspace name."); return; } void (async () => { try { const workspace = await createWorkspace(value); await refreshWorkspace(); selectWorkspace(workspace.id); setName(""); setMessage("Collaborative workspace created."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not create workspace."); } })(); };
  return (
    <div className="px-6 pb-2">
      <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]" htmlFor="workspace-selector">Workspace</label>
      <select className="mt-1 w-full rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-2 py-1.5 text-xs text-[var(--strata-text)] disabled:opacity-60" disabled={status === "loading" || workspaces.length === 0} id="workspace-selector" onChange={(event) => selectWorkspace(Number(event.target.value))} value={selectedWorkspaceId ?? ""}>
        {workspaces.length === 0 ? <option value="">No workspaces</option> : workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
      </select>
      <label className="mt-3 block text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]" htmlFor="project-selector">Project</label>
      <select className="mt-1 w-full rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-2 py-1.5 text-xs text-[var(--strata-text)] disabled:opacity-60" disabled={status === "loading" || projects.length === 0} id="project-selector" onChange={(event) => selectProject(Number(event.target.value))} value={selectedProjectId ?? ""}>
        {projects.length === 0 ? <option value="">No projects</option> : projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
      <div className="mt-4 border-t border-[var(--strata-border)] pt-3">
        <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]" htmlFor="new-workspace">New collaborative workspace</label>
        <div className="mt-1 flex gap-1"><input className="min-w-0 flex-1 rounded-md border border-[var(--strata-border)] px-2 py-1 text-xs" id="new-workspace" onChange={(event) => setName(event.target.value)} value={name} /><button className="rounded-md bg-[var(--strata-accent)] px-2 text-xs font-semibold text-white" onClick={create} type="button">Create</button></div>
      </div>
      {selected?.kind === "COLLABORATIVE" && <section aria-label="Workspace members" className="mt-4 border-t border-[var(--strata-border)] pt-3"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--strata-subtle)]">Members {owner && <span className="text-[var(--strata-accent)]">· Owner</span>}</p><ul className="mt-2 space-y-1">{members.map((member) => <li className="flex items-center justify-between gap-1 text-xs" key={member.user_id}><span className="truncate">{member.name} <span className="text-[var(--strata-subtle)]">({member.role})</span></span>{owner && member.role === "MEMBER" && <span className="flex gap-1"><button className="text-[var(--strata-accent)]" onClick={() => { if (window.confirm(`Transfer ownership to ${member.name}?`)) void mutate(() => transferWorkspaceOwnership(selected.id, member.user_id), "Ownership transferred."); }} type="button">Make owner</button><button className="text-rose-700" onClick={() => { if (window.confirm(`Remove ${member.name}? Their tasks will be unassigned.`)) void mutate(() => removeWorkspaceMember(selected.id, member.user_id), "Member removed and their tasks unassigned."); }} type="button">Remove</button></span>}</li>)}</ul>{owner && <div className="mt-2 flex gap-1"><input aria-label="Member user ID" className="min-w-0 flex-1 rounded-md border border-[var(--strata-border)] px-2 py-1 text-xs" inputMode="numeric" onChange={(event) => setMemberId(event.target.value)} placeholder="User ID" value={memberId} /><button className="rounded-md border border-[var(--strata-border)] px-2 text-xs font-semibold" onClick={add} type="button">Add</button></div>}</section>}
      {message && <p className="mt-2 text-xs text-[var(--strata-muted)]" role="status">{message}</p>}
    </div>
  );
}

function NavigationLink({ item }: { item: { to: string; label: string; icon: NavIconName } }) {
  return (
    <NavLink
      className={({ isActive }) => [
        "flex h-9 items-center gap-3 rounded-md px-3 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--strata-accent)]",
        isActive ? "bg-[var(--strata-accent-soft)] font-semibold text-[var(--strata-accent)]" : "font-medium text-[var(--strata-muted)] hover:bg-[var(--strata-hover)] hover:text-[var(--strata-text)]",
      ].join(" ")}
      end={item.to === "/"}
      to={item.to}
    >
      <NavIcon className="size-4 shrink-0" name={item.icon} />
      <span>{item.label}</span>
    </NavLink>
  );
}

function HealthStatus({ connection }: { connection: ConnectionState }) {
  return (
    <span aria-live="polite" className="flex items-center gap-2 text-xs font-medium text-[var(--strata-muted)]">
      <span aria-hidden="true" className={`size-1.5 rounded-full ${healthDot[connection]}`} />
      {healthCopy[connection]}
    </span>
  );
}
