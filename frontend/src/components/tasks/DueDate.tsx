import type { Task } from "../../types/product";

export type DueState = "overdue" | "today" | "soon" | "future";

export function dateOnlyToday(now = new Date()): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dueState(dueDate: string, today = dateOnlyToday()): DueState {
  if (dueDate < today) return "overdue";
  if (dueDate === today) return "today";
  const start = calendarNumber(today);
  const end = calendarNumber(dueDate);
  return end - start <= 7 ? "soon" : "future";
}

export function formatDateOnly(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, day)));
}

export function DueDate({ dueDate, status }: { dueDate: string | null; status?: Task["status"] }) {
  if (!dueDate) return <span className="due-date due-none">No due date</span>;
  const state = status === "DONE" ? "future" : dueState(dueDate);
  const label = state === "overdue" ? "Overdue" : state === "today" ? "Due today" : state === "soon" ? "Due soon" : "Due";
  return <span className={`due-date due-${state}`}><span aria-hidden="true">◷</span>{label}: {formatDateOnly(dueDate)}</span>;
}

function calendarNumber(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Math.floor(Date.UTC(year, month - 1, day) / 86_400_000);
}
