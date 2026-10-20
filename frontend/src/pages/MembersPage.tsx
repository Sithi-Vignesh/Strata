import { useEffect, useState } from "react";
import { addWorkspaceMember, removeWorkspaceMember, transferWorkspaceOwnership } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { Avatar } from "../components/ui/Avatar";
import { EmptyState } from "../components/ui/EmptyState";
import type { WorkspaceMember } from "../types/product";

export function MembersPage() {
  const { members, workspaces, currentUser, selectedWorkspaceId, status, retry, refreshWorkspace } = useProduct();
  const workspace = workspaces.find((item) => item.id === selectedWorkspaceId);
  const owner = members.some((member) => member.user_id === currentUser.id && member.role === "OWNER");
  const [email, setEmail] = useState("");
  const [busyId, setBusyId] = useState<number | "add" | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [confirming, setConfirming] = useState<WorkspaceMember | null>(null);

  useEffect(() => { setEmail(""); setMessage(null); setConfirming(null); }, [selectedWorkspaceId]);

  const mutate = async (id: number | "add", action: () => Promise<unknown>, success: string) => {
    setBusyId(id); setMessage(null);
    try { await action(); await refreshWorkspace(); setMessage({ tone: "success", text: success }); return true; }
    catch (reason) { setMessage({ tone: "error", text: reason instanceof Error ? reason.message : "Could not update workspace members." }); return false; }
    finally { setBusyId(null); }
  };
  const add = async () => {
    const value = email.trim();
    if (!/^\S+@\S+\.\S+$/.test(value) || selectedWorkspaceId === null) { setMessage({ tone: "error", text: "Enter a valid member email." }); return; }
    if (await mutate("add", () => addWorkspaceMember(selectedWorkspaceId, value), "Member added to the workspace.")) setEmail("");
  };

  return <section className="page-container">
    <PageHeader eyebrow={workspace?.kind === "PERSONAL" ? "Personal workspace" : "Collaboration"} title="Members" description="Manage who can access this workspace and understand their role." />
    <DataState error={status === "error"} errorMessage="Could not load workspace members." loading={status === "loading"} loadingMessage="Loading members…" onRetry={retry} />
    {status === "ready" && selectedWorkspaceId === null && <EmptyState title="No workspace selected" description="Create or select a workspace to manage its members." />}
    {status === "ready" && workspace?.kind === "PERSONAL" && <EmptyState title="This workspace is private" description="Personal workspaces are available only to their owner. Create a collaborative workspace to work with others." />}
    {status === "ready" && workspace?.kind === "COLLABORATIVE" && <div className="members-layout">
      <section className="panel members-panel" aria-labelledby="workspace-members-heading">
        <div className="panel-header"><div><h2 id="workspace-members-heading">Workspace members</h2><p>{members.length} {members.length === 1 ? "person" : "people"} can access {workspace.name}.</p></div></div>
        <div className="member-list">{members.map((member) => <article className="member-row" key={member.user_id}>
          <Avatar name={member.name} />
          <div className="member-identity"><strong>{member.name}{member.user_id === currentUser.id && <span> (you)</span>}</strong><p>{member.email}</p></div>
          <span className={`role-badge role-${member.role.toLowerCase()}`}>{member.role}</span>
          {owner && member.role === "MEMBER" && <div className="member-actions"><button className="text-button" disabled={busyId !== null} onClick={() => void mutate(member.user_id, () => transferWorkspaceOwnership(workspace!.id, member.user_id), `Ownership transferred to ${member.name}.`)} type="button">Make owner</button><button className="text-button danger-text" disabled={busyId !== null} onClick={() => setConfirming(member)} type="button">Remove</button></div>}
        </article>)}</div>
      </section>
      <aside className="panel invite-panel">
        <span className="kicker">Owner controls</span><h2>Add a teammate</h2><p>Enter the email of an existing Strata account. Access is granted immediately; Strata does not send invitations.</p>
        {owner ? <><label className="field-label" htmlFor="member-page-email">Member email</label><input className="input" id="member-page-email" onChange={(event) => setEmail(event.target.value)} placeholder="teammate@example.com" type="email" value={email} /><button className="button button-primary button-block" disabled={busyId !== null} onClick={() => void add()} type="button">{busyId === "add" ? "Adding…" : "Add member"}</button></> : <div className="info-callout">Only the workspace owner can add or remove members.</div>}
      </aside>
    </div>}
    {message && <p className={`toast-message ${message.tone}`} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p>}
    {confirming && <div className="dialog-backdrop" role="presentation"><section aria-labelledby="remove-member-title" aria-modal="true" className="confirm-dialog" role="dialog"><div className="dialog-icon danger-icon">!</div><h2 id="remove-member-title">Remove {confirming.name}?</h2><p>They will lose access to this workspace and their assigned tasks will become unassigned.</p><div className="dialog-actions"><button className="button button-secondary" disabled={busyId !== null} onClick={() => setConfirming(null)} type="button">Cancel</button><button className="button button-danger" disabled={busyId !== null} onClick={() => void mutate(confirming.user_id, () => removeWorkspaceMember(workspace!.id, confirming.user_id), "Member removed and their tasks unassigned.").then((ok) => { if (ok) setConfirming(null); })} type="button">{busyId === confirming.user_id ? "Removing…" : "Remove member"}</button></div></section></div>}
  </section>;
}
