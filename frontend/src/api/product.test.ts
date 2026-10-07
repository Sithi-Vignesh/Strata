import { afterEach, describe, expect, it, vi } from "vitest";
import { getUser, listProjectTasks, listUserWorkspaces } from "./product";
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
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
