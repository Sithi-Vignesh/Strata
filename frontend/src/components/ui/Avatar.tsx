export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const initials = avatarInitials(name);
  return <span aria-hidden="true" className={`avatar avatar-${size}`}>{initials}</span>;
}

export function avatarInitials(name: string): string {
  const parts = name.trim().split(/\s+/u).filter(Boolean);
  if (parts.length === 0) return "?";
  const selected = parts.length === 1 ? parts : [parts[0], parts.at(-1)!];
  return selected.map((part) => Array.from(part.replace(/^[^\p{L}\p{N}]+/u, ""))[0] ?? "").join("").toLocaleUpperCase().slice(0, 2) || "?";
}
