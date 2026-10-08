import { afterEach, describe, expect, it, vi } from "vitest";
import { createNote, createTask, deleteNote, deleteTask, getUser, listProjectTasks, listTaskNotes, listUserWorkspaces, updateNote, updateTask } from "./product";
import { StrataApiError } from "./strata";

afterEach(() => vi.unstubAllGlobals());

describe("product API client", () => {
  it("reads product entities from product REST routes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ id: 1, name: "Sithi", email: "sithi@strata.local" }))
      .mockResolvedValueOnce(jsonResponse([{ id: 1, name: "Strata Team" }]))
      .mockResolvedValueOnce(jsonResponse([{ id: 1, project_id: 1, title: "Connect frontend", description: null, status: "TODO", priority: "HIGH", assignee_user_id: null }]));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getUser(1)).resolves.toMatchObject({ name: "Sithi" });
    await expect(listUserWorkspaces(1)).resolves.toEqual([{ id: 1, name: "Strata Team" }]);
    await expect(listProjectTasks(1)).resolves.toMatchObject([{ title: "Connect frontend", assignee_user_id: null }]);
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(["/api/users/1", "/api/users/1/workspaces", "/api/projects/1/tasks"]);
  });

  it("preserves domain errors and normalizes FastAPI validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse({ detail: { code: "PRODUCT_NOT_FOUND", message: "User 1 does not exist." } }, 404)).mockResolvedValueOnce(jsonResponse({ detail: [{ msg: "invalid" }] }, 422)));
    await expect(getUser(1)).rejects.toMatchObject({ code: "PRODUCT_NOT_FOUND", status: 404 } satisfies Partial<StrataApiError>);
    await expect(listUserWorkspaces(0)).rejects.toMatchObject({ code: "REQUEST_VALIDATION_ERROR", status: 422 } satisfies Partial<StrataApiError>);
  });

  it("normalizes network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(getUser(1)).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 } satisfies Partial<StrataApiError>);
  });

  it("sends task mutations through product REST and preserves explicit null", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ id: 9, project_id: 1, title: "New", description: null, status: "TODO", priority: "MEDIUM", assignee_user_id: null }, 201))
      .mockResolvedValueOnce(jsonResponse({ id: 9, project_id: 1, title: "New", description: null, status: "TODO", priority: "MEDIUM", assignee_user_id: null }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await createTask(1, { title: "New", assignee_user_id: null });
    await updateTask(9, { description: null, assignee_user_id: null });
    await deleteTask(9);
    expect(fetchMock.mock.calls[0]).toEqual(["/api/projects/1/tasks", expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "New", assignee_user_id: null }) })]);
    expect(fetchMock.mock.calls[1]).toEqual(["/api/tasks/9", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ description: null, assignee_user_id: null }) })]);
    expect(fetchMock.mock.calls[2]).toEqual(["/api/tasks/9", { method: "DELETE" }]);
  });

  it("uses product REST paths for note CRUD", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse([])).mockResolvedValueOnce(jsonResponse({ id: 1, task_id: 2, author_user_id: 1, content: "Note" }, 201)).mockResolvedValueOnce(jsonResponse({ id: 1, task_id: 2, author_user_id: 1, content: "Edited" })).mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await listTaskNotes(2); await createNote(2, { content: "Note" }); await updateNote(1, { content: "Edited" }); await deleteNote(1);
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(["/api/tasks/2/notes", "/api/tasks/2/notes", "/api/notes/1", "/api/notes/1"]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ content: "Note" }) });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "PATCH", body: JSON.stringify({ content: "Edited" }) });
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
