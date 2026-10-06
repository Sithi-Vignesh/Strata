import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routes } from "./router";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("application routing", () => {
  it("renders the Tasks placeholder for the tasks route", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok",
      service: "strata_backend",
      engine: { name: "StrataEngine", status: "open", initialized: true },
    }))));
    const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByText("Backend: connected")).toBeInTheDocument();
  });
});
