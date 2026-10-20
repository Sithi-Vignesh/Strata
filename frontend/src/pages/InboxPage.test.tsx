import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InboxPage } from "./InboxPage";

vi.mock("../app/ProductContext", () => ({ useProduct: () => ({ refreshWorkspace: vi.fn().mockResolvedValue(undefined) }) }));
vi.mock("../api/product", () => ({ listNotifications: vi.fn(), setNotificationRead: vi.fn(), markAllNotificationsRead: vi.fn(), dismissNotification: vi.fn() }));
import { dismissNotification, listNotifications, markAllNotificationsRead, setNotificationRead } from "../api/product";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const notification = { id: 8, recipient_user_id: 1, event_type: "TASK_ASSIGNED", summary: "A task was assigned to you.", workspace_id: 2, project_id: 3, task_id: 4, created_at: 1_760_000_000_000, is_read: false, dismissed_at: null };

describe("InboxPage", () => {
  it("renders notifications and supports read, unread, and mark-all actions", async () => {
    let isRead = false;
    vi.mocked(listNotifications).mockImplementation(async () => ({ items: [{ ...notification, is_read: isRead }], total: 1, limit: 20, offset: 0 }));
    vi.mocked(setNotificationRead).mockImplementation(async (_id, next) => { isRead = next; return { ...notification, is_read: next }; });
    vi.mocked(markAllNotificationsRead).mockImplementation(async () => { isRead = true; return { updated: 1 }; });
    render(<MemoryRouter><InboxPage /></MemoryRouter>);
    expect(await screen.findByText(notification.summary)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark read" }));
    await waitFor(() => expect(setNotificationRead).toHaveBeenCalledWith(8, true));
    expect(await screen.findByRole("button", { name: "Mark unread" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark unread" }));
    await waitFor(() => expect(setNotificationRead).toHaveBeenLastCalledWith(8, false));
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(markAllNotificationsRead).toHaveBeenCalledTimes(1));
  });

  it("rolls a failed dismissal back into the list", async () => {
    vi.mocked(listNotifications).mockResolvedValue({ items: [notification], total: 1, limit: 20, offset: 0 });
    vi.mocked(dismissNotification).mockRejectedValue(new Error("Dismiss failed"));
    render(<MemoryRouter><InboxPage /></MemoryRouter>);
    expect(await screen.findByText(notification.summary)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Dismiss failed");
    expect(screen.getByText(notification.summary)).toBeInTheDocument();
  });
});
