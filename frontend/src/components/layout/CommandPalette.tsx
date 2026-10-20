import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useOptionalProduct } from "../../app/ProductContext";
import { useTheme, type ThemePreference } from "../../app/ThemeContext";

type Command = { id: string; label: string; keywords?: string; run: () => void };
export function CommandPalette() {
  const [open, setOpen] = useState(false), [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null), previousFocus = useRef<HTMLElement | null>(null), navigate = useNavigate(), product = useOptionalProduct(), { setPreference } = useTheme();
  const commands = useMemo<Command[]>(() => {
    const routes = [["home", "Go to Common Dashboard", "/"], ["all-tasks", "Go to All Tasks", "/all-tasks"], ["workspace", "Go to Workspace Dashboard", "/workspace"], ["tasks", "Go to My Tasks", "/my-tasks"], ["projects", "Go to Projects", "/projects"], ["inbox", "Go to Inbox", "/inbox"], ["members", "Go to Members", "/members"], ["sql", "Go to SQL Lab", "/sql"]].map(([id, label, path]) => ({ id, label, run: () => navigate(path) }));
    const workspaceCommands = product?.workspaces.map((workspace) => ({ id: `workspace-${workspace.id}`, label: `Switch workspace: ${workspace.name}`, keywords: "workspace", run: () => { product.selectWorkspace(workspace.id); navigate("/workspace"); } })) ?? [];
    const themeCommands = (["light", "dark", "system"] as ThemePreference[]).map((theme) => ({ id: `theme-${theme}`, label: `Appearance: ${theme}`, keywords: "theme appearance", run: () => setPreference(theme) }));
    const create = product?.selectedProjectId ? [{ id: "create-task", label: "Create task", keywords: "new add", run: () => navigate("/tasks?create=1") }] : [];
    return [...routes, ...create, ...workspaceCommands, ...themeCommands];
  }, [navigate, product, setPreference]);
  const visible = commands.filter((command) => `${command.label} ${command.keywords ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  const close = () => { setOpen(false); setQuery(""); setActive(0); window.setTimeout(() => previousFocus.current?.focus(), 0); };
  useEffect(() => { const show = () => { previousFocus.current = document.activeElement as HTMLElement | null; setOpen(true); }; const keydown = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !editableTarget(event.target)) { event.preventDefault(); if (open) close(); else show(); return; } if (event.key === "Escape" && open) { event.preventDefault(); close(); return; } if (editableTarget(event.target) || document.querySelector("[role='dialog']")) return; if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === "c" && product?.selectedProjectId) navigate("/tasks?create=1"); }; window.addEventListener("keydown", keydown); window.addEventListener("strata:open-command-palette", show); return () => { window.removeEventListener("keydown", keydown); window.removeEventListener("strata:open-command-palette", show); }; }, [navigate, open, product?.selectedProjectId]);
  useEffect(() => { if (open) window.setTimeout(() => input.current?.focus(), 0); }, [open]);
  useEffect(() => setActive(0), [query]);
  if (!open) return null;
  const run = (command: Command) => { command.run(); close(); };
  return <div className="command-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><section aria-label="Command palette" aria-modal="true" className="command-palette" role="dialog"><label><span className="sr-only">Search commands</span><input aria-activedescendant={visible[active] ? `command-${visible[active].id}` : undefined} aria-controls="command-list" aria-expanded="true" autoComplete="off" onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "ArrowDown") { event.preventDefault(); setActive((index) => Math.min(index + 1, visible.length - 1)); } else if (event.key === "ArrowUp") { event.preventDefault(); setActive((index) => Math.max(index - 1, 0)); } else if (event.key === "Enter" && visible[active]) { event.preventDefault(); run(visible[active]); } }} placeholder="Type a command…" ref={input} role="combobox" value={query} /></label><div id="command-list" role="listbox">{visible.map((command, index) => <button aria-selected={index === active} className={index === active ? "command-active" : ""} id={`command-${command.id}`} key={command.id} onClick={() => run(command)} onMouseEnter={() => setActive(index)} role="option" type="button">{command.label}<kbd>↵</kbd></button>)}{visible.length === 0 && <p>No commands found.</p>}</div><footer><span>↑↓ Navigate</span><span>Esc Close</span></footer></section></div>;
}
function editableTarget(target: EventTarget | null) { if (!(target instanceof Element)) return false; return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [role='textbox']")); }
