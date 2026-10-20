import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { getHealth } from "../../api/strata";
import { addWorkspaceMember, createWorkspace, getUnreadNotificationCount } from "../../api/product";
import { useOptionalProduct } from "../../app/ProductContext";
import { useAuth } from "../../app/AuthContext";
import { useTheme } from "../../app/ThemeContext";
import { Avatar } from "../ui/Avatar";
import { NavIcon, type NavIconName } from "../icons/NavIcon";
import { CommandPalette } from "./CommandPalette";

type ConnectionState = "checking" | "connected" | "unavailable";

const navigation = [
  { label: "Global", items: [
    { to: "/", label: "Common Dashboard", icon: "overview" },
    { to: "/all-tasks", label: "All Tasks", icon: "list" },
    { to: "/inbox", label: "Inbox", icon: "inbox" },
  ] },
  { label: "Workspace", items: [
    { to: "/workspace", label: "Workspace Dashboard", icon: "overview" },
    { to: "/my-tasks", label: "My Tasks", icon: "tasks" },
    { to: "/projects", label: "Projects", icon: "projects" },
    { to: "/tasks", label: "Tasks", icon: "list" },
    { to: "/board", label: "Board", icon: "board" },
    { to: "/members", label: "Members", icon: "members" },
  ] },
  { label: "Database", items: [
    { to: "/sql", label: "SQL Console", icon: "sql" },
    { to: "/engine", label: "Engine", icon: "engine" },
  ] },
] as const satisfies ReadonlyArray<{ label: string; items: ReadonlyArray<{ to: string; label: string; icon: NavIconName }> }>;

const routeTitles: Record<string, string> = { "/": "Common Dashboard", "/workspace": "Workspace Dashboard", "/all-tasks": "All Tasks", "/my-tasks": "My Tasks", "/inbox": "Inbox", "/projects": "Projects", "/tasks": "Tasks", "/board": "Board", "/members": "Members", "/sql": "SQL Lab", "/engine": "Database Engine", "/settings": "Settings" };

