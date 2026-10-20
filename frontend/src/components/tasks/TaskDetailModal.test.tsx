import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TaskDetailModal } from "./TaskDetailModal";
import * as productApi from "../../api/product";

vi.mock("../../api/product", () => ({ createNote: vi.fn(), deleteNote: vi.fn(), listTaskActivity: vi.fn(), listTaskNotes: vi.fn(), updateNote: vi.fn() }));

const user = { id: 1, name: "Sithi", email: "sithi@strata.local" };
const members = { 1: user };
const task = { id: 7, project_id: 1, title: "Task detail", description: "A description", status: "IN_PROGRESS" as const, priority: "HIGH" as const, assignee_user_id: 1 };
const note = { id: 3, task_id: 7, author_user_id: 1, content: "Initial note" };

afterEach(() => { cleanup(); vi.resetAllMocks(); });
beforeEach(() => { vi.mocked(productApi.listTaskActivity).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }); });

describe("TaskDetailModal", () => {
  it("loads task-local notes and renders task details with resolved names", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValue([note]);
    renderDetail();
    expect(screen.getByText("Task detail")).toBeInTheDocument();
    expect(screen.getByText("A description")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Loading notes…")).toBeInTheDocument();
    expect(await screen.findByText("Initial note")).toBeInTheDocument();
    expect(screen.getAllByText("Sithi")).toHaveLength(2);
    expect(productApi.listTaskNotes).toHaveBeenCalledWith(7);
  });

  it("validates and creates notes with the current user, then refreshes", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValueOnce([]).mockResolvedValueOnce([{ ...note, content: "New note" }]);
    vi.mocked(productApi.createNote).mockResolvedValue({ ...note, content: "New note" });
    renderDetail();
    await screen.findByText("No notes yet.");
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Note content cannot be blank.");
    expect(productApi.createNote).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("New note"), { target: { value: "New note" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(productApi.createNote).toHaveBeenCalledWith(7, { content: "New note" }));
    expect(productApi.listTaskNotes).toHaveBeenCalledTimes(2);
  });

  it("prevents duplicate creates while a create is pending", async () => {
    let resolveCreate!: (value: typeof note) => void;
    vi.mocked(productApi.listTaskNotes).mockResolvedValue([]);
    vi.mocked(productApi.createNote).mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
    renderDetail(); await screen.findByText("No notes yet.");
    fireEvent.change(screen.getByLabelText("New note"), { target: { value: "Once" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByRole("button", { name: "Adding…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Adding…" }));
    expect(productApi.createNote).toHaveBeenCalledTimes(1);
    resolveCreate(note);
  });

  it("edits only changed note content and refetches", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValueOnce([note]).mockResolvedValueOnce([{ ...note, content: "Edited" }]);
    vi.mocked(productApi.updateNote).mockResolvedValue({ ...note, content: "Edited" });
    renderDetail(); await screen.findByText("Initial note");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Edit note")).toHaveValue("Initial note");
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(productApi.updateNote).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Edit note"), { target: { value: "Edited" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(productApi.updateNote).toHaveBeenCalledWith(3, { content: "Edited" }));
    expect(productApi.listTaskNotes).toHaveBeenCalledTimes(2);
  });

  it("requires confirmation before deleting and refetches after confirmation", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValueOnce([note]).mockResolvedValueOnce([]);
    vi.mocked(productApi.deleteNote).mockResolvedValue(undefined);
    renderDetail(); await screen.findByText("Initial note");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(productApi.deleteNote).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Delete$/ }));
    await waitFor(() => expect(productApi.deleteNote).toHaveBeenCalledWith(3));
    expect(productApi.listTaskNotes).toHaveBeenCalledTimes(2);
  });

  it("preserves composer text on ordinary failure and distinguishes refresh failure after success", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValueOnce([]).mockRejectedValueOnce(new Error("refresh failed"));
    vi.mocked(productApi.createNote).mockRejectedValueOnce(new Error("create failed")).mockResolvedValueOnce(note);
    renderDetail(); await screen.findByText("No notes yet.");
    fireEvent.change(screen.getByLabelText("New note"), { target: { value: "Keep this" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("create failed");
    expect(screen.getByLabelText("New note")).toHaveValue("Keep this");
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Note was added, but the latest notes could not be refreshed.");
    expect(productApi.createNote).toHaveBeenCalledTimes(2);
  });

  it("does not show stale notes after switching tasks", async () => {
    let resolveA!: (notes: typeof note[]) => void;
    const taskB = { ...task, id: 8, title: "Task B", description: null, assignee_user_id: null };
    vi.mocked(productApi.listTaskNotes).mockImplementation((id) => id === 7 ? new Promise((resolve) => { resolveA = resolve; }) : Promise.resolve([{ ...note, id: 4, task_id: 8, content: "B note" }]));
    const view = renderDetail();
    await waitFor(() => expect(productApi.listTaskNotes).toHaveBeenCalledWith(7));
    view.rerender(<TaskDetailModal currentUser={user} memberUsers={members} onClose={vi.fn()} task={taskB} />);
    await screen.findByText("B note");
    resolveA([note]);
    await waitFor(() => expect(screen.queryByText("Initial note")).not.toBeInTheDocument());
  });

  it("renders newest-first activity changes and handoff notes from the API", async () => {
    vi.mocked(productApi.listTaskNotes).mockResolvedValue([]);
    vi.mocked(productApi.listTaskActivity).mockResolvedValue({ items: [
      { id: 2, task_id: 7, project_id: 1, workspace_id: 1, actor_user_id: 1, event_type: "ASSIGNEE_CHANGED", details: { from: null, to: 1, handoff_note: "Start with the release checklist." }, created_at: 2_000 },
      { id: 1, task_id: 7, project_id: 1, workspace_id: 1, actor_user_id: 1, event_type: "TASK_CREATED", details: null, created_at: 1_000 },
    ], total: 2, limit: 20, offset: 0 });
    renderDetail();
    const changes = await screen.findAllByText(/changed|created/i);
    expect(changes[0]).toHaveTextContent("Assignee changed");
    expect(screen.getByText(/Start with the release checklist/)).toBeInTheDocument();
    expect(productApi.listTaskActivity).toHaveBeenCalledWith(7, 20, 0);
  });

  it("shows activity errors and never retains activity from a prior task", async () => {
    let resolveA!: (value: { items: never[]; total: number; limit: number; offset: number }) => void;
    const taskB = { ...task, id: 8, title: "Task B" };
    vi.mocked(productApi.listTaskNotes).mockResolvedValue([]);
    vi.mocked(productApi.listTaskActivity).mockImplementation((id) => id === 7 ? new Promise((resolve) => { resolveA = resolve; }) : Promise.reject(new Error("Activity access revoked.")));
    const view = renderDetail();
    await waitFor(() => expect(productApi.listTaskActivity).toHaveBeenCalledWith(7, 20, 0));
    view.rerender(<TaskDetailModal currentUser={user} memberUsers={members} onClose={vi.fn()} task={taskB} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Activity access revoked.");
    resolveA({ items: [], total: 0, limit: 20, offset: 0 });
    await waitFor(() => expect(screen.queryByText("Task created")).not.toBeInTheDocument());
  });
});

function renderDetail() { return render(<TaskDetailModal currentUser={user} memberUsers={members} onClose={vi.fn()} task={task} />); }

it("keeps teammates' notes readable without offering author-only mutations", async () => {
  vi.mocked(productApi.listTaskNotes).mockResolvedValue([{ ...note, author_user_id: 2 }]);
  renderDetail(); await screen.findByText("Initial note");
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
});
