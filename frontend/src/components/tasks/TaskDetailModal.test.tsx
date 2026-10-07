import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskDetailModal } from "./TaskDetailModal";
import * as productApi from "../../api/product";

vi.mock("../../api/product", () => ({ createNote: vi.fn(), deleteNote: vi.fn(), listTaskNotes: vi.fn(), updateNote: vi.fn() }));

const user = { id: 1, name: "Sithi", email: "sithi@strata.local" };
const members = { 1: user };
const task = { id: 7, project_id: 1, title: "Task detail", description: "A description", status: "IN_PROGRESS" as const, priority: "HIGH" as const, assignee_user_id: 1 };
const note = { id: 3, task_id: 7, author_user_id: 1, content: "Initial note" };

afterEach(() => { cleanup(); vi.resetAllMocks(); });

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
    await waitFor(() => expect(productApi.createNote).toHaveBeenCalledWith(7, { author_user_id: 1, content: "New note" }));
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
});

function renderDetail() { return render(<TaskDetailModal currentUser={user} memberUsers={members} onClose={vi.fn()} task={task} />); }