export function AppShell() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const unreadVersion = useRef(0);
  const auth = useAuth();
  const product = useOptionalProduct();
  const location = useLocation();
  const workspace = product?.workspaces.find((item) => item.id === product.selectedWorkspaceId);
  const project = product?.projects.find((item) => item.id === product.selectedProjectId);

  useEffect(() => { let active = true; void getHealth().then(() => active && setConnection("connected"), () => active && setConnection("unavailable")); return () => { active = false; }; }, []);
  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => { if (!auth.user) { ++unreadVersion.current; setUnreadCount(0); return; } let active = true; const refresh = () => { const version = ++unreadVersion.current; void getUnreadNotificationCount().then((result) => { if (active && version === unreadVersion.current) setUnreadCount(result.unread_count); }, () => { if (active && version === unreadVersion.current) setUnreadCount(0); }); }; refresh(); window.addEventListener("focus", refresh); window.addEventListener("strata:notifications-changed", refresh); return () => { active = false; ++unreadVersion.current; window.removeEventListener("focus", refresh); window.removeEventListener("strata:notifications-changed", refresh); }; }, [auth.user, location.pathname]);

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
      <div className="sidebar-brand"><Wordmark /><button aria-label="Close navigation" className="icon-button mobile-only" onClick={() => setMobileOpen(false)} type="button">×</button></div>
      <WorkspaceSelector />
      <nav aria-label="Primary navigation" className="sidebar-nav">{navigation.map((group) => <section className="nav-group" key={group.label}><h2>{group.label}</h2><div>{group.items.map((item) => <NavigationLink item={item} key={item.to} unreadCount={item.to === "/inbox" ? unreadCount : 0} />)}</div></section>)}</nav>
      <div className="sidebar-footer">
        <NavLink className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`} to="/settings"><NavIcon name="settings" /><span>Settings & appearance</span></NavLink>
        {auth.user && <div className="account-summary"><Avatar name={auth.user.name} /><div><strong>{auth.user.name}</strong><span>{auth.user.email}</span></div><button aria-label="Sign out" className="icon-button" disabled={auth.logoutPending} onClick={() => void auth.logout()} title="Sign out" type="button">↗</button></div>}
        <HealthStatus connection={connection} />
      </div>
    </aside>
    {mobileOpen && <button aria-label="Close navigation" className="sidebar-scrim" onClick={() => setMobileOpen(false)} type="button" />}
    <div className="app-main">
      <header className="topbar">
        <button aria-label="Open navigation" className="icon-button menu-button" onClick={() => setMobileOpen(true)} type="button"><NavIcon name="menu" /></button>
        <div className="breadcrumbs"><span>{["/", "/all-tasks", "/inbox"].includes(location.pathname) ? "Global" : (workspace?.name ?? "No workspace")}</span>{project && ["/tasks", "/board"].includes(location.pathname) && <><b>/</b><span>{project.name}</span></>}<b>/</b><strong>{routeTitles[location.pathname] ?? "Workspace"}</strong></div>
        <div className="topbar-actions"><HealthStatus connection={connection} compact />{auth.user && <button aria-label="Open command palette" className="command-trigger" onClick={() => window.dispatchEvent(new Event("strata:open-command-palette"))} title="Open command palette (Ctrl+K)" type="button"><span aria-hidden="true">⌕</span><kbd>Ctrl K</kbd></button>}<ThemeButton />{auth.user && <><Avatar name={auth.user.name} size="sm" /><button aria-label="Sign out" className="icon-button mobile-account-action" disabled={auth.logoutPending} onClick={() => void auth.logout()} type="button">↗</button></>}</div>
      </header>
      <nav aria-label="Mobile navigation" className="mobile-nav">{navigation.map((group) => <div key={group.label}>{group.items.map((item) => <NavigationLink item={item} key={item.to} unreadCount={item.to === "/inbox" ? unreadCount : 0} />)}</div>)}</nav>
      <main id="main-content" className="content-area">
        {auth.user && auth.error && <div className="alert alert-error" role="alert">Could not sign you out. Please try again.</div>}
        <Outlet />
      </main>
    </div>
    {auth.user && <CommandPalette />}
  </div>;
}

function Wordmark() { return <Link className="wordmark" to="/"><span className="wordmark-mark" aria-hidden="true"><i /><i /><i /></span><span>STRATA</span></Link>; }

function WorkspaceSelector() {
  const product = useOptionalProduct();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const selectorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!open) return; const close = (event: PointerEvent) => { if (!selectorRef.current?.contains(event.target as Node)) setOpen(false); }; const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); }; document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape); return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); }; }, [open]);
  if (product === null) return <div className="workspace-switcher workspace-switcher-static"><span className="workspace-icon">DB</span><span><strong>Strata Engine</strong><small>Developer workspace</small></span></div>;
  const { workspaces, members, currentUser, selectedWorkspaceId, selectWorkspace, refreshWorkspace, status } = product;
  const selected = workspaces.find((workspace) => workspace.id === selectedWorkspaceId);
  const owner = members.some((member) => member.user_id === currentUser.id && member.role === "OWNER");
  const create = async () => { const value = name.trim(); if (!value) { setMessage("Enter a workspace name."); return; } try { const workspace = await createWorkspace(value); await refreshWorkspace({ workspaceId: workspace.id }); setName(""); setCreating(false); setMessage(null); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not create workspace."); } };
  const add = async () => { const email = memberEmail.trim(); if (!/^\S+@\S+\.\S+$/.test(email) || selectedWorkspaceId === null) { setMessage("Enter a valid member email."); return; } try { await addWorkspaceMember(selectedWorkspaceId, email); await refreshWorkspace(); setMemberEmail(""); setMessage("Member added."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not add member."); } };
  return <div className="workspace-control" ref={selectorRef}>
    <div className="workspace-switcher"><span className="workspace-icon">{selected?.name.slice(0, 2).toUpperCase() ?? "—"}</span><button aria-controls="workspace-options" aria-expanded={open} aria-haspopup="listbox" aria-label={`Workspace: ${selected?.name ?? "none selected"}`} className="workspace-selector-trigger" disabled={status === "loading" || workspaces.length === 0} id="workspace-selector-trigger" onClick={() => setOpen((value) => !value)} onKeyDown={(event) => { if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); window.setTimeout(() => document.querySelector<HTMLElement>("#workspace-options [role='option']")?.focus(), 0); } }} type="button"><span><strong title={selected?.name}>{selected?.name ?? "No workspaces"}</strong><small>{selected?.kind === "COLLABORATIVE" ? `${members.length} members` : "Personal workspace"}</small></span><i aria-hidden="true">⌄</i></button><select aria-hidden="true" className="workspace-selector-native" disabled={status === "loading" || workspaces.length === 0} id="workspace-selector" onChange={(event) => selectWorkspace(Number(event.target.value))} tabIndex={-1} value={selectedWorkspaceId ?? ""}>{workspaces.length === 0 ? <option value="">No workspaces</option> : workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select><button aria-label="Create workspace" className="workspace-add" onClick={() => { setOpen(false); setCreating((value) => !value); }} type="button">+</button></div>
    {open && <div className="workspace-options" id="workspace-options" onKeyDown={(event) => { if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return; event.preventDefault(); const options = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[role='option']")); const index = options.indexOf(document.activeElement as HTMLElement); options[(index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length]?.focus(); }} role="listbox">{workspaces.map((workspace) => <button aria-selected={workspace.id === selectedWorkspaceId} key={workspace.id} onClick={() => { selectWorkspace(workspace.id); setOpen(false); }} role="option" title={workspace.name} type="button"><span className="workspace-option-icon">{workspace.name.slice(0, 2).toUpperCase()}</span><span><strong>{workspace.name}</strong><small>{workspace.kind === "COLLABORATIVE" ? "Collaborative workspace" : "Personal workspace"}</small></span>{workspace.id === selectedWorkspaceId && <i aria-hidden="true">✓</i>}</button>)}</div>}
    {creating && <div className="workspace-create"><label htmlFor="new-workspace">New collaborative workspace</label><div><input className="input" id="new-workspace" onChange={(event) => setName(event.target.value)} placeholder="Workspace name" value={name} /><button className="button button-primary" onClick={() => void create()} type="button">Create</button></div></div>}
    {selected?.kind === "COLLABORATIVE" && owner && <div className="sidebar-quick-add"><input aria-label="Member email" onChange={(event) => setMemberEmail(event.target.value)} placeholder="Add by email" type="email" value={memberEmail} /><button onClick={() => void add()} type="button">Add</button></div>}
    {message && <p className="workspace-message" role="status">{message}</p>}
  </div>;
}

function NavigationLink({ item, unreadCount = 0 }: { item: { to: string; label: string; icon: NavIconName }; unreadCount?: number }) { return <NavLink className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`} end={item.to === "/"} to={item.to}><NavIcon name={item.icon} /><span>{item.label}</span>{unreadCount > 0 && <span aria-label={`${unreadCount} unread notifications`} className="nav-count">{unreadCount > 99 ? "99+" : unreadCount}</span>}</NavLink>; }
function ThemeButton() { const { resolvedTheme, setPreference } = useTheme(); return <button aria-label={`Switch to ${resolvedTheme === "dark" ? "light" : "dark"} theme`} className="icon-button" onClick={() => setPreference(resolvedTheme === "dark" ? "light" : "dark")} title="Toggle theme" type="button">{resolvedTheme === "dark" ? "☀" : "☾"}</button>; }
function HealthStatus({ connection, compact = false }: { connection: ConnectionState; compact?: boolean }) { return <span aria-live="polite" className={`health-status ${compact ? "health-compact" : ""}`}><i className={`health-dot health-${connection}`} />{connection === "checking" ? "Checking backend…" : connection === "connected" ? "Backend: Connected" : "Backend: Unavailable"}</span>; }
