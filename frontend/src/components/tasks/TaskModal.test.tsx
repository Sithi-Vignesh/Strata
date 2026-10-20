import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskDeleteConfirmation, TaskModal } from "./TaskModal";

const task = { id: 1, project_id: 1, title: "Task", description: "Details", status: "TODO" as const, priority: "HIGH" as const, assignee_user_id: 1 };
const members = { 1: { id: 1, name: "Sithi", email: "sithi@strata.local" } };

afterEach(cleanup);

describe("TaskModal", () => {
  it("validates a blank title and supplies visible backend defaults for create", () => {
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} task={null} />);
    expect(screen.getByLabelText("Status")).toHaveValue("TODO");
    expect(screen.getByLabelText("Priority")).toHaveValue("MEDIUM");
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Task title cannot be blank.");
  });

  it("builds a minimal PATCH and preserves explicit null when clearing fields", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={vi.fn()} onUpdate={onUpdate} task={task} />);
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(task, { description: null, assignee_user_id: null }));
  });

  it("keeps the form open when its caller reports that the mutation did not commit", async () => {
    const onCreate = vi.fn().mockResolvedValue(false);
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} task={null} />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Follow up" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("creates with a due date and clears an existing due date explicitly", async () => {
    const onCreate = vi.fn().mockResolvedValue(true), onUpdate = vi.fn().mockResolvedValue(true);
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={onCreate} onUpdate={onUpdate} task={null} />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Dated work" } });
    fireEvent.change(screen.getByLabelText(/Due date/), { target: { value: "2027-02-28" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ due_date: "2027-02-28" })));
    cleanup();
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={onCreate} onUpdate={onUpdate} task={{ ...task, due_date: "2027-02-28" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear due date" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(expect.anything(), { due_date: null }));
  });

  it("submits a handoff only for a real reassignment and preserves it after failure", async () => {
    const onUpdate = vi.fn().mockResolvedValue(false);
    render(<TaskModal memberUsers={{ ...members, 2: { id: 2, name: "Ada", email: "ada@strata.local" } }} onClose={vi.fn()} onCreate={vi.fn()} onUpdate={onUpdate} task={task} />);
    expect(screen.queryByLabelText(/Handoff note/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/Handoff note/), { target: { value: "Start with the checklist." } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(task, { assignee_user_id: 2, handoff_note: "Start with the checklist." }));
    expect(screen.getByLabelText(/Handoff note/)).toHaveValue("Start with the checklist.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("requires explicit confirmation before deletion", () => {
    const onConfirm = vi.fn().mockResolvedValue(true);
    render(<TaskDeleteConfirmation onCancel={vi.fn()} onConfirm={onConfirm} task={task} />);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete task" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
