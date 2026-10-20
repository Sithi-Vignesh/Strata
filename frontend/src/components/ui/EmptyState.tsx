import type { ReactNode } from "react";

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <section className="empty-state">
    {icon && <div className="empty-state-icon">{icon}</div>}
    <h2>{title}</h2>
    <p>{description}</p>
    {action && <div className="empty-state-action">{action}</div>}
  </section>;
}
