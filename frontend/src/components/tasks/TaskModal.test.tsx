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

  it("keeps the form open when a save succeeds but the task refresh fails", async () => {
    const onCreate = vi.fn().mockResolvedValue(false);
    render(<TaskModal memberUsers={members} onClose={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} task={null} />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Follow up" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
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
