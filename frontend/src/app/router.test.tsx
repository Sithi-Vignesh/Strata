import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routes } from "./router";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("application routing", () => {
  it("renders the shell navigation and active Tasks route", async () => {
    vi.stubGlobal("fetch", vi.fn((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ id: 1, name: "Sithi", email: "sithi@strata.local" })));
      if (path === "/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok", service: "strata_backend", engine: { name: "StrataEngine", status: "open", initialized: true } })));
      if (path === "/api/users/1/workspaces") return Promise.resolve(new Response(JSON.stringify([])));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    }));
    const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Database" })).toBeInTheDocument();

    const links = [["Overview", "/"], ["Tasks", "/tasks"], ["Board", "/board"], ["SQL Console", "/sql"], ["Engine", "/engine"]] as const;
    for (const [name, href] of links) {
      const matchingLinks = screen.getAllByRole("link", { name });
      expect(matchingLinks).toHaveLength(2);
      matchingLinks.forEach((link) => expect(link).toHaveAttribute("href", href));
    }

    screen.getAllByRole("link", { name: "Tasks" }).forEach((link) => {
      expect(link).toHaveAttribute("aria-current", "page");
    });
    expect(await screen.findAllByText("Backend: Connected")).toHaveLength(2);
  });

  it("keeps technical routes available when product initialization fails", async () => {
    vi.stubGlobal("fetch", vi.fn((path: string) => {
      if (path === "/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok", service: "strata_backend", engine: { name: "StrataEngine", status: "open", initialized: true } })));
      return Promise.reject(new TypeError("Failed to fetch"));
    }));
    const router = createMemoryRouter(routes, { initialEntries: ["/engine"] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Strata Database Engine" })).toBeInTheDocument();
  });

  it("sends an unauthenticated protected route to the sign-in flow", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: { code: "AUTHENTICATION_REQUIRED", message: "Authentication required." } }), { status: 401 }))));
    const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Tasks" })).not.toBeInTheDocument();
  });

  it("clears authenticated product UI after successful logout", async () => {
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ id: 1, name: "Sithi", email: "sithi@strata.local" })));
      if (path === "/api/users/1/workspaces") return Promise.resolve(new Response(JSON.stringify([])));
      if (path === "/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok", service: "strata_backend", engine: { name: "StrataEngine", status: "open", initialized: true } })));
      if (path === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sign out" })).toHaveLength(2);
    screen.getAllByRole("button", { name: "Sign out" })[0].click();
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
  });

  it("keeps product UI and shows safe feedback when logout fails", async () => {
    vi.stubGlobal("fetch", vi.fn((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ id: 1, name: "Sithi", email: "sithi@strata.local" })));
      if (path === "/api/users/1/workspaces") return Promise.resolve(new Response(JSON.stringify([])));
      if (path === "/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok", service: "strata_backend", engine: { name: "StrataEngine", status: "open", initialized: true } })));
      if (path === "/api/auth/logout") return Promise.resolve(new Response(JSON.stringify({ detail: { code: "INTERNAL", message: "Internal detail" } }), { status: 500 }));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    }));
    const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    screen.getAllByRole("button", { name: "Sign out" })[0].click();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign you out. Please try again.");
    expect(screen.getByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.queryByText("Internal detail")).not.toBeInTheDocument();
  });
});
