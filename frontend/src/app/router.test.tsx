import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routes } from "./router";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("application routing", () => {
  it("renders the shell navigation and active Tasks route", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok",
      service: "strata_backend",
      engine: { name: "StrataEngine", status: "open", initialized: true },
    }))));
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
    expect(screen.getAllByText("Backend: Connected")).toHaveLength(2);
  });
});
